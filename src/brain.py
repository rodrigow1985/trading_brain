"""
Cerebro de trading — Fase 2 (refactor multi-proveedor).

Función pública principal:
    analizar(contexto: ContextoMercado) -> DecisionCerebro

Evalúa el contexto multi-timeframe pasándolo al LLM via tool use y
devuelve una decisión estructurada validada.

Proveedores soportados (LLM_PROVIDER en el entorno):
    anthropic  — Claude (default)
    gemini     — Google Gemini via google-generativeai
    groq       — Groq via groq SDK (API compatible con OpenAI)

Restricciones innegociables:
- NO importa ccxt, pandas, ni pandas_ta.
- Variables de entorno desde .env via python-dotenv.
- Logging con el módulo estándar logging, no print.
- Type hints en todas las funciones públicas.
- Ante cualquier falla no contemplada → fallback, nunca propagar excepción al caller.
- Imports de SDKs de terceros (google-generativeai, groq) son lazy: se hacen dentro
  de cada función _llamar_* para que el módulo cargue sin errores si el SDK no está
  instalado.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from src.types import ContextoMercado, DecisionCerebro

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MAX_TOKENS = 1024
_TEMPERATURE = 0.1
_TOOL_CHOICE: dict[str, str] = {"type": "tool", "name": "decision_cerebro"}

_REGIMENES_VALIDOS = {"tendencia_alcista", "tendencia_bajista", "rango", "volatil"}
_EVALUACIONES_VALIDAS = {"confirmar", "vetar", "neutral"}

_FALLBACK: DecisionCerebro = {
    "regimen": "rango",
    "confianza_regimen": 0.0,
    "evaluacion_senal": "neutral",
    "conviccion": 0.0,
    "multiplicador_riesgo": 0.0,
    "factores_clave": ["respuesta default por falla en el cerebro"],
    "racional": "Cerebro no disponible — operando en modo seguro.",
    "alertas": ["FALLBACK_ACTIVADO"],
}

_SYSTEM_PROMPT = """\
Eres un analista de trading de criptomonedas con experiencia en análisis técnico
multi-timeframe (MTF). Tu rol es evaluar si el contexto de mercado actual es
coherente con una señal de trading candidata, y devolver una decisión estructurada.

IMPORTANTE — lo que NO eres:
- No predices precios futuros.
- No generas señales de trading propias.
- No ajustás stops ni límites de posición (eso lo hace el sistema de ejecución).

REGLAS INNEGOCIABLES:
1. Ante cualquier ambigüedad, preferí "neutral" sobre "confirmar".
2. El multiplicador_riesgo nunca puede superar 1.0.
3. Si el contexto que recibís es insuficiente para una conclusión, devolvé
   evaluacion_senal = "neutral" y explicá qué falta en factores_clave.
4. Respondé únicamente con el JSON estructurado solicitado. Sin texto adicional.

JERARQUÍA DE TIMEFRAMES (crítico — respetá este orden siempre):

El análisis es top-down. Los timeframes mayores mandan sobre los menores:

  1W  →  tendencia macro de largo plazo (si presente en el contexto, tiene PRIORIDAD ABSOLUTA)
  4H  →  define el sesgo direccional dominante
  1D  →  confirma la estructura macro (soportes, resistencias, tendencia de fondo)
  1H  →  solo marca el TIMING de entrada, nunca define el régimen

El RÉGIMEN que declarás debe reflejar la tendencia del 4H y el 1D, NO del 1H.
Si el 1H está lateral pero el 4H y el 1D son bajistas, el régimen es
"tendencia_bajista" — no "rango". El rango en 1H es solo una pausa dentro de
la tendencia mayor.

REGLAS MTF DE EVALUACIÓN:

Si hay datos de 1W en el contexto (campo "1w" en timeframes):
- LONG con 1W bajista → VETAR SIEMPRE, sin excepción. La tendencia semanal en contra
  invalida cualquier setup de entrada LONG.
- SHORT con 1W alcista → VETAR SIEMPRE, sin excepción.
- LONG con 1W alcista + 1D alcista + 4H alcista → alineación perfecta, confirmar con
  riesgo alto (0.8–1.0)
- LONG con 1W alcista + 1D alcista + 4H lateral o débil → confirmar con riesgo moderado
  (0.5–0.7)

Reglas generales (con o sin 1W):
- LONG con 1D alcista + 4H alcista → coherente, podés confirmar con riesgo normal
- LONG con 1D bajista (contra-tendencia) → reducir multiplicador fuertemente (0.0–0.3)
  o vetar directamente. Operar LONG contra una tendencia bajista en 1D es de alto riesgo.
