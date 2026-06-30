# Bitácora — Fase 4: Loop paper end-to-end

**Fecha:** 2026-06-17
**Fase:** 4 — Loop mínimo en paper
**Estado:** Implementada y checkpoint OK

---

## Resumen

Implementación completa del loop paper end-to-end: señal base real (cruce de EMAs),
simulador de trades con stops, comisiones y slippage, y scheduler que corre indefinidamente
por vela 1H.

---

## Cambios realizados

### `src/types.py`

Agregados `ema_rapida_prev` y `ema_lenta_prev` a `Indicadores` y `IndicadoresDiario`.
Necesarios para detectar cruces de EMA (no solo posición relativa) en `strategy.py`.

### `src/context_builder.py`

Dos cambios:
1. En `_calcular_indicadores()`: se agrega `ema_rapida_prev = ema_rapida_series.iloc[-2]`
   y `ema_lenta_prev = ema_lenta_series.iloc[-2]` al dict de indicadores.
2. En `construir_contexto()`: se reemplaza el `senal_base = "NONE"` hardcodeado por
   una llamada real a `calcular_senal()`. Se arma un contexto preliminar (con
   `senal_base="NONE"` como placeholder) para pasárselo a strategy.py.

### `src/strategy.py` (nuevo)

Función `calcular_senal(contexto) -> str` que detecta cruces de EMA21/EMA50 en 1H:
- LONG si ema_rapida cruza hacia arriba ema_lenta + RSI > 50
- SHORT si ema_rapida cruza hacia abajo ema_lenta + RSI < 50
- NONE en cualquier otro caso

Manejo defensivo: si faltan campos en el contexto, devuelve NONE (nunca propaga excepción).
No importa ccxt, pandas ni anthropic.

### `src/logger.py`

Tres funciones nuevas al final del módulo:
- `log_paper_trade_open()`: inserta un trade al abrirse, devuelve el id.
- `log_paper_trade_close()`: actualiza el trade al cerrarse (exit_price, exit_reason, pnl, fees).
- `log_account_snapshot()`: inserta una fila en account_snapshots para la curva de equity.

### `src/paper_trader.py` (nuevo)

Dataclass `EstadoPaperTrader` + funciones `crear_estado()` y `procesar_vela()`.

Lógica de `procesar_vela()`:
1. Si hay posición abierta: evalúa TIMEOUT (primero) → STOP_HIT → OPPOSITE_SIGNAL/SIGNAL_CLOSE.
2. Si no hay posición y la señal confirma: abre trade (sizing con ATR, slippage 0.05%, fee 0.1%).
3. Actualiza `velas_desde_cierre`.
4. Inserta account_snapshot con equity a precio de mercado.

Restricción de re-entrada: `velas_desde_cierre >= 1` antes de abrir.
Cash mínimo: `PAPER_INITIAL_BALANCE * 0.05`.
En spot: al abrir, `cash -= nocional`; al cerrar, `cash = equity`.

### `src/scheduler.py` (nuevo)

Loop principal `run(par, mercado_tipo)`:
- Duerme hasta el próximo cierre de vela 1H en bloques de 60 s (interrompible con Ctrl+C).
- Por ciclo: construir contexto → llamar cerebro → log brain_call → procesar_vela.
- Cualquier excepción en un ciclo → log + continuar (nunca romper el loop).
- Estado del paper trader en memoria (se pierde si el proceso se reinicia).

Aproximación en esta fase: la vela OHLCV se construye desde el contexto MTF (close como
proxy del open, max/min de rolling 20 velas). En Fase 5 se puede mejorar descargando la
vela exacta.

### `scripts/run_scheduler.py` (nuevo)

Entrypoint que llama a `scheduler.run()`. Lee `TRADING_PAR` y `CCXT_MARKET_TYPE` del entorno.

### `docker-compose.yml`

Actualizado el comentario de Fase 4 para apuntar a `scripts/run_scheduler.py`.

---

## Checkpoint

Comando ejecutado:
```
docker compose run --rm brain python scripts/validate_brain.py --iterations 2
```

Resultado:
- 2/2 iteraciones completadas sin errores
- 2 filas insertadas en `brain_calls` (is_fallback=0)
- Los nuevos campos `ema_rapida_prev` y `ema_lenta_prev` se calculan correctamente
- `calcular_senal()` se llama sin errores y devuelve "NONE" (no hubo cruce en ese momento)
- `strategy.py` y `paper_trader.py` verificados: no importan ccxt, pandas ni anthropic

---

## Estado del mercado al momento del checkpoint

**BTC/USDT — 2026-06-17T00:00:00 UTC (vela 1H)**

El cerebro clasificó:
- Régimen: `rango`
- Evaluación: `neutral`
- Multiplicador de riesgo: `0.00`
- Señal base: `NONE` (sin cruce de EMA21/EMA50 en 1H)

Decisión del paper trader: **sin operación** (señal base NONE → el paper trader no evalúa
apertura; si hubiera posición abierta, evaluaría SIGNAL_CLOSE).

---

## Notas y decisiones de diseño

1. **Vela OHLCV aproximada**: el scheduler construye la vela OHLCV desde el contexto
   (close como open, rolling max/min). Suficiente para Fase 4; en Fase 5 mejorar con
   descarga directa de la vela cerrada.

2. **Estado en memoria**: `EstadoPaperTrader` vive en memoria durante el run. Si el
   proceso se reinicia, el balance vuelve al inicial. Persistencia en SQLite queda para
   Fase 5.

3. **Importación cruzada context_builder ↔ strategy**: `context_builder.py` importa
   `calcular_senal` desde `strategy.py`. No hay ciclo porque `strategy.py` solo importa
   de `src.types`. Se probó sin problemas en el checkpoint.

4. **`senal_base` en el contexto que va al cerebro**: se calcula antes de construir el
   dict final de `ContextoMercado`, de modo que el cerebro recibe la señal correcta.
   El cerebro puede usar `senal_base = "NONE"` como hint para devolver `neutral`.

5. **Telegram**: queda para Fase 5 según la spec.

---

## Para el analista

- El loop corre por vela 1H — aproximadamente 24 ciclos por día.
- Los trades simulados quedan en `paper_trades` con todos los campos de apertura y cierre.
- La curva de equity queda en `account_snapshots` (una fila por vela).
- Para arrancar el scheduler:
  ```
  docker compose run --rm brain python scripts/run_scheduler.py
  ```
  (o cambiar el `command` en docker-compose.yml).
