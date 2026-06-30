# Bitácora — Fase 3: logger.py + validate_brain.py

**Fecha:** 2026-06-16
**Autor:** desarrollador

---

## Qué se implementó

### `src/logger.py`

Módulo de persistencia en SQLite. Funciones públicas:

- `init_db(db_path: str) -> None`: crea las tres tablas (`brain_calls`, `paper_trades`, `account_snapshots`) e índices si no existen. Idempotente.
- `log_brain_call(...) -> int`: inserta una fila en `brain_calls` y devuelve el `id` insertado.

Decisiones de implementación:
- `is_fallback` se detecta automáticamente buscando `"FALLBACK_ACTIVADO"` en `decision["alertas"]`.
- `fallback_reason` se extrae de `alertas[1]` (posición donde `brain.py` pone la razón).
- `input_tokens`, `output_tokens`, `price_Nc_later`: `None` por ahora, se completan en Fase 5 y por job separado respectivamente.
- `call_timestamp` = `datetime.now(timezone.utc).isoformat()` en el momento del insert.
- Cero imports de `anthropic`, `ccxt`, ni `pandas` — verificado con grep.

### `scripts/validate_brain.py`

Harness de validación pasiva. Loop de N iteraciones (configurable con `--iterations`, default 5):

1. `construir_contexto("BTC/USDT", "spot", "NONE", 1.0)`
2. `analizar(contexto)` con medición de latencia (`time.monotonic()`)
3. `log_brain_call(...)` → inserta en SQLite
4. Imprime resumen por línea: `[i/N] PAR TF | régimen=X | eval=Y | mult=Z | latencia=Nms | id=K`
5. Espera 5 segundos entre iteraciones para no saturar la API

Si `construir_contexto` falla (red, exchange) → loguea el error y continúa con la siguiente iteración. Si el cerebro devuelve fallback → registra y continúa (no frena el loop).

---

## Checkpoint ejecutado

```
docker compose run --rm brain python scripts/validate_brain.py --iterations 2
```

Output (resumen):
```
[1/2] BTC/USDT 1h | régimen=rango | eval=neutral | mult=0.00 | latencia=1108ms | id=1
[2/2] BTC/USDT 1h | régimen=rango | eval=neutral | mult=0.00 | latencia=756ms | id=2

Validación pasiva completada — 2/2 filas insertadas en brain_calls.
```

Proveedor usado: Groq (llama-3.3-70b-versatile), configurado en `.env`.

Verificación DB:
```
(1, 'BTC/USDT', 'NONE', 0, 1108)
(2, 'BTC/USDT', 'NONE', 0, 756)
```

- `is_fallback = 0` en ambas filas (el LLM respondió correctamente en las dos).
- `senal_base = "NONE"` — correcto, `construir_contexto` hardcodea `"NONE"` hasta Fase 4.
- `regimen = "rango"` con `eval = "neutral"` y `mult = 0.0` — consistente con `senal_base = "NONE"`.

---

## Notas

- El log muestra la fila insertada (`id=K`) directamente en el output de consola para facilitar trazabilidad.
- Las tablas `paper_trades` y `account_snapshots` se crean en `init_db()` pero sus funciones de escritura se implementan en Fase 4.
- `raw_response` se pasa como `None` porque `brain.py` no expone el string crudo del LLM al caller. Se puede agregar en Fase 5 modificando la firma de `analizar()`.
