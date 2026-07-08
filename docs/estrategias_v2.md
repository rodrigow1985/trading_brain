# Estrategias v2 — Screener de Situaciones Técnicas (Daily)

> **Objetivo:** detectar SITUACIONES técnicas en timeframe diario y alertar para análisis manual.
> El bot NO genera señales de long/short. Solo indica "ocurrió X en el ticker Y".
> Todas las condiciones se evalúan sobre VELAS CERRADAS (nunca la vela en curso).

**Implementación:** `src/strategies/v2.py` · **Selección de versión:** `SCANNER_STRATEGY_SET` en `.env` (`v1` | `v2`) · **Rollback de código:** tag git `estrategias-v1`.

---

## Parámetros globales

| Parámetro | Valor default | Variable de entorno |
|---|---|---|
| Timeframe | 1D (diario) | — |
| EMA período | 20 | — |
| RSI período | 14 (sobre cierre) | — |
| RSI sobrecompra | 70 | `SCANNER_V2_RSI_SOBRECOMPRA` |
| RSI sobreventa | 30 | `SCANNER_V2_RSI_SOBREVENTA` |
| Volumen promedio | SMA(20) del volumen, **excluyendo la vela evaluada** | — |
| Tolerancia EMA ("toque") | 0.5% | `SCANNER_V2_TOLERANCIA_EMA_PCT` |
| Distancia "alejado" | 2% | `SCANNER_V2_ALEJADO_PCT` |
| Tendencia 20 ruedas | 8% | `SCANNER_V2_TENDENCIA_PCT` |
| Pico de volumen | 2.5× | `SCANNER_V2_VOL_SPIKE_RATIO` |
| Gap mínimo | 2% | `SCANNER_V2_GAP_PCT` |

Subconjunto de situaciones: `SCANNER_V2_SITUACIONES=1,2,5` (vacío = todas).

---

## SITUACIÓN 1 — Toque de EMA20 (`SIT1_TOQUE_EMA20`)

**Qué detecta:** el precio llegó a la zona de la EMA20 después de estar alejado.

**Condiciones:**
1. En alguna de las últimas 2 velas cerradas, el mínimo ≤ EMA20 × (1 + tolerancia) **y** el máximo ≥ EMA20 × (1 − tolerancia) — la vela tocó o cruzó la EMA.
2. En las 5 velas anteriores a ese toque, el cierre estuvo alejado de su EMA20 más del 2% (evita alertar cuando el precio viene pegado a la EMA hace días).

**Dato extra:** dirección desde la que llega (desde arriba = posible soporte / desde abajo = posible resistencia) y distancia % actual entre cierre y EMA20.

## SITUACIÓN 2 — Cruce confirmado de EMA20 (`SIT2_CRUCE_EMA20`)

**Qué detecta:** cambio de lado respecto a la EMA20 confirmado con 2 velas.

- **Alcista:** hace 3 velas cierre < EMA20; últimas 2 velas cerradas con cierre > EMA20.
- **Bajista:** espejo.

**Dato extra:** % de distancia del último cierre a la EMA20 y si el volumen promedio de las 2 velas de confirmación supera el volumen promedio (cruce con volumen = más relevante).

## SITUACIÓN 3 — RSI en sobrecompra tras tendencia alcista (`SIT3_RSI_SOBRECOMPRA`)

1. RSI(14) de la última vela cerrada ≥ 70.
2. Cierre actual ≥ +8% respecto al cierre de hace 20 ruedas (hubo subida real, no solo un pico).

**Dato extra:** RSI exacto, % de suba en 20 ruedas, velas consecutivas con RSI ≥ 70.

## SITUACIÓN 4 — RSI en sobreventa tras tendencia bajista (`SIT4_RSI_SOBREVENTA`)

1. RSI(14) ≤ 30.
2. Cierre actual ≤ −8% respecto al cierre de hace 20 ruedas.

**Dato extra:** RSI, % de caída en 20 ruedas, velas consecutivas en sobreventa.