- SHORT con 1D bajista + 4H bajista → coherente, podés confirmar con riesgo normal
- SHORT con 1D alcista (contra-tendencia) → reducir multiplicador fuertemente o vetar
- Si 4H y 1D apuntan en direcciones opuestas → régimen "rango" o "volatil",
  multiplicador máximo 0.5, ser conservador

CÓMO RAZONAR:

1. Régimen de mercado
   Determiná el régimen basándote PRIMERO en 4H y 1D:
   - tendencia_alcista: 4H alcista y 1D alcista (precio > EMA rápida > EMA lenta en ambos)
   - tendencia_bajista: 4H bajista y 1D bajista (precio < EMA rápida < EMA lenta en ambos)
   - rango: 4H y 1D sin alineación clara, o ambos laterales
   - volatil: ATR elevado en 4H/1D, estructura de máximos/mínimos irregular

   El 1H es contexto secundario. Si el 1H está lateral dentro de un 4H bajista,
   el régimen sigue siendo tendencia_bajista.

2. Evaluación de la señal
   - senal_base = NONE: siempre "neutral", multiplicador_riesgo = 0.0
   - LONG en tendencia_alcista MTF: confirmar con multiplicador alto (0.7–1.0)
   - LONG en tendencia_bajista MTF: vetar o multiplicador muy bajo (0.0–0.2)
   - SHORT en tendencia_bajista MTF: confirmar con multiplicador alto (0.7–1.0)
   - SHORT en tendencia_alcista MTF: vetar o multiplicador muy bajo (0.0–0.2)
   - Señal en "rango": confirmar solo si hay contexto favorable (soporte/resistencia claro),
     multiplicador moderado (0.3–0.6)
   - Señal en "volatil": muy conservador, multiplicador máximo 0.3

3. Multiplicador de riesgo
   - Señal alineada con tendencia MTF clara: 0.7–1.0
   - Señal en rango con contexto favorable: 0.3–0.6
   - Señal contra-tendencia o régimen incierto: 0.0–0.2
   - Veto: siempre 0.0

4. Racional para Telegram
   Máximo 280 caracteres. Mencioná explícitamente la alineación (o no) entre
   timeframes. Ejemplo: "4H y 1D bajistas — LONG contra-tendencia vetado.
   Estructura macro no apoya la entrada."

5. Alertas
   Condiciones relevantes adicionales. Ejemplos: "RSI > 70 en 1H — sobrecompra",
   "Divergencia 4H/1D — contexto mixto", "Volumen bajo — señal débil"
"""

# ---------------------------------------------------------------------------
# System prompt y tool para el scanner (contextualización, sin veto)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_SCANNER = """\
Sos un analista técnico especializado en análisis multi-timeframe.

El scanner detectó una condición técnica en el activo. Tu trabajo es
COMPLEMENTAR con contexto de calidad — no tomás decisiones de entrada ni salida,
y no podés cancelar la alerta.

Leé el campo senal_base del contexto para orientar tu análisis:
  - "LONG"  → hay un setup alcista validado; enfocar en si el contexto lo respalda
  - "SHORT" → hay un setup bajista validado; enfocar en si el contexto lo respalda
  - "NONE"  → es una alerta informativa; analizá sin imponer dirección, describí
               qué significa la condición y qué opciones tiene el trader

Escribí entre 5 y 6 líneas en prosa fluida (sin bullet points ni listas) que cubran:
1. Qué significa esta condición técnica en el contexto actual del activo
2. Calidad y madurez de la tendencia dominante (4H y 1D)
3. Estructura de precio: niveles clave cercanos (soporte/resistencia más relevante)
4. Comportamiento del volumen: ¿confirma o diverge?
5. Factores de riesgo o cautela específicos que el trader debería considerar

