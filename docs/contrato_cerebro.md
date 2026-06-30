# Contrato del Cerebro

Define el protocolo exacto entre la capa determinística y `brain.py`. Cualquier cambio en estos schemas requiere actualizar ambos lados.

---

## Entrada — ContextoMercado

Armado íntegramente por `context_builder.py`. El cerebro no busca ni deriva datos propios.

El contexto sigue un enfoque **multi-timeframe top-down**: los datos de 4H y 1D dan el sesgo y la estructura; los de 1H aportan el timing de la señal.

```python
{
    # Identificación
    "par":          str,   # "BTC/USDT"
    "timestamp":    str,   # ISO 8601, cierre de la vela 1H evaluada
    "mercado_tipo": str,   # "spot" | "futuro"  (nota: CCXT_MARKET_TYPE usa "spot"/"future" — context_builder.py mapea "future" → "futuro")

    # Señal de la estrategia base (calculada sobre 1H)
    "senal_base": str,     # "LONG" | "SHORT" | "NONE"

    # Estado del portfolio
    "portfolio": {
        "posicion_actual":       str,    # "LONG" | "SHORT" | "NONE"
        "riesgo_disponible_pct": float,  # % del capital disponible, rango [0.0, 1.0]
    },

    # Contexto por timeframe — mismo schema para los tres
    "timeframes": {

        "4h": {
            "indicadores": {
                "rsi":              float,  # RSI(14), rango [0, 100]
                "ema_rapida":       float,  # EMA(21), precio
                "ema_lenta":        float,  # EMA(50), precio
                "atr":              float,  # ATR(14), en unidades del par
                "volumen":          float,  # volumen de la vela de cierre
                "volumen_promedio": float,  # SMA(20) del volumen
            },
            "estructura": {
                "precio_actual":     float,        # close de la vela evaluada
                "maximos_recientes": list[float],  # últimos 5 máximos (viejo → nuevo)
                "minimos_recientes": list[float],  # últimos 5 mínimos (viejo → nuevo)
                "tendencia":         str,          # "alcista" | "bajista" | "lateral"
            },
        },

        "1d": {
            "indicadores": {
                "rsi":              float,
                "ema_rapida":       float,  # EMA(21)
                "ema_lenta":        float,  # EMA(50)
                "ema_largo":        float,  # EMA(200) — solo disponible en 1D
                "atr":              float,
                "volumen":          float,
                "volumen_promedio": float,
            },
            "estructura": {
                "precio_actual":     float,
                "maximos_recientes": list[float],
                "minimos_recientes": list[float],
                "tendencia":         str,
            },
        },

        "1h": {
            "indicadores": {
                "rsi":              float,
                "ema_rapida":       float,  # EMA(21)
                "ema_lenta":        float,  # EMA(50)
                "atr":              float,
                "volumen":          float,
                "volumen_promedio": float,
            },
            "estructura": {
                "precio_actual":     float,
                "maximos_recientes": list[float],
                "minimos_recientes": list[float],
                "tendencia":         str,
            },
        },
    },

    # Campos adicionales en fase futuro: funding_rate, open_interest, liquidaciones
}
```

### Validaciones de entrada

Aplican a cada uno de los tres timeframes:

| Campo | Tipo | Restricción |
|---|---|---|
| `par` | str | no vacío, formato `"BASE/QUOTE"` |
| `timestamp` | str | ISO 8601 parseable |
| `mercado_tipo` | str | uno de `["spot","futuro"]` |
| `senal_base` | str | uno de `["LONG","SHORT","NONE"]` |
| `portfolio.riesgo_disponible_pct` | float | `[0.0, 1.0]` |
| `timeframes` | dict | debe contener exactamente las claves `"4h"`, `"1d"`, `"1h"` |
| `*.indicadores.rsi` | float | `[0.0, 100.0]` |
| `*.indicadores.atr` | float | `> 0.0` |
| `*.indicadores.volumen` | float | `>= 0.0` |
| `*.indicadores.volumen_promedio` | float | `> 0.0` |
| `*.estructura.maximos_recientes` | list | longitud == 5 |
| `*.estructura.minimos_recientes` | list | longitud == 5 |
| `*.estructura.tendencia` | str | uno de `["alcista","bajista","lateral"]` |

Si algún campo obligatorio falta o está fuera de rango → no llamar al LLM → devolver respuesta default.

---

## Salida — DecisionCerebro

Sin cambios respecto al enfoque single-timeframe. La salida es siempre una decisión unificada.

```json
{
  "regimen":              "tendencia_alcista | tendencia_bajista | rango | volatil",
  "confianza_regimen":    0.0,
  "evaluacion_senal":     "confirmar | vetar | neutral",
  "conviccion":           0.0,
  "multiplicador_riesgo": 0.0,
  "factores_clave":       ["..."],
  "racional":             "texto para Telegram, máx 280 caracteres",
  "alertas":              ["..."]
}
```

### Validaciones de salida

