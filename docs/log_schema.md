# Schema del Log — SQLite

Define las tablas de `trading_brain.db` antes de implementar `logger.py`. El schema determina qué podemos analizar en la Fase 5 — si falta una columna acá, no hay forma de recuperarla después.

---

## Tablas

### `brain_calls` — registro de cada llamada al cerebro

Una fila por llamada al LLM, exitosa o fallback.

```sql
CREATE TABLE brain_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identificación de la vela evaluada
    par               TEXT    NOT NULL,          -- "BTC/USDT"
    timeframe         TEXT    NOT NULL,          -- "1h"
    candle_timestamp  TEXT    NOT NULL,          -- ISO 8601, cierre de la vela

    -- Cuándo se hizo la llamada
    call_timestamp    TEXT    NOT NULL,          -- ISO 8601

    -- Contexto completo enviado al LLM (JSON serializado)
    context_json      TEXT    NOT NULL,

    -- Respuesta cruda del LLM (JSON string o mensaje de error)
    raw_response      TEXT,

    -- Decisión parseada y validada (JSON serializado)
    decision_json     TEXT    NOT NULL,

    -- Señal base que disparó la evaluación
    senal_base        TEXT    NOT NULL,          -- "LONG" | "SHORT" | "NONE"

    -- Resultado de la llamada
    is_fallback       INTEGER NOT NULL DEFAULT 0, -- 1 si se usó el fallback
    fallback_reason   TEXT,                       -- motivo del fallback (error API, schema inválido, etc.)

    -- Metadata de la llamada API
    model             TEXT,                       -- modelo usado
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    latency_ms        INTEGER,

    -- Precio posterior para evaluación (se completa en background, no en el momento)
    price_at_close    REAL,                       -- precio de cierre de la vela evaluada
    price_5c_later    REAL,                       -- close 5 velas después  (NULL hasta que pasen)
    price_10c_later   REAL,                       -- close 10 velas después
    price_20c_later   REAL                        -- close 20 velas después
);

CREATE INDEX idx_brain_calls_par_tf    ON brain_calls (par, timeframe);
CREATE INDEX idx_brain_calls_candle_ts ON brain_calls (candle_timestamp);
CREATE INDEX idx_brain_calls_fallback  ON brain_calls (is_fallback);
```

**Por qué `price_Nc_later`:** permite evaluar en Fase 5 si el régimen clasificado fue correcto y si las señales confirmadas tuvieron momentum real. Se completan con un job separado que corre N velas después.

---

### `paper_trades` — trades simulados

Una fila por trade abierto. Se actualiza cuando el trade se cierra.

```sql
CREATE TABLE paper_trades (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Vínculo con la llamada al cerebro que originó el trade
    brain_call_id         INTEGER NOT NULL REFERENCES brain_calls(id),

    par                   TEXT    NOT NULL,
    timeframe             TEXT    NOT NULL,
    direction             TEXT    NOT NULL,   -- "LONG" | "SHORT"

    -- Apertura
    entry_timestamp       TEXT    NOT NULL,   -- ISO 8601
    entry_price           REAL    NOT NULL,   -- open de la vela siguiente a la señal
    stop_price            REAL    NOT NULL,   -- entry ± 2 * ATR
    position_size         REAL    NOT NULL,   -- unidades de base currency (e.g., BTC)
    risk_amount_quote     REAL    NOT NULL,   -- USDT en riesgo = account * risk_pct * multiplicador
    multiplicador_riesgo  REAL    NOT NULL,   -- el que devolvió el cerebro

    -- Cierre (NULL mientras el trade está abierto)
    exit_timestamp        TEXT,
    exit_price            REAL,
    exit_reason           TEXT,   -- "STOP_HIT" | "SIGNAL_CLOSE" | "OPPOSITE_SIGNAL" | "TIMEOUT"
    pnl_quote             REAL,   -- P&L en USDT (positivo = ganancia)
    pnl_pct               REAL,   -- P&L como % del capital en riesgo
    fees_quote            REAL,   -- comisiones simuladas

    -- Estado
    status                TEXT    NOT NULL DEFAULT 'OPEN'  -- "OPEN" | "CLOSED"
);

CREATE INDEX idx_paper_trades_status   ON paper_trades (status);
CREATE INDEX idx_paper_trades_par      ON paper_trades (par, timeframe);
CREATE INDEX idx_paper_trades_brain_id ON paper_trades (brain_call_id);
```

---

### `account_snapshots` — estado del portfolio por vela

Una fila por vela procesada, para trazar la curva de equity.

```sql
CREATE TABLE account_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,   -- ISO 8601, cierre de la vela
    par             TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,
    equity          REAL    NOT NULL,   -- balance total en USDT (cerrado + abierto a precio de mercado)
    cash            REAL    NOT NULL,   -- USDT disponible (sin posiciones abiertas)
    open_trades     INTEGER NOT NULL    -- cantidad de trades abiertos en ese momento
);
```

---

## Consultas frecuentes (referencia Fase 5)

```sql
-- Tasa de fallback por par
SELECT par, COUNT(*) AS total, SUM(is_fallback) AS fallbacks,
       ROUND(100.0 * SUM(is_fallback) / COUNT(*), 1) AS fallback_pct
FROM brain_calls GROUP BY par;

-- Decisiones del cerebro por evaluacion_senal
SELECT json_extract(decision_json, '$.evaluacion_senal') AS decision,
       COUNT(*) AS total
FROM brain_calls WHERE is_fallback = 0 GROUP BY decision;

-- P&L acumulado de trades cerrados
SELECT par, COUNT(*) AS trades,
       ROUND(SUM(pnl_quote), 2) AS pnl_total_usdt,
       ROUND(AVG(pnl_pct) * 100, 2) AS avg_pnl_pct
FROM paper_trades WHERE status = 'CLOSED' GROUP BY par;

-- Llamadas donde el cerebro confirmó pero el precio bajó (para analizar errores)
SELECT bc.id, bc.par, bc.candle_timestamp,
       json_extract(bc.decision_json, '$.evaluacion_senal') AS decision,
       bc.price_at_close, bc.price_10c_later,
       ROUND((bc.price_10c_later - bc.price_at_close) / bc.price_at_close * 100, 2) AS ret_10c
FROM brain_calls bc
WHERE json_extract(decision_json, '$.evaluacion_senal') = 'confirmar'
  AND bc.senal_base = 'LONG'
  AND bc.price_10c_later < bc.price_at_close
  AND bc.is_fallback = 0;
```

---

## Notas de implementación

- El archivo de DB se lee de la variable de entorno `DB_PATH` (default: `trading_brain.db` en la raíz del proyecto)
- Nunca borrar filas — marcar como fallback o cerrar trades, siempre
- Las columnas `price_Nc_later` las completa un job separado, no el loop principal

### Valores esperados para `fallback_reason`

| Valor | Situación |
|---|---|
| `"CONTEXTO_INVALIDO"` | Campo obligatorio ausente o fuera de rango en la entrada |
| `"API_ERROR"` | Error HTTP, timeout o rate limit de la API de Anthropic |
| `"JSON_MALFORMADO"` | La respuesta del LLM no es JSON parseable |
| `"SCHEMA_INVALIDO"` | JSON válido pero con campos fuera de rango o tipos incorrectos |
| `"TOOL_NO_LLAMADO"` | El modelo no invocó la tool (respuesta de texto libre) |
