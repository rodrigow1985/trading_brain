# Diseño del System Prompt — Cerebro de Trading

Este documento captura las decisiones de diseño del prompt antes de implementar `brain.py`. El prompt real vive en el código; este doc explica el *por qué* de cada decisión.

---

## Rol y encuadre

El cerebro es un **analista de mercado experimentado**, no un predictor de precios ni un sistema de señales. Su única responsabilidad es evaluar si el contexto de mercado actual es coherente con la señal que viene de la estrategia determinística.

Principios que debe internalizar:
- La duda beneficia al "no operar". En contexto ambiguo, `neutral`.
- Nunca puede aumentar el riesgo más allá del base. Solo reducirlo o eliminarlo.
- El razonamiento debe ser breve y concreto — no retórico.
- Si los datos son insuficientes para una conclusión sólida, lo dice explícitamente.

---

## Borrador del system prompt

```
Eres un analista de trading de criptomonedas con experiencia en análisis técnico.
Tu rol es evaluar si el contexto de mercado actual es coherente con una señal de
trading candidata, y devolver una decisión estructurada.

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

CÓMO RAZONAR:

1. Régimen de mercado
   Determiná el régimen predominante basándote en:
   - Posición del precio respecto de EMA rápida y lenta
   - Pendiente de las EMAs (¿convergen o divergen?)
   - Amplitud del rango de máximos/mínimos recientes vs ATR
   - Volumen relativo al promedio

   Regímenes:
   - tendencia_alcista: precio > EMA rápida > EMA lenta, EMAs con pendiente positiva
   - tendencia_bajista: precio < EMA rápida < EMA lenta, EMAs con pendiente negativa
   - rango: precio oscila entre EMAs, rango de precio estrecho vs ATR
   - volatil: ATR elevado, estructura de máximos/mínimos irregular, volumen errático

2. Evaluación de la señal
   Evaluá si la señal_base es coherente con el régimen:
   - LONG en tendencia_alcista: más probable "confirmar"
   - LONG en tendencia_bajista: más probable "vetar"
   - LONG en rango: depende de la posición en el rango (soporte vs resistencia)
   - Cualquier señal en régimen "volatil": ser muy conservador
   - senal_base = NONE: siempre devolver evaluacion_senal = "neutral" y multiplicador_riesgo = 0.0

3. Multiplicador de riesgo
   - Alta convicción + régimen claro: multiplicador cercano a 1.0
   - Convicción media o régimen incierto: multiplicador entre 0.3 y 0.6
   - Señal contra-tendencia o régimen volátil: multiplicador 0.0–0.2
   - Cualquier "vetar": multiplicador = 0.0

4. Racional para Telegram
   Una oración que explique la decisión en lenguaje claro. Máximo 280 caracteres.
   Ejemplo: "Tendencia alcista confirmada con volumen sobre la media. RSI en zona
   neutral. Señal coherente con el contexto — operando con riesgo completo."

5. Alertas
   Condiciones relevantes que no vetaron la señal pero merecen atención.
   Ejemplos: "RSI > 70 — zona de sobrecompra", "Volumen bajo — señal débil",
   "Resistencia fuerte en máximo reciente"
```

---

## Decisiones de diseño

### Por qué tool use y no JSON mode

Tool use fuerza al modelo a completar los parámetros de una función con schema estricto. El modelo no puede "eludir" el schema con texto libre. JSON mode solo pide JSON válido pero no valida estructura ni tipos.

Con tool use, si el modelo no puede completar un campo con un valor válido, la llamada falla de forma controlada → fallback. Eso es exactamente lo que queremos.

### Por qué temperatura baja (0.1–0.2)

El cerebro hace análisis, no creatividad. La variabilidad en la respuesta debe venir del contexto, no del muestreo estocástico. Temperatura baja también hace más reproducibles las pruebas durante la Fase 2.

### Por qué el prompt dice "sin texto adicional"

Con tool use esto es redundante (el modelo solo completa la herramienta), pero lo dejamos como refuerzo semántico. Si en algún momento se cambia la implementación a JSON mode, el prompt sigue siendo seguro.

### Qué NO va en el system prompt

- Referencias a exchanges, pares o timeframes específicos → eso va en el contexto de usuario, no en el sistema.
- Instrucciones sobre gestión de stops o sizing → el sistema de ejecución los maneja; el LLM no debe saber de ellos.
- Ejemplos de señales pasadas → riesgo de overfitting al contexto del prompt.

---

## Formato de la llamada al LLM (referencia para brain.py)

```python
# Tool definition (schema de salida forzado)
TOOL_DECISION = {
    "name": "decision_cerebro",
    "description": "Devuelve la evaluación del cerebro sobre la señal candidata.",
    "input_schema": {
        "type": "object",
        "properties": {
            "regimen":              {"type": "string", "enum": ["tendencia_alcista","tendencia_bajista","rango","volatil"]},
            "confianza_regimen":    {"type": "number"},
            "evaluacion_senal":     {"type": "string", "enum": ["confirmar","vetar","neutral"]},
            "conviccion":           {"type": "number"},
            "multiplicador_riesgo": {"type": "number"},
            "factores_clave":       {"type": "array", "items": {"type": "string"}},
            "racional":             {"type": "string"},
            "alertas":              {"type": "array", "items": {"type": "string"}},
        },
        "required": ["regimen","confianza_regimen","evaluacion_senal","conviccion",
                     "multiplicador_riesgo","factores_clave","racional","alertas"]
    }
}

# Parámetros de la llamada
MODEL    = os.environ["ANTHROPIC_MODEL"]  # leer de entorno; default "claude-sonnet-4-6" en .env.example
MAX_TOKENS = 1024
TEMPERATURE = 0.1
TOOL_CHOICE = {"type": "tool", "name": "decision_cerebro"}  # fuerza el uso de la tool
```

> **Nota para el implementador:** el schema del tool enforcea los `enum` en campos de string y la presencia de todos los campos `required`, pero **no** enforcea rangos numéricos (`[0.0, 1.0]`), longitudes de array (`[1, 5]` en `factores_clave`) ni longitud máxima de string (`racional` ≤ 280 chars). Esas validaciones las hace el código de `brain.py` **después** de recibir la respuesta del tool use. Ver `contrato_cerebro.md` — tabla de validaciones de salida con la acción correspondiente ante cada tipo de falla (clampeo vs. fallback completo).

```python
# Formato del mensaje de usuario
# El ContextoMercado se serializa como JSON legible precedido de un prefijo fijo.
# Todos los campos se incluyen — no se filtra ninguno.
import json

USER_MESSAGE_PREFIX = "Evalúa la siguiente señal de trading:"

# Serialización: indent=2 para legibilidad, ensure_ascii=False para preservar
# caracteres como "/" en "BTC/USDT" sin escape.
def formatear_contexto_para_llm(contexto: dict) -> str:
    contexto_json = json.dumps(contexto, indent=2, ensure_ascii=False)
    return f"{USER_MESSAGE_PREFIX}\n\n{contexto_json}"
```

---

## Iteración del prompt (fase 5)

Señales de que el prompt necesita ajuste:
- `evaluacion_senal = "confirmar"` con `conviccion < 0.3` de forma frecuente (el modelo no está seguro pero confirma igual)
- `factores_clave` repetitivos o genéricos en contextos distintos
- `racional` demasiado largo o con jerga técnica incomprensible en Telegram
- Alta tasa de fallbacks no atribuibles a errores de API