| Campo | Tipo | Restricción | Acción ante falla |
|---|---|---|---|
| `regimen` | str | exactamente uno de `["tendencia_alcista","tendencia_bajista","rango","volatil"]` | Fallback completo — `SCHEMA_INVALIDO` |
| `confianza_regimen` | float | `[0.0, 1.0]` | Clampear al rango; loguear anomalía |
| `evaluacion_senal` | str | exactamente uno de `["confirmar","vetar","neutral"]` | Fallback completo — `SCHEMA_INVALIDO` |
| `conviccion` | float | `[0.0, 1.0]` | Clampear al rango; loguear anomalía |
| `multiplicador_riesgo` | float | `[0.0, 1.0]` — nunca puede superar 1.0 | Clampear al rango; loguear anomalía (ver también "Semántica") |
| `factores_clave` | list[str] | longitud `[1, 5]` | Fallback completo — `SCHEMA_INVALIDO` |
| `racional` | str | no vacío, máx 280 caracteres | Si vacío: fallback — `SCHEMA_INVALIDO`. Si > 280 chars: truncar a 277 + `"..."`; loguear anomalía |
| `alertas` | list[str] | puede ser vacío `[]` | Sin acción — nunca falla |

**Regla general:** si el campo tiene un valor inválido pero clampeable (numérico fuera de rango, string demasiado largo), se corrige en código y se loguea como anomalía sin activar el fallback. Si el campo tiene un tipo incorrecto o un enum no reconocido, no es recuperable → fallback completo con `fallback_reason = "SCHEMA_INVALIDO"`.

---

## Semántica de los campos de salida

### `regimen`
Refleja el régimen del **4H** (sesgo principal). Si 4H y 1H divergen, el cerebro debe mencionarlo en `factores_clave` y ser conservador con `multiplicador_riesgo`.

### `multiplicador_riesgo`
Escala el tamaño de posición calculado por la estrategia base.

| Valor | Significado |
|---|---|
| `0.0` | No operar (equivale a vetar incluso si `evaluacion_senal = "confirmar"`) |
| `0.5` | Operar con la mitad del riesgo base |
| `1.0` | Operar con el riesgo base completo |

El código nunca debe usar un `multiplicador_riesgo > 1.0`. Si el LLM devuelve uno, se clampea a `1.0` y se loguea como anomalía.

### `conviccion`
Nivel de confianza del cerebro en su `evaluacion_senal`. No escala el riesgo directamente (eso lo hace `multiplicador_riesgo`). Sirve para métricas y calibración posterior.

### `alertas`
Condiciones que el cerebro considera relevantes aunque no veten la señal. El código no actúa sobre `alertas`; solo las loguea y las incluye en la notificación de Telegram.

---

## Respuesta default (safe fallback)

Se devuelve ante cualquiera de estas condiciones:
- Contexto de entrada inválido o incompleto
- Error de API (timeout, rate limit, error HTTP)
- JSON malformado en la respuesta del LLM
- JSON válido pero con campos fuera de rango
- Timeout de validación

```json
{
  "regimen":              "rango",
  "confianza_regimen":    0.0,
  "evaluacion_senal":     "neutral",
  "conviccion":           0.0,
  "multiplicador_riesgo": 0.0,
  "factores_clave":       ["respuesta default por falla en el cerebro"],
  "racional":             "Cerebro no disponible — operando en modo seguro.",
  "alertas":              ["FALLBACK_ACTIVADO"]
}
```

La presencia de `"FALLBACK_ACTIVADO"` en `alertas` permite identificar estas entradas en el log de SQLite.

---

## Casos borde documentados

| Situación | Comportamiento esperado | Quién lo fuerza |
|---|---|---|
| `senal_base = "NONE"` | El cerebro igualmente clasifica el régimen. `evaluacion_senal` siempre `"neutral"`, `multiplicador_riesgo = 0.0`. | El system prompt lo instruye. Si el LLM devuelve un valor distinto de `"neutral"` o un `multiplicador_riesgo > 0.0`, el código los corrige post-validación (clampeo) y loguea la anomalía — no activa fallback completo. |
| `riesgo_disponible_pct = 0.0` | El cerebro puede analizar, pero `multiplicador_riesgo` debe ser `0.0`. | **Código en `brain.py`**: el LLM se llama igualmente (para registrar el régimen). Después de recibir la respuesta validada, `brain.py` clampea `multiplicador_riesgo` a `0.0` si `riesgo_disponible_pct == 0.0`, independientemente de lo que haya devuelto el modelo. Loguear la corrección. |
| `posicion_actual != "NONE"` y `senal_base` en la misma dirección | El cerebro puede confirmar pero debe mencionar la posición abierta en `factores_clave`. | Solo el sistema prompt lo instruye. El código no lo fuerza. |
| Régimen `"volatil"` | El cerebro debería ser más conservador con `multiplicador_riesgo` (< 0.5 salvo convicción muy alta). | Solo el system prompt lo instruye. El código no lo fuerza. |
| 4H alcista pero 1H bajista (divergencia MTF) | El cerebro debe vetar o reducir `multiplicador_riesgo` y mencionarlo en `factores_clave`. | Solo el system prompt lo instruye. El código no lo fuerza. |
| 4H y 1D alineados pero 1H en contra | Señal de entrada prematura — `multiplicador_riesgo` reducido, esperar confirmación. | Solo el system prompt lo instruye. El código no lo fuerza. |
| API key inválida o expirada | Falla en la llamada → fallback. Loguear el error HTTP. | Código: captura la excepción de la SDK de Anthropic → fallback con `fallback_reason = "API_ERROR"`. |
