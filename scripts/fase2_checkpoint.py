"""
Checkpoint Fase 2 — El Cerebro.

Prueba brain.analizar() con 4 contextos hardcodeados (sin ccxt) y
un contexto intencionalmente inválido para verificar el fallback.
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

# Silenciar httpx para no ensuciar la salida del checkpoint
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)

# Asegurar que src/ esté en el path cuando se corre desde la raíz del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.brain import analizar  # noqa: E402  (import post load_dotenv)
from src.types import ContextoMercado, DecisionCerebro  # noqa: E402

# ---------------------------------------------------------------------------
# Contextos de prueba hardcodeados
# ---------------------------------------------------------------------------

# Contexto 1: BTC/USDT — 4H alcista + 1D bajista + 1H alcista (divergencia MTF → LONG)
CONTEXTO_1: ContextoMercado = {
    "par": "BTC/USDT",
    "timestamp": "2026-06-16T04:00:00+00:00",
    "mercado_tipo": "spot",
    "senal_base": "LONG",
    "portfolio": {
        "posicion_actual": "NONE",
        "riesgo_disponible_pct": 1.0,
    },
    "timeframes": {
        "4h": {
            "indicadores": {
                "rsi": 58.5,
                "ema_rapida": 66500.0,
                "ema_lenta": 65800.0,
                "atr": 720.0,
                "volumen": 2800.0,
                "volumen_promedio": 2200.0,
            },
            "estructura": {
                "precio_actual": 67000.0,
                "maximos_recientes": [65500.0, 66000.0, 66500.0, 67000.0, 67200.0],
                "minimos_recientes": [63000.0, 63500.0, 64000.0, 64500.0, 65000.0],
                "tendencia": "alcista",
            },
        },
        "1d": {
            "indicadores": {
                "rsi": 41.0,
                "ema_rapida": 68000.0,
                "ema_lenta": 71000.0,
                "ema_largo": 77000.0,
                "atr": 2100.0,
                "volumen": 18000.0,
                "volumen_promedio": 21000.0,
            },
            "estructura": {
                "precio_actual": 67000.0,
                "maximos_recientes": [78000.0, 76000.0, 75000.0, 73000.0, 71000.0],
                "minimos_recientes": [60000.0, 61000.0, 62000.0, 63000.0, 64000.0],
                "tendencia": "bajista",
            },
        },
        "1h": {
            "indicadores": {
                "rsi": 54.0,
                "ema_rapida": 66800.0,
                "ema_lenta": 66200.0,
                "atr": 320.0,
                "volumen": 850.0,
                "volumen_promedio": 750.0,
            },
            "estructura": {
                "precio_actual": 67000.0,
                "maximos_recientes": [66000.0, 66200.0, 66500.0, 66800.0, 67000.0],
                "minimos_recientes": [65000.0, 65200.0, 65500.0, 65700.0, 65900.0],
                "tendencia": "alcista",
            },
        },
    },
}

# Contexto 2: BTC/USDT — todos los timeframes alcistas (alineación perfecta → LONG)
CONTEXTO_2: ContextoMercado = {
    "par": "BTC/USDT",
    "timestamp": "2026-06-16T08:00:00+00:00",
    "mercado_tipo": "spot",
    "senal_base": "LONG",
    "portfolio": {
        "posicion_actual": "NONE",
        "riesgo_disponible_pct": 1.0,
    },
    "timeframes": {
        "4h": {
            "indicadores": {
                "rsi": 63.0,
                "ema_rapida": 68000.0,
                "ema_lenta": 66000.0,
                "atr": 700.0,
                "volumen": 3500.0,
                "volumen_promedio": 2200.0,
            },
            "estructura": {
                "precio_actual": 70000.0,
                "maximos_recientes": [65000.0, 66500.0, 68000.0, 69500.0, 70000.0],
                "minimos_recientes": [62000.0, 63000.0, 64000.0, 65500.0, 67000.0],
                "tendencia": "alcista",
            },
        },
        "1d": {
            "indicadores": {
                "rsi": 62.0,
                "ema_rapida": 67000.0,
                "ema_lenta": 65000.0,
                "ema_largo": 60000.0,
                "atr": 2000.0,
                "volumen": 25000.0,
                "volumen_promedio": 21000.0,
            },
            "estructura": {
                "precio_actual": 70000.0,
                "maximos_recientes": [62000.0, 64000.0, 66000.0, 68000.0, 70000.0],
                "minimos_recientes": [58000.0, 60000.0, 62000.0, 64000.0, 66000.0],
                "tendencia": "alcista",
            },
        },
        "1h": {
            "indicadores": {
                "rsi": 60.0,
                "ema_rapida": 69600.0,
                "ema_lenta": 69000.0,
                "atr": 300.0,
                "volumen": 1100.0,
                "volumen_promedio": 800.0,
            },
            "estructura": {
                "precio_actual": 70000.0,
                "maximos_recientes": [68000.0, 68500.0, 69000.0, 69500.0, 70000.0],
                "minimos_recientes": [67000.0, 67500.0, 68000.0, 68500.0, 69000.0],
                "tendencia": "alcista",
            },
        },
    },
}

# Contexto 3: BTC/USDT — todos los timeframes bajistas → SHORT
CONTEXTO_3: ContextoMercado = {
    "par": "BTC/USDT",
    "timestamp": "2026-06-16T12:00:00+00:00",
    "mercado_tipo": "spot",
    "senal_base": "SHORT",
    "portfolio": {
        "posicion_actual": "NONE",
        "riesgo_disponible_pct": 0.8,
    },
    "timeframes": {
        "4h": {
            "indicadores": {
                "rsi": 38.0,
                "ema_rapida": 61000.0,
                "ema_lenta": 63000.0,
                "atr": 800.0,
                "volumen": 3200.0,
                "volumen_promedio": 2200.0,
            },
            "estructura": {
                "precio_actual": 59500.0,
                "maximos_recientes": [68000.0, 66000.0, 64000.0, 62000.0, 60000.0],
                "minimos_recientes": [65000.0, 63000.0, 61000.0, 59000.0, 57000.0],
                "tendencia": "bajista",
            },
        },
        "1d": {
            "indicadores": {
                "rsi": 35.0,
                "ema_rapida": 63000.0,
                "ema_lenta": 67000.0,
                "ema_largo": 72000.0,
                "atr": 2300.0,
                "volumen": 28000.0,
                "volumen_promedio": 21000.0,
            },
            "estructura": {
                "precio_actual": 59500.0,
                "maximos_recientes": [75000.0, 73000.0, 70000.0, 66000.0, 62000.0],
                "minimos_recientes": [68000.0, 65000.0, 62000.0, 59000.0, 56000.0],
                "tendencia": "bajista",
            },
        },
        "1h": {
            "indicadores": {
                "rsi": 32.0,
                "ema_rapida": 60200.0,
                "ema_lenta": 60800.0,
                "atr": 350.0,
                "volumen": 1400.0,
                "volumen_promedio": 800.0,
            },
            "estructura": {
                "precio_actual": 59500.0,
                "maximos_recientes": [62000.0, 61500.0, 61000.0, 60500.0, 60000.0],
                "minimos_recientes": [60500.0, 60000.0, 59500.0, 59000.0, 58500.0],
                "tendencia": "bajista",
            },
        },
    },
}

# Contexto 4: senal_base = "NONE" → debe devolver neutral con multiplicador 0.0
CONTEXTO_4: ContextoMercado = {
    "par": "ETH/USDT",
    "timestamp": "2026-06-16T16:00:00+00:00",
    "mercado_tipo": "spot",
    "senal_base": "NONE",
    "portfolio": {
        "posicion_actual": "NONE",
        "riesgo_disponible_pct": 1.0,
    },
    "timeframes": {
        "4h": {
            "indicadores": {
                "rsi": 50.5,
                "ema_rapida": 3500.0,
                "ema_lenta": 3480.0,
                "atr": 55.0,
                "volumen": 15000.0,
                "volumen_promedio": 14000.0,
            },
            "estructura": {
                "precio_actual": 3510.0,
                "maximos_recientes": [3480.0, 3490.0, 3500.0, 3510.0, 3520.0],
                "minimos_recientes": [3440.0, 3450.0, 3460.0, 3470.0, 3480.0],
                "tendencia": "lateral",
            },
        },
        "1d": {
            "indicadores": {
                "rsi": 49.0,
                "ema_rapida": 3510.0,
                "ema_lenta": 3490.0,
                "ema_largo": 3200.0,
                "atr": 130.0,
                "volumen": 180000.0,
                "volumen_promedio": 170000.0,
            },
            "estructura": {
                "precio_actual": 3510.0,
                "maximos_recientes": [3550.0, 3540.0, 3530.0, 3520.0, 3510.0],
                "minimos_recientes": [3400.0, 3420.0, 3440.0, 3460.0, 3480.0],
                "tendencia": "lateral",
            },
        },
        "1h": {
            "indicadores": {
                "rsi": 51.0,
                "ema_rapida": 3505.0,
                "ema_lenta": 3495.0,
                "atr": 25.0,
                "volumen": 5000.0,
                "volumen_promedio": 4800.0,
            },
            "estructura": {
                "precio_actual": 3510.0,
                "maximos_recientes": [3500.0, 3502.0, 3504.0, 3507.0, 3510.0],
                "minimos_recientes": [3490.0, 3492.0, 3494.0, 3497.0, 3500.0],
                "tendencia": "lateral",
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Helpers de impresión y verificación
# ---------------------------------------------------------------------------

CAMPOS_REQUERIDOS: list[str] = [
    "regimen",
    "confianza_regimen",
    "evaluacion_senal",
    "conviccion",
    "multiplicador_riesgo",
    "factores_clave",
    "racional",
    "alertas",
]

REGIMENES_VALIDOS = {"tendencia_alcista", "tendencia_bajista", "rango", "volatil"}
EVALUACIONES_VALIDAS = {"confirmar", "vetar", "neutral"}


def _verificar_decision(decision: DecisionCerebro, descripcion: str) -> bool:
    """Verifica que la decisión tenga los campos y tipos correctos."""
    errores: list[str] = []

    for campo in CAMPOS_REQUERIDOS:
        if campo not in decision:
            errores.append(f"  campo faltante: '{campo}'")

    if decision.get("regimen") not in REGIMENES_VALIDOS:
        errores.append(f"  regimen inválido: '{decision.get('regimen')}'")

    if decision.get("evaluacion_senal") not in EVALUACIONES_VALIDAS:
        errores.append(f"  evaluacion_senal inválida: '{decision.get('evaluacion_senal')}'")

    for campo_float in ("confianza_regimen", "conviccion", "multiplicador_riesgo"):
        val = decision.get(campo_float)
        if not isinstance(val, (int, float)) or not (0.0 <= float(val) <= 1.0):
            errores.append(f"  {campo_float} fuera de rango o tipo inválido: {val!r}")

    factores = decision.get("factores_clave", [])
    if not isinstance(factores, list) or len(factores) < 1:
        errores.append(f"  factores_clave vacío o no es lista: {factores!r}")

    racional = decision.get("racional", "")
    if not isinstance(racional, str) or not racional.strip():
        errores.append(f"  racional vacío o no es string: {racional!r}")
    elif len(racional) > 280:
        errores.append(f"  racional supera 280 chars: {len(racional)}")

    if errores:
        print(f"  FALLO — {descripcion}:")
        for e in errores:
            print(e)
        return False
    else:
        print(f"  OK — {descripcion}: todos los campos presentes, tipos y rangos correctos.")
        return True


def _imprimir_decision(decision: DecisionCerebro) -> None:
    print(json.dumps(dict(decision), indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Ejecución principal
# ---------------------------------------------------------------------------

def main() -> None:
    fallos: list[str] = []

    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    model = os.environ.get("LLM_MODEL", "")
    print(f"Proveedor: {provider} | Modelo: {model or '(default)'}")
    print()

    # --- Contexto 1: divergencia MTF —
    print("=" * 70)
    print("CONTEXTO 1 — BTC/USDT | 4H alcista + 1D bajista + 1H alcista | LONG")
    print("=" * 70)
    dec1 = analizar(CONTEXTO_1)
    _imprimir_decision(dec1)
    if not _verificar_decision(dec1, "Contexto 1"):
        fallos.append("Contexto 1")
    print()

    # --- Contexto 2: alineación perfecta alcista ---
    print("=" * 70)
    print("CONTEXTO 2 — BTC/USDT | todos los TF alcistas | LONG (alineación perfecta)")
    print("=" * 70)
    dec2 = analizar(CONTEXTO_2)
    _imprimir_decision(dec2)
    if not _verificar_decision(dec2, "Contexto 2"):
        fallos.append("Contexto 2")
    print()

    # --- Contexto 3: todos los TF bajistas ---
    print("=" * 70)
    print("CONTEXTO 3 — BTC/USDT | todos los TF bajistas | SHORT")
    print("=" * 70)
    dec3 = analizar(CONTEXTO_3)
    _imprimir_decision(dec3)
    if not _verificar_decision(dec3, "Contexto 3"):
        fallos.append("Contexto 3")
    print()

    # --- Contexto 4: senal_base = NONE ---
    print("=" * 70)
    print("CONTEXTO 4 — ETH/USDT | senal_base=NONE | debe devolver neutral")
    print("=" * 70)
    dec4 = analizar(CONTEXTO_4)
    _imprimir_decision(dec4)
    if not _verificar_decision(dec4, "Contexto 4"):
        fallos.append("Contexto 4")
    # Verificar que con senal_base=NONE devuelve neutral y multiplicador 0.0
    if dec4.get("evaluacion_senal") != "neutral":
        print(f"  ADVERTENCIA: senal_base=NONE pero evaluacion_senal='{dec4.get('evaluacion_senal')}'")
    if float(dec4.get("multiplicador_riesgo", -1.0)) != 0.0:
        print(f"  ADVERTENCIA: senal_base=NONE pero multiplicador_riesgo={dec4.get('multiplicador_riesgo')}")
    print()

    # --- Contexto inválido: verificar fallback ---
    print("=" * 70)
    print("CONTEXTO INVÁLIDO — campo 'senal_base' faltante — debe activar fallback")
    print("=" * 70)
    contexto_invalido = {
        "par": "BTC/USDT",
        "timestamp": "2026-06-16T20:00:00+00:00",
        "mercado_tipo": "spot",
        # senal_base ausente — campo requerido
        "portfolio": {
            "posicion_actual": "NONE",
            "riesgo_disponible_pct": 1.0,
        },
        "timeframes": {
            "4h": {
                "indicadores": {
                    "rsi": 55.0,
                    "ema_rapida": 66000.0,
                    "ema_lenta": 65000.0,
                    "atr": 700.0,
                    "volumen": 2000.0,
                    "volumen_promedio": 2000.0,
                },
                "estructura": {
                    "precio_actual": 67000.0,
                    "maximos_recientes": [65000.0, 65500.0, 66000.0, 66500.0, 67000.0],
                    "minimos_recientes": [63000.0, 63500.0, 64000.0, 64500.0, 65000.0],
                    "tendencia": "alcista",
                },
            },
            "1d": {
                "indicadores": {
                    "rsi": 45.0,
                    "ema_rapida": 67000.0,
                    "ema_lenta": 70000.0,
                    "ema_largo": 75000.0,
                    "atr": 2000.0,
                    "volumen": 20000.0,
                    "volumen_promedio": 21000.0,
                },
                "estructura": {
                    "precio_actual": 67000.0,
                    "maximos_recientes": [75000.0, 73000.0, 71000.0, 69000.0, 67000.0],
                    "minimos_recientes": [62000.0, 63000.0, 64000.0, 65000.0, 66000.0],
                    "tendencia": "bajista",
                },
            },
            "1h": {
                "indicadores": {
                    "rsi": 52.0,
                    "ema_rapida": 66800.0,
                    "ema_lenta": 66300.0,
                    "atr": 310.0,
                    "volumen": 900.0,
                    "volumen_promedio": 750.0,
                },
                "estructura": {
                    "precio_actual": 67000.0,
                    "maximos_recientes": [66000.0, 66200.0, 66500.0, 66800.0, 67000.0],
                    "minimos_recientes": [65200.0, 65400.0, 65600.0, 65800.0, 66000.0],
                    "tendencia": "alcista",
                },
            },
        },
    }
    dec_invalido = analizar(contexto_invalido)  # type: ignore[arg-type]
    _imprimir_decision(dec_invalido)

    es_fallback = "FALLBACK_ACTIVADO" in dec_invalido.get("alertas", [])
    if es_fallback:
        print("  OK — FALLBACK_ACTIVADO presente en alertas (comportamiento esperado).")
    else:
        print("  FALLO — FALLBACK_ACTIVADO NO presente en alertas del contexto inválido.")
        fallos.append("Contexto inválido (fallback)")
    print()

    # --- Resumen final ---
    print("=" * 70)
    if not fallos:
        print("CHECKPOINT FASE 2: PASO (OK)")
    else:
        print(f"CHECKPOINT FASE 2: FALLO — errores en: {', '.join(fallos)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