Sé técnico, concreto y útil. El texto va directo a Telegram. Máximo 6 líneas.
"""

_TOOL_CONTEXTO_SCANNER: dict[str, Any] = {
    "name": "contexto_scanner",
    "description": "Análisis contextual del setup detectado por el scanner.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analisis": {
                "type": "string",
                "description": "Análisis en prosa, 5-6 líneas, sin bullet points.",
            },
            "nivel_atencion": {
                "type": "string",
                "enum": ["alto", "medio", "bajo"],
                "description": "Qué tanto merece la pena prestar atención al setup.",
            },
            "alertas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Máximo 3 factores de riesgo concretos.",
            },
        },
        "required": ["analisis", "nivel_atencion", "alertas"],
    },
}

_TOOL_CONTEXTO_SCANNER_OPENAI: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "contexto_scanner",
        "description": "Análisis contextual del setup detectado por el scanner.",
        "parameters": _TOOL_CONTEXTO_SCANNER["input_schema"],
    },
}

_FALLBACK_CONTEXTO: dict[str, Any] = {
    "analisis": "Análisis no disponible — el cerebro no pudo procesar el contexto en este momento.",
    "nivel_atencion": "medio",
    "alertas": ["FALLBACK_ACTIVADO"],
}

# ---------------------------------------------------------------------------
# Tool schema para Anthropic (formato nativo)
# ---------------------------------------------------------------------------

_TOOL_DECISION: dict[str, Any] = {
    "name": "decision_cerebro",
    "description": "Devuelve la evaluación del cerebro sobre la señal candidata.",
    "input_schema": {
        "type": "object",
        "properties": {
            "regimen": {
                "type": "string",
                "enum": ["tendencia_alcista", "tendencia_bajista", "rango", "volatil"],
            },
            "confianza_regimen": {"type": "number"},
            "evaluacion_senal": {
                "type": "string",
                "enum": ["confirmar", "vetar", "neutral"],
            },
            "conviccion": {"type": "number"},
            "multiplicador_riesgo": {"type": "number"},
            "factores_clave": {"type": "array", "items": {"type": "string"}},
            "racional": {"type": "string"},
            "alertas": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "regimen",
            "confianza_regimen",
            "evaluacion_senal",
            "conviccion",
            "multiplicador_riesgo",
            "factores_clave",
            "racional",
            "alertas",
        ],
    },
}

# Tool schema para Groq/OpenAI (reutiliza el input_schema de Anthropic)
_TOOL_DECISION_OPENAI: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "decision_cerebro",
        "description": "Devuelve la evaluación del cerebro sobre la señal candidata.",
        "parameters": _TOOL_DECISION["input_schema"],
    },
}

# ---------------------------------------------------------------------------
# Helpers de validación de entrada
# ---------------------------------------------------------------------------

def _validar_contexto(contexto: ContextoMercado) -> tuple[bool, str]:
    """
    Valida que todos los campos requeridos estén presentes y dentro de rango.
    Devuelve (True, "") si es válido, o (False, razón) si no.
    """
    # Campos raíz obligatorios
    for campo in ("par", "timestamp", "mercado_tipo", "senal_base", "portfolio", "timeframes"):
        if campo not in contexto:
            return False, f"campo requerido ausente: '{campo}'"

    # par: no vacío (cripto lleva "/", acciones no — ambos formatos válidos)
    par = contexto.get("par", "")
    if not par:
        return False, f"par inválido: '{par}'"

    # timestamp: parseable como ISO 8601
    timestamp = contexto.get("timestamp", "")
    if not timestamp:
        return False, "timestamp vacío"
    try:
        datetime.fromisoformat(str(timestamp))
    except (ValueError, TypeError):
        return False, f"timestamp no parseable: '{timestamp}'"

    # mercado_tipo
    if contexto.get("mercado_tipo") not in ("spot", "futuro"):
        return False, f"mercado_tipo inválido: '{contexto.get('mercado_tipo')}'"

    # senal_base
    if contexto.get("senal_base") not in ("LONG", "SHORT", "NONE"):
        return False, f"senal_base inválido: '{contexto.get('senal_base')}'"

    # portfolio
    portfolio = contexto.get("portfolio", {})
    if not isinstance(portfolio, dict):
        return False, "portfolio no es un dict"
    riesgo = portfolio.get("riesgo_disponible_pct")
    if riesgo is None:
        return False, "portfolio.riesgo_disponible_pct ausente"
    try:
        riesgo_f = float(riesgo)
    except (TypeError, ValueError):
        return False, "portfolio.riesgo_disponible_pct no es numérico"
    if not (0.0 <= riesgo_f <= 1.0):
        return False, f"portfolio.riesgo_disponible_pct fuera de rango: {riesgo_f}"

    # timeframes: claves exactas requeridas
    timeframes = contexto.get("timeframes", {})
    if not isinstance(timeframes, dict):
        return False, "timeframes no es un dict"
    for tf in ("4h", "1d", "1h"):
        if tf not in timeframes:
            return False, f"timeframe ausente: '{tf}'"

    # Validar cada timeframe
    for tf_key in ("4h", "1d", "1h"):
        tf_data = timeframes[tf_key]
        ok, reason = _validar_timeframe(tf_key, tf_data)
        if not ok:
            return False, reason

    return True, ""


def _validar_timeframe(tf_key: str, tf_data: dict) -> tuple[bool, str]:
    """Valida los campos de indicadores y estructura de un timeframe."""
    if not isinstance(tf_data, dict):
        return False, f"timeframe {tf_key} no es un dict"

    # indicadores
    indicadores = tf_data.get("indicadores")
    if not isinstance(indicadores, dict):
        return False, f"{tf_key}.indicadores ausente o no es dict"

    # RSI [0, 100]
    rsi = indicadores.get("rsi")
    if rsi is None:
        return False, f"{tf_key}.indicadores.rsi ausente"
    try:
        rsi_f = float(rsi)
    except (TypeError, ValueError):
        return False, f"{tf_key}.indicadores.rsi no es numérico"
    if not (0.0 <= rsi_f <= 100.0):
        return False, f"{tf_key}.indicadores.rsi fuera de rango: {rsi_f}"

    # ATR > 0
    atr = indicadores.get("atr")
    if atr is None:
        return False, f"{tf_key}.indicadores.atr ausente"
    try:
        atr_f = float(atr)
    except (TypeError, ValueError):
        return False, f"{tf_key}.indicadores.atr no es numérico"
    if atr_f <= 0.0:
        return False, f"{tf_key}.indicadores.atr debe ser > 0: {atr_f}"

    # volumen >= 0
    vol = indicadores.get("volumen")
    if vol is None:
        return False, f"{tf_key}.indicadores.volumen ausente"
    try:
        vol_f = float(vol)
    except (TypeError, ValueError):
        return False, f"{tf_key}.indicadores.volumen no es numérico"
    if vol_f < 0.0:
        return False, f"{tf_key}.indicadores.volumen debe ser >= 0: {vol_f}"

    # volumen_promedio > 0
    vol_prom = indicadores.get("volumen_promedio")
    if vol_prom is None:
        return False, f"{tf_key}.indicadores.volumen_promedio ausente"
    try:
        vol_prom_f = float(vol_prom)
    except (TypeError, ValueError):
        return False, f"{tf_key}.indicadores.volumen_promedio no es numérico"
    if vol_prom_f <= 0.0:
        return False, f"{tf_key}.indicadores.volumen_promedio debe ser > 0: {vol_prom_f}"

    # estructura
    estructura = tf_data.get("estructura")
    if not isinstance(estructura, dict):
        return False, f"{tf_key}.estructura ausente o no es dict"

    # maximos_recientes: lista de longitud 5
    maximos = estructura.get("maximos_recientes")
    if not isinstance(maximos, list) or len(maximos) != 5:
        return False, f"{tf_key}.estructura.maximos_recientes debe ser lista de 5 elementos"

    # minimos_recientes: lista de longitud 5
    minimos = estructura.get("minimos_recientes")
    if not isinstance(minimos, list) or len(minimos) != 5:
        return False, f"{tf_key}.estructura.minimos_recientes debe ser lista de 5 elementos"

    # tendencia
    if estructura.get("tendencia") not in ("alcista", "bajista", "lateral"):
        return False, f"{tf_key}.estructura.tendencia inválido: '{estructura.get('tendencia')}'"

    return True, ""


# ---------------------------------------------------------------------------
# Helpers de validación de salida y corrección
# ---------------------------------------------------------------------------

def _fallback_con_razon(razon: str) -> DecisionCerebro:
    """Devuelve el fallback estándar y loguea la razón."""
    logger.warning("Fallback activado — razón: %s", razon)
    resultado = dict(_FALLBACK)
    resultado["alertas"] = ["FALLBACK_ACTIVADO", razon]
    return DecisionCerebro(**resultado)  # type: ignore[arg-type]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _validar_y_corregir_salida(
    raw: dict[str, Any],
    riesgo_disponible_pct: float,
) -> DecisionCerebro | None:
    """
    Valida y corrige la respuesta del tool use.
    Devuelve DecisionCerebro corregida, o None si hay un fallo no recuperable.
    """
    alertas: list[str] = list(raw.get("alertas", []))

    # --- Campos enum (fallo completo si inválido) ---
    regimen = raw.get("regimen")
    if regimen not in _REGIMENES_VALIDOS:
        logger.error("regimen inválido recibido: '%s'", regimen)
        return None

    evaluacion_senal = raw.get("evaluacion_senal")
    if evaluacion_senal not in _EVALUACIONES_VALIDAS:
        logger.error("evaluacion_senal inválida recibida: '%s'", evaluacion_senal)
        return None

    # --- Floats con clampeo ---
    confianza_regimen = raw.get("confianza_regimen", 0.0)
    try:
        confianza_regimen_f = float(confianza_regimen)
    except (TypeError, ValueError):
        logger.error("confianza_regimen no es numérico: '%s'", confianza_regimen)
        return None
    if not (0.0 <= confianza_regimen_f <= 1.0):
        logger.warning("confianza_regimen fuera de rango (%.4f) — clampeando", confianza_regimen_f)
        alertas.append(f"anomalía: confianza_regimen={confianza_regimen_f} clampeado")
        confianza_regimen_f = _clamp(confianza_regimen_f, 0.0, 1.0)

    conviccion = raw.get("conviccion", 0.0)
    try:
        conviccion_f = float(conviccion)
    except (TypeError, ValueError):
        logger.error("conviccion no es numérico: '%s'", conviccion)
        return None
    if not (0.0 <= conviccion_f <= 1.0):
        logger.warning("conviccion fuera de rango (%.4f) — clampeando", conviccion_f)
        alertas.append(f"anomalía: conviccion={conviccion_f} clampeado")
        conviccion_f = _clamp(conviccion_f, 0.0, 1.0)

    multiplicador_riesgo = raw.get("multiplicador_riesgo", 0.0)
    try:
        mult_f = float(multiplicador_riesgo)
    except (TypeError, ValueError):
        logger.error("multiplicador_riesgo no es numérico: '%s'", multiplicador_riesgo)
        return None
    if mult_f > 1.0:
        logger.warning(
            "multiplicador_riesgo > 1.0 (%.4f) — clampeando a 1.0 (anomalía)", mult_f
        )
        alertas.append(f"anomalía: multiplicador_riesgo={mult_f} clampeado a 1.0")
        mult_f = 1.0
    elif mult_f < 0.0:
        logger.warning("multiplicador_riesgo < 0.0 (%.4f) — clampeando a 0.0", mult_f)
        alertas.append(f"anomalía: multiplicador_riesgo={mult_f} clampeado a 0.0")
        mult_f = 0.0

    # --- factores_clave: lista[str] longitud [1, 5] (fallo completo si inválido) ---
    factores_clave = raw.get("factores_clave")
    if not isinstance(factores_clave, list) or len(factores_clave) < 1:
        logger.error("factores_clave vacío o no es lista: %s", factores_clave)
        return None
    if len(factores_clave) > 5:
        logger.warning("factores_clave tiene %d elementos — truncando a 5", len(factores_clave))
        factores_clave = factores_clave[:5]

    # --- racional: str no vacío, máx 280 chars ---
    racional = raw.get("racional", "")
    if not isinstance(racional, str) or not racional.strip():
        logger.error("racional vacío o no es string")
        return None
    if len(racional) > 280:
        logger.warning("racional supera 280 chars (%d) — truncando", len(racional))
        alertas.append("anomalía: racional truncado a 280 caracteres")
        racional = racional[:277] + "..."

    # --- Caso borde: riesgo_disponible_pct == 0.0 → forzar multiplicador a 0.0 ---
    if riesgo_disponible_pct == 0.0 and mult_f != 0.0:
        logger.info(
            "riesgo_disponible_pct=0.0 — clampeando multiplicador_riesgo de %.4f a 0.0", mult_f
        )
        alertas.append("multiplicador_riesgo forzado a 0.0 por riesgo_disponible_pct=0.0")
        mult_f = 0.0

    return DecisionCerebro(
        regimen=regimen,
        confianza_regimen=confianza_regimen_f,
        evaluacion_senal=evaluacion_senal,
        conviccion=conviccion_f,
        multiplicador_riesgo=mult_f,
        factores_clave=factores_clave,
        racional=racional,
        alertas=alertas,
    )


# ---------------------------------------------------------------------------
# Implementaciones por proveedor (imports lazy dentro de cada función)
# ---------------------------------------------------------------------------

def _llamar_anthropic(user_message: str) -> dict | None:
    """
    Llama a Claude via Anthropic SDK con tool use forzado.
    Devuelve el input del tool como dict, o None si hubo error.
    """
    import anthropic  # lazy: solo si LLM_PROVIDER=anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY no definida en el entorno")
        return None

    model = os.environ.get("LLM_MODEL") or "claude-sonnet-4-6"

    logger.info("Proveedor: anthropic | Modelo: %s", model)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL_DECISION],
            tool_choice=_TOOL_CHOICE,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        logger.error("Error de API de Anthropic: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Excepción inesperada llamando a Anthropic: %s", exc)
        return None

    # Buscar el bloque tool_use en la respuesta
    for block in response.content:
        if block.type == "tool_use" and block.name == "decision_cerebro":
            raw_input = block.input
            if not isinstance(raw_input, dict):
                logger.error("tool_use.input no es un dict: %s", type(raw_input))
                return None
            logger.debug("Respuesta raw del tool (anthropic): %s", raw_input)
            return raw_input

    logger.error(
        "El LLM no llamó al tool 'decision_cerebro'. stop_reason=%s content=%s",
        response.stop_reason,
        response.content,
    )
    return None


def _llamar_gemini(user_message: str) -> dict | None:
    """
    Llama a Gemini via google-genai SDK con function calling forzado.
    Devuelve el input del tool como dict, o None si hubo error.
    """
    try:
        from google import genai  # lazy: solo si LLM_PROVIDER=gemini
        from google.genai import types as genai_types
    except ImportError:
        logger.error(
            "SDK google-genai no instalado. "
            "Instalalo con: pip install google-genai>=1.0.0"
        )
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY no definida en el entorno")
        return None

    model_name = os.environ.get("LLM_MODEL") or "gemini-1.5-flash"

    logger.info("Proveedor: gemini | Modelo: %s", model_name)

    tool_gemini = genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(
                name="decision_cerebro",
                description="Devuelve la evaluación del cerebro sobre la señal candidata.",
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "regimen": genai_types.Schema(type=genai_types.Type.STRING),
                        "confianza_regimen": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "evaluacion_senal": genai_types.Schema(type=genai_types.Type.STRING),
                        "conviccion": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "multiplicador_riesgo": genai_types.Schema(type=genai_types.Type.NUMBER),
                        "factores_clave": genai_types.Schema(
                            type=genai_types.Type.ARRAY,
                            items=genai_types.Schema(type=genai_types.Type.STRING),
                        ),
                        "racional": genai_types.Schema(type=genai_types.Type.STRING),
                        "alertas": genai_types.Schema(
                            type=genai_types.Type.ARRAY,
                            items=genai_types.Schema(type=genai_types.Type.STRING),
                        ),
                    },
                    required=[
                        "regimen",
                        "confianza_regimen",
                        "evaluacion_senal",
                        "conviccion",
                        "multiplicador_riesgo",
                        "factores_clave",
                        "racional",
                        "alertas",
                    ],
                ),
            )
        ]
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=user_message,
            config=genai_types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=_TEMPERATURE,
                tools=[tool_gemini],
                tool_config=genai_types.ToolConfig(
                    function_calling_config=genai_types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=["decision_cerebro"],
                    )
                ),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Excepción llamando a Gemini: %s", exc)
        return None

    # Extraer el function_call de la respuesta
    try:
        for part in response.candidates[0].content.parts:
            if part.function_call is not None:
                args = dict(part.function_call.args)
                # Los arrays pueden venir como estructuras iterables — normalizar a list
                for key, val in args.items():
                    if hasattr(val, "__iter__") and not isinstance(val, str):
                        args[key] = list(val)
                logger.debug("Respuesta raw del tool (gemini): %s", args)
                return args
        logger.error("Gemini no devolvió function_call en la respuesta")
        return None
    except (IndexError, AttributeError) as exc:
        logger.error("Error extrayendo function_call de respuesta Gemini: %s", exc)
        return None


def _llamar_groq(user_message: str) -> dict | None:
    """
    Llama a Groq via SDK (API compatible con OpenAI) con tool use forzado.
    Devuelve el input del tool como dict, o None si hubo error.
    """
    try:
        from groq import Groq  # lazy: solo si LLM_PROVIDER=groq
    except ImportError:
        logger.error(
            "SDK groq no instalado. "
            "Instalalo con: pip install groq>=0.9.0"
        )
        return None

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY no definida en el entorno")
        return None

    model_name = os.environ.get("LLM_MODEL") or "llama-3.3-70b-versatile"

    logger.info("Proveedor: groq | Modelo: %s", model_name)

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            tools=[_TOOL_DECISION_OPENAI],
            tool_choice={"type": "function", "function": {"name": "decision_cerebro"}},
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Excepción llamando a Groq: %s", exc)
        return None

    # Extraer los argumentos del tool_call
    try:
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            logger.error("Groq no devolvió tool_calls en la respuesta")
            return None
        raw_args = tool_calls[0].function.arguments
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            logger.error("tool_call.arguments no es un dict tras parsear JSON: %s", type(args))
            return None
        logger.debug("Respuesta raw del tool (groq): %s", args)
        return args
    except (IndexError, AttributeError, json.JSONDecodeError) as exc:
        logger.error("Error extrayendo tool_call de respuesta Groq: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Despachador de proveedor
# ---------------------------------------------------------------------------

def _llamar_proveedor(user_message: str) -> dict | None:
    """
    Llama al proveedor LLM configurado y devuelve el input del tool como dict.
    Lee LLM_PROVIDER del entorno (anthropic | gemini | groq). Default: anthropic.
    Devuelve None si hubo error de API o el tool no fue llamado.
    """
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower().strip()

    if provider == "anthropic":
        return _llamar_anthropic(user_message)
    elif provider == "gemini":
        return _llamar_gemini(user_message)
    elif provider == "groq":
        return _llamar_groq(user_message)
    else:
        logger.error(
            "LLM_PROVIDER desconocido: '%s'. Valores válidos: anthropic, gemini, groq", provider
        )
        return None


# ---------------------------------------------------------------------------
# Implementaciones del scanner por proveedor
# ---------------------------------------------------------------------------

def _llamar_anthropic_scanner(user_message: str) -> dict | None:
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY no definida")
        return None
    model = os.environ.get("LLM_MODEL") or "claude-sonnet-4-6"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0.3,
            system=_SYSTEM_PROMPT_SCANNER,
            tools=[_TOOL_CONTEXTO_SCANNER],
            tool_choice={"type": "tool", "name": "contexto_scanner"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.error("Error llamando a Anthropic (scanner): %s", exc)
        return None
    for block in response.content:
        if block.type == "tool_use" and block.name == "contexto_scanner":
            return block.input if isinstance(block.input, dict) else None
    return None


def _llamar_groq_scanner(user_message: str) -> dict | None:
    try:
        from groq import Groq
    except ImportError:
        logger.error("SDK groq no instalado")
        return None
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY no definida")
        return None
    model_name = os.environ.get("LLM_MODEL") or "llama-3.3-70b-versatile"
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_SCANNER},
                {"role": "user", "content": user_message},
            ],
            tools=[_TOOL_CONTEXTO_SCANNER_OPENAI],
            tool_choice={"type": "function", "function": {"name": "contexto_scanner"}},
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as exc:
        logger.error("Error llamando a Groq (scanner): %s", exc)
        return None
    try:
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            return None
        args = json.loads(tool_calls[0].function.arguments)
        return args if isinstance(args, dict) else None
    except Exception as exc:
        logger.error("Error extrayendo tool_call de Groq (scanner): %s", exc)
        return None


def _llamar_gemini_scanner(user_message: str) -> dict | None:
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        logger.error("SDK google-genai no instalado")
        return None
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY no definida")
        return None
    model_name = os.environ.get("LLM_MODEL") or "gemini-2.0-flash"
    tool_gemini = genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(
                name="contexto_scanner",
                description="Análisis contextual del setup detectado por el scanner.",
                parameters=genai_types.Schema(
                    type=genai_types.Type.OBJECT,
                    properties={
                        "analisis": genai_types.Schema(type=genai_types.Type.STRING),
                        "nivel_atencion": genai_types.Schema(type=genai_types.Type.STRING),
                        "alertas": genai_types.Schema(
                            type=genai_types.Type.ARRAY,
                            items=genai_types.Schema(type=genai_types.Type.STRING),
                        ),
                    },
                    required=["analisis", "nivel_atencion", "alertas"],
                ),
            )
        ]
    )
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=user_message,
            config=genai_types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT_SCANNER,
                temperature=0.3,
                tools=[tool_gemini],
                tool_config=genai_types.ToolConfig(
                    function_calling_config=genai_types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=["contexto_scanner"],
                    )
                ),
            ),
        )
    except Exception as exc:
        logger.error("Error llamando a Gemini (scanner): %s", exc)
        return None
    try:
        for part in response.candidates[0].content.parts:
            if part.function_call is not None:
                args = dict(part.function_call.args)
                for key, val in args.items():
                    if hasattr(val, "__iter__") and not isinstance(val, str):
                        args[key] = list(val)
                return args
        return None
    except Exception as exc:
        logger.error("Error extrayendo function_call de Gemini (scanner): %s", exc)
        return None


def _llamar_proveedor_scanner(user_message: str) -> dict | None:
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower().strip()
    if provider == "anthropic":
        return _llamar_anthropic_scanner(user_message)
    elif provider == "gemini":
        return _llamar_gemini_scanner(user_message)
    elif provider == "groq":
        return _llamar_groq_scanner(user_message)
    else:
        logger.error("LLM_PROVIDER desconocido: '%s'", provider)
        return None


def contextualizar(contexto: ContextoMercado) -> dict[str, Any]:
    """
    Analiza el setup detectado por el scanner y devuelve contexto de calidad.

    A diferencia de analizar(), esta función NO toma ninguna decisión de entrada
    ni puede vetar la señal. Solo complementa el análisis mecánico con contexto
    cualitativo: calidad de la tendencia, estructura, volumen, riesgos.

    Args:
        contexto: ContextoMercado construido por el scanner.

    Returns:
        dict con:
          - analisis (str): texto de 5-6 líneas para Telegram
          - nivel_atencion (str): "alto" | "medio" | "bajo"
          - alertas (list[str]): factores de riesgo concretos (máx 3)

        Ante cualquier falla → fallback con texto genérico, nunca lanza excepción.
    """
    try:
        contexto_json = json.dumps(contexto, indent=2, ensure_ascii=False)
        user_message = f"Analizá el siguiente setup de trading:\n\n{contexto_json}"
    except (TypeError, ValueError) as exc:
        logger.error("Error serializando contexto para contextualizar: %s", exc)
        return dict(_FALLBACK_CONTEXTO)

    logger.info(
        "Contextualizando scanner — par=%s proveedor=%s",
        contexto.get("par"),
        os.environ.get("LLM_PROVIDER", "anthropic"),
    )

    raw = _llamar_proveedor_scanner(user_message)
    if raw is None:
        return dict(_FALLBACK_CONTEXTO)

    analisis = raw.get("analisis", "")
    if not analisis or not isinstance(analisis, str):
        return dict(_FALLBACK_CONTEXTO)

    nivel = raw.get("nivel_atencion", "medio")
    if nivel not in ("alto", "medio", "bajo"):
        nivel = "medio"

    alertas = raw.get("alertas", [])
    if not isinstance(alertas, list):
        alertas = []
    alertas = [str(a) for a in alertas[:3]]

    return {
        "analisis": analisis[:900],
        "nivel_atencion": nivel,
        "alertas": alertas,
    }


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def analizar(contexto: ContextoMercado) -> DecisionCerebro:
    """
    Evalúa el contexto de mercado multi-timeframe y devuelve una decisión estructurada.

    Pasos:
    1. Valida la entrada — si falla → fallback inmediato (sin llamar al LLM).
    2. Formatea el contexto como mensaje de usuario.
    3. Llama al proveedor LLM configurado via _llamar_proveedor().
    4. Ante error de API o tool no llamado → fallback con "API_ERROR".
    5. Parsea y valida la respuesta del tool.
    6. Devuelve la DecisionCerebro validada.
    """
    # 1. Validar entrada
    valido, razon_invalido = _validar_contexto(contexto)
    if not valido:
        logger.warning("Contexto de entrada inválido — %s", razon_invalido)
        return _fallback_con_razon(f"ENTRADA_INVALIDA: {razon_invalido}")

    riesgo_disponible_pct: float = float(contexto["portfolio"]["riesgo_disponible_pct"])

    # 2. Formatear contexto como mensaje de usuario
    try:
        contexto_json = json.dumps(contexto, indent=2, ensure_ascii=False)
        user_message = f"Evalúa la siguiente señal de trading:\n\n{contexto_json}"
    except (TypeError, ValueError) as exc:
        logger.error("Error serializando contexto: %s", exc)
        return _fallback_con_razon("ENTRADA_INVALIDA: error al serializar el contexto")

    # 3. Log de contexto antes de llamar al proveedor
    logger.info(
        "Llamando al LLM — par=%s timestamp=%s senal=%s proveedor=%s",
        contexto.get("par"),
        contexto.get("timestamp"),
        contexto.get("senal_base"),
        os.environ.get("LLM_PROVIDER", "anthropic"),
    )

    # 4. Llamar al proveedor
    raw_input = _llamar_proveedor(user_message)
    if raw_input is None:
        return _fallback_con_razon("API_ERROR")

    # 5. Validar y corregir
    decision = _validar_y_corregir_salida(raw_input, riesgo_disponible_pct)
    if decision is None:
        return _fallback_con_razon("SCHEMA_INVALIDO")

    logger.info(
        "Decisión — regimen=%s evaluacion=%s multiplicador=%.2f conviccion=%.2f",
        decision["regimen"],
        decision["evaluacion_senal"],
        decision["multiplicador_riesgo"],
        decision["conviccion"],
    )
    return decision
