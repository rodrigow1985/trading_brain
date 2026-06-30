# Indicadores Técnicos — Parámetros y Definiciones

Define los parámetros exactos de cada indicador usado en `context_builder.py`. Cambiar estos valores requiere re-validar el cerebro desde cero (los umbrales del system prompt asumen estos períodos).

---

## Enfoque multi-timeframe (MTF)

El análisis sigue un orden top-down:

| Orden | Timeframe | Rol |
|---|---|---|
| 1° | 4H | Sesgo direccional — define la tendencia principal |
| 2° | 1D | Confirmación de estructura — soportes, resistencias, contexto macro |
| 3° | 1H | Timing de entrada — señal operativa |

El cerebro recibe contexto de los tres timeframes. La señal base viene del 1H, pero el régimen declarado debe ser coherente con el 4H. Si el 4H es bajista y el 1H da LONG, el cerebro debería ser muy conservador o vetar.

> Nota de implementación: el `context_builder.py` arma tres sub-contextos (uno por timeframe) y los incluye en el dict de entrada al cerebro. Ver `contrato_cerebro.md`.

---

## Parámetros de descarga

### Parámetros generales

| Parámetro | Valor | Razón |
|---|---|---|
| Velas a descargar (1H y 4H) | 200 | Warmup: EMA(50) necesita ~150, más margen para estructura |
| Velas válidas para operar (1H y 4H) | últimas 150 (descartar primeras 50) | Las primeras velas tienen EMAs con warmup incompleto |
| Exchange | Binance (configurable vía `CCXT_EXCHANGE`) | |
| Timeframes | `4h`, `1d`, `1h` | Top-down: sesgo → estructura → entrada |

### Excepción: timeframe 1D

El timeframe `1d` tiene parámetros distintos porque calcula EMA(200), que requiere al menos 200 velas válidas post-warmup. Con solo 150 velas válidas, `close.ewm(span=200, adjust=False).mean()` devuelve valores poco confiables (warmup incompleto).

| Parámetro | Valor | Razón |
|---|---|---|
| Velas a descargar (`VELAS_DESCARGAR_1D`) | **250** | 200 válidas + 50 de warmup |
| Velas válidas para operar | últimas 200 (descartar primeras 50) | EMA(200) necesita exactamente 200 puntos para el primer valor estable |

> Constante en código: `VELAS_DESCARGAR_1D = 250` en `context_builder.py`. Los timeframes 1H y 4H siguen usando 200 velas descargadas / 150 válidas.

---

## RSI — Relative Strength Index

| Parámetro | Valor |
|---|---|
| Período | 14 |
| Fuente | `close` |
| Implementación | Wilder's RSI con `pandas.Series.ewm(alpha=1/14)` |
| Se calcula en | todos los timeframes |

**Umbrales de referencia para el cerebro:**

| Zona | Rango | Interpretación |
|---|---|---|
| Sobrevendido | < 30 | Posible agotamiento bajista |
| Neutral bajo | 30–50 | Momentum débil |
| Neutral | 50 | Sin sesgo |
| Neutral alto | 50–70 | Momentum positivo |
| Sobrecomprado | > 70 | Posible agotamiento alcista |

---

## EMAs — Medias Móviles Exponenciales

| EMA | Período | Uso |
|---|---|---|
| `ema_rapida` | 21 | Tendencia de corto/mediano plazo, referencia dinámica de soporte/resistencia |
| `ema_lenta` | 50 | Tendencia de mediano plazo, sesgo estructural |
| `ema_largo` | 200 | Referencia macro (calculada pero usada solo en 1D; omitir en 1H y 4H salvo pedido explícito) |

```python
ema_rapida = close.ewm(span=21, adjust=False).mean()
ema_lenta  = close.ewm(span=50, adjust=False).mean()
ema_largo  = close.ewm(span=200, adjust=False).mean()  # solo en 1D
```

**Lógica de tendencia basada en EMAs:**

| Condición | `tendencia` |
|---|---|
| `precio > ema_rapida > ema_lenta` y ambas con pendiente positiva | `"alcista"` |
| `precio < ema_rapida < ema_lenta` y ambas con pendiente negativa | `"bajista"` |
| Cualquier otra combinación | `"lateral"` |

**Pendiente:** se calcula como `ema[i] - ema[i-3]` (diferencia de 3 velas). Positiva si > 0, negativa si < 0.

---

## ATR — Average True Range

| Parámetro | Valor |
|---|---|
| Período | 14 |
| Implementación | True Range + Wilder's smoothing con `pandas.Series.ewm(alpha=1/14)` |
| Se calcula en | todos los timeframes |

El ATR se incluye en el contexto en unidades del par. El cerebro lo usa para evaluar la amplitud del movimiento reciente respecto de la volatilidad normal.

**Referencia para el cerebro:**
- `rango_reciente / ATR > 3` → mercado volátil o en movimiento direccional fuerte
- `rango_reciente / ATR < 1` → mercado en compresión / rango estrecho

Donde `rango_reciente = max(maximos_recientes) - min(minimos_recientes)`.

---

## Volumen

| Parámetro | Valor |
|---|---|
| Volumen de vela | `volume` de la vela de cierre |
| Promedio | SMA(20) del volumen |
| Implementación | `volume.rolling(window=20).mean()` |
| Se calcula en | todos los timeframes |

**Referencia para el cerebro:**

| Ratio `volumen / volumen_promedio` | Interpretación |
|---|---|
| < 0.5 | Volumen muy bajo — señal débil |
| 0.5–1.5 | Volumen normal |
| > 1.5 | Volumen elevado — mayor convicción en el movimiento |
| > 3.0 | Volumen anómalo — posible evento (noticias, liquidaciones) |

---

## Estructura de precio

### Máximos y mínimos recientes

Se toman los **5 cierres máximos y mínimos de las últimas 20 velas**, de más viejo a más nuevo.

```python
ventana = 20
maximos_recientes = close.rolling(ventana).max()  # simplificación fase 1
minimos_recientes = close.rolling(ventana).min()
# En la implementación real: detectar swing highs/lows con lógica propia en pandas
```

> Nota de implementación: para la Fase 1 se puede usar rolling max/min. Desde la Fase 3 en adelante, migrar a swing points reales para mayor precisión.

### Tendencia

Calculada con la lógica de EMAs descrita arriba. El campo `estructura.tendencia` es una redundancia explícita del cruce de EMAs para que el cerebro no tenga que derivarla.

---

## Señal base (strategy.py) — referencia rápida

La señal operativa viene del timeframe **1H**. Para la Fase 1–2 se usa:

| Condición | `senal_base` |
|---|---|
| `ema_rapida(21)` cruza hacia arriba `ema_lenta(50)` + `rsi > 50` | `"LONG"` |
| `ema_rapida(21)` cruza hacia abajo `ema_lenta(50)` + `rsi < 50` | `"SHORT"` |
| Cualquier otro caso | `"NONE"` |

Esta estrategia base es intencionalmente simple — es solo el input para el cerebro, no la estrategia final.

---

## Checklist antes de cambiar parámetros

- [ ] ¿El system prompt referencia umbrales que asumen los períodos actuales?
- [ ] ¿Se re-corrió la validación pasiva (Fase 3) con los nuevos parámetros?
- [ ] ¿Se actualizó el contrato del cerebro si cambió algún campo?