## SITUACIÓN 5 — Divergencia RSI/precio (`SIT5_DIVERGENCIA_RSI`)

**Pivotes:** máximo/mínimo local con 2 velas a cada lado confirmando, buscados en las últimas 30 ruedas. El pivote más reciente debe estar recién confirmado (sus 2 velas de confirmación son las últimas 2 cerradas) para que la alerta sea oportuna.

- **Bajista:** el precio hace un pivote máximo mayor al pivote máximo anterior, pero el RSI en ese máximo es MENOR al RSI del máximo anterior.
- **Alcista:** pivote mínimo menor con RSI MAYOR.

**Dato extra:** precios y RSI de ambos pivotes.

## SITUACIÓN 6 — Vela de rechazo en la EMA20 (`SIT6_RECHAZO_EMA20`)

Complementa la Situación 1 con confirmación de price action (pin bar).

- **Rechazo alcista (EMA soporte):** la vela tocó la EMA20, mecha inferior ≥ 60% del rango, cierre en el tercio superior, cierre > EMA20.
- **Rechazo bajista (EMA resistencia):** espejo.

**Dato extra:** % de mecha sobre el rango, y si el volumen de la vela supera el promedio.

## SITUACIÓN 7 — Pico de volumen anómalo (`SIT7_PICO_VOLUMEN`)

1. Volumen de la última vela cerrada ≥ 2.5 × volumen promedio (SMA 20 previa).

**Dato extra:** dirección de la vela, ratio exacto, y si ocurrió cerca de la EMA20 (±2%) o de máximos/mínimos de 20 ruedas (±2%) — un pico en soporte/resistencia es más relevante.

## SITUACIÓN 8 — Compresión de volatilidad / squeeze de Bollinger (`SIT8_SQUEEZE_BOLLINGER`)

1. Ancho relativo de bandas de Bollinger (20, 2) = (superior − inferior) / SMA20.
2. El ancho actual está en el 20% más bajo de los últimos 90 días.

**Dato extra:** ancho actual y días consecutivos de compresión. No indica dirección.

## SITUACIÓN 9 — Máximo/mínimo de 52 semanas (`SIT9_EXTREMO_52W`)

1. Cierre ≥ máximo de las 250 ruedas previas, o
2. Cierre ≤ mínimo de las 250 ruedas previas.

**Dato extra:** nivel previo y si es zona sin referencia técnica anterior (dentro de la historia descargada, ~350 ruedas).

## SITUACIÓN 10 — Gap significativo en la apertura (`SIT10_GAP`)

**Solo acciones/CEDEARs** (no aplica a cripto 24/7).

1. |Apertura − cierre anterior| / cierre anterior ≥ 2%.

**Dato extra:** dirección del gap y, con la vela ya cerrada, si la rueda cerró achicando o extendiendo el gap.

---

## Reglas transversales

- **Velas cerradas:** el scanner descarta la vela cuya fecha (UTC) es hoy antes de evaluar (`_solo_velas_cerradas` en `src/scanner.py`).
- **Anti-duplicados:** una situación alertada no se repite hasta que la condición deje de cumplirse al menos un día (estado en la tabla SQLite `scanner_situaciones`, ver `src/scanner_state.py`).
- **Confluencia → PRIORITARIA:** si un ticker dispara 2+ situaciones simultáneas, la alerta se marca ⭐ PRIORITARIA.
- **Un mensaje por ticker:** todas las situaciones nuevas del día van en un solo mensaje de Telegram, con contexto (cierre, EMA20, RSI, volumen), análisis del cerebro y chart 1D.
- **Cerebro:** recibe el contexto MTF más la lista `situaciones_detectadas` (id, nombre, detalle) con `senal_base=NONE` — contextualiza sin imponer dirección.
- **Cadencia:** una corrida diaria tras el cierre de la vela 1D (00:00 UTC), `scripts/run_scanner.py`.
