"""
Logger de trading_brain — Fase 3.

Persistencia en SQLite de llamadas al cerebro, trades en papel y snapshots de cuenta.

Restricciones innegociables:
- NO importar anthropic, ccxt, ni pandas.
- Logging con el módulo estándar logging, no print.
- Type hints en todas las funciones públicas.
- Usar sqlite3 de la stdlib — sin dependencias adicionales.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from src.types import ContextoMercado, DecisionCerebro

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_BRAIN_CALLS = """
CREATE TABLE IF NOT EXISTS brain_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identificación de la vela evaluada
    par               TEXT    NOT NULL,
    timeframe         TEXT    NOT NULL,
    candle_timestamp  TEXT    NOT NULL,

    -- Cuándo se hizo la llamada
    call_timestamp    TEXT    NOT NULL,

    -- Contexto completo enviado al LLM (JSON serializado)
    context_json      TEXT    NOT NULL,

    -- Respuesta cruda del LLM (JSON string o mensaje de error)
    raw_response      TEXT,

    -- Decisión parseada y validada (JSON serializado)
    decision_json     TEXT    NOT NULL,

    -- Señal base que disparó la evaluación
    senal_base        TEXT    NOT NULL,

    -- Resultado de la llamada
    is_fallback       INTEGER NOT NULL DEFAULT 0,
    fallback_reason   TEXT,

    -- Metadata de la llamada API
    model             TEXT,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    latency_ms        INTEGER,

    -- Precio posterior para evaluación (se completa en background)
    price_at_close    REAL,
    price_5c_later    REAL,
    price_10c_later   REAL,
    price_20c_later   REAL
);
"""

_DDL_BRAIN_CALLS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_brain_calls_par_tf    ON brain_calls (par, timeframe);",
    "CREATE INDEX IF NOT EXISTS idx_brain_calls_candle_ts ON brain_calls (candle_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_brain_calls_fallback  ON brain_calls (is_fallback);",
]

_DDL_PAPER_TRADES = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,

    brain_call_id         INTEGER NOT NULL REFERENCES brain_calls(id),

    par                   TEXT    NOT NULL,
    timeframe             TEXT    NOT NULL,
    direction             TEXT    NOT NULL,

    -- Apertura
    entry_timestamp       TEXT    NOT NULL,
    entry_price           REAL    NOT NULL,
    stop_price            REAL    NOT NULL,
    position_size         REAL    NOT NULL,
    risk_amount_quote     REAL    NOT NULL,
    multiplicador_riesgo  REAL    NOT NULL,

    -- Cierre (NULL mientras el trade está abierto)
    exit_timestamp        TEXT,
    exit_price            REAL,
    exit_reason           TEXT,
    pnl_quote             REAL,
    pnl_pct               REAL,
    fees_quote            REAL,

    -- Estado
    status                TEXT    NOT NULL DEFAULT 'OPEN'
);
"""

_DDL_PAPER_TRADES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_status   ON paper_trades (status);",
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_par      ON paper_trades (par, timeframe);",
    "CREATE INDEX IF NOT EXISTS idx_paper_trades_brain_id ON paper_trades (brain_call_id);",
]

_DDL_ACCOUNT_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS account_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    par             TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,
    equity          REAL    NOT NULL,
    cash            REAL    NOT NULL,
    open_trades     INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> None:
    """
    Crea las tablas e índices si no existen. Idempotente.

    Args:
        db_path: Ruta al archivo SQLite. Se crea si no existe.
    """
    logger.info("Inicializando DB en '%s'", db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_DDL_BRAIN_CALLS)
        for idx_sql in _DDL_BRAIN_CALLS_INDEXES:
            conn.execute(idx_sql)
        conn.execute(_DDL_PAPER_TRADES)
        for idx_sql in _DDL_PAPER_TRADES_INDEXES:
            conn.execute(idx_sql)
        conn.execute(_DDL_ACCOUNT_SNAPSHOTS)
        conn.commit()
    logger.info("DB inicializada correctamente")


def log_brain_call(
    db_path: str,
    par: str,
    timeframe: str,
    candle_timestamp: str,
    context: ContextoMercado,
    decision: DecisionCerebro,
    raw_response: Optional[str],
    model: str,
    latency_ms: int,
) -> int:
    """
    Inserta una fila en brain_calls y devuelve el id insertado.

    is_fallback se detecta automáticamente: 1 si "FALLBACK_ACTIVADO" está en
    decision["alertas"]. fallback_reason se extrae del segundo elemento de
    alertas si is_fallback=1 (brain.py pone la razón en alertas[1]).

    Args:
        db_path:          Ruta al archivo SQLite.
        par:              Ticker en formato "BASE/QUOTE" (e.g. "BTC/USDT").
        timeframe:        Timeframe evaluado (e.g. "1h").
        candle_timestamp: ISO 8601 del cierre de la vela evaluada.
        context:          ContextoMercado enviado al cerebro.
        decision:         DecisionCerebro devuelta por analizar().
        raw_response:     JSON crudo devuelto por el LLM (o None en fallback/error).
        model:            Nombre del modelo usado.
        latency_ms:       Latencia de la llamada al cerebro en milisegundos.

    Returns:
        El id (INTEGER) de la fila insertada.
    """
    call_timestamp = datetime.now(timezone.utc).isoformat()
    context_json = json.dumps(context, ensure_ascii=False)
    decision_json = json.dumps(dict(decision), ensure_ascii=False)
    senal_base: str = context.get("senal_base", "NONE")  # type: ignore[assignment]

    # Detectar fallback
    alertas: list[str] = decision.get("alertas", [])  # type: ignore[assignment]
    is_fallback = 1 if "FALLBACK_ACTIVADO" in alertas else 0
    fallback_reason: Optional[str] = None
    if is_fallback and len(alertas) >= 2:
        fallback_reason = alertas[1]

    logger.debug(
        "Insertando brain_call — par=%s tf=%s senal=%s is_fallback=%d latency=%dms",
        par, timeframe, senal_base, is_fallback, latency_ms,
    )

    sql = """
        INSERT INTO brain_calls (
            par, timeframe, candle_timestamp, call_timestamp,
            context_json, raw_response, decision_json, senal_base,
            is_fallback, fallback_reason,
            model, input_tokens, output_tokens, latency_ms,
            price_at_close, price_5c_later, price_10c_later, price_20c_later
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?
        )
    """

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(sql, (
            par, timeframe, candle_timestamp, call_timestamp,
            context_json, raw_response, decision_json, senal_base,
            is_fallback, fallback_reason,
            model, None, None, latency_ms,
            None, None, None, None,
        ))
        conn.commit()
        row_id: int = cursor.lastrowid  # type: ignore[assignment]

    logger.info(
        "brain_call insertado — id=%d par=%s senal=%s regimen=%s eval=%s fallback=%s",
        row_id, par, senal_base,
        decision.get("regimen"), decision.get("evaluacion_senal"),
        bool(is_fallback),
    )
    return row_id


def log_paper_trade_open(
    db_path: str,
    brain_call_id: int,
    par: str,
    timeframe: str,
    direction: str,
    entry_timestamp: str,
    entry_price: float,
    stop_price: float,
    position_size: float,
    risk_amount_quote: float,
    multiplicador_riesgo: float,
) -> int:
    """
    Inserta un trade al abrirse en paper_trades.

    Args:
        db_path:              Ruta al archivo SQLite.
        brain_call_id:        id de la fila en brain_calls que originó el trade.
        par:                  Ticker en formato "BASE/QUOTE".
        timeframe:            Timeframe de la señal (e.g. "1h").
        direction:            "LONG" | "SHORT".
        entry_timestamp:      ISO 8601 del momento de entrada.
        entry_price:          Precio de entrada (con slippage aplicado).
        stop_price:           Precio del stop loss.
        position_size:        Tamaño de la posición en moneda base.
        risk_amount_quote:    Capital en riesgo en USDT.
        multiplicador_riesgo: Multiplicador devuelto por el cerebro.

    Returns:
        El id (INTEGER) de la fila insertada.
    """
    sql = """
        INSERT INTO paper_trades (
            brain_call_id, par, timeframe, direction,
            entry_timestamp, entry_price, stop_price,
            position_size, risk_amount_quote, multiplicador_riesgo,
            status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(sql, (
            brain_call_id, par, timeframe, direction,
            entry_timestamp, entry_price, stop_price,
            position_size, risk_amount_quote, multiplicador_riesgo,
        ))
        conn.commit()
        trade_id: int = cursor.lastrowid  # type: ignore[assignment]

    logger.info(
        "paper_trade abierto — id=%d par=%s dir=%s entry=%.4f stop=%.4f size=%.6f",
        trade_id, par, direction, entry_price, stop_price, position_size,
    )
    return trade_id


def log_paper_trade_close(
    db_path: str,
    trade_id: int,
    exit_timestamp: str,
    exit_price: float,
    exit_reason: str,
    pnl_quote: float,
    pnl_pct: float,
    fees_quote: float,
) -> None:
    """
    Actualiza un trade en paper_trades al cerrarse.

    Args:
        db_path:        Ruta al archivo SQLite.
        trade_id:       id de la fila a actualizar.
        exit_timestamp: ISO 8601 del momento de cierre.
        exit_price:     Precio de salida.
        exit_reason:    "STOP_HIT" | "SIGNAL_CLOSE" | "OPPOSITE_SIGNAL" | "TIMEOUT".
        pnl_quote:      P&L en USDT (positivo = ganancia).
        pnl_pct:        P&L como porcentaje del capital en riesgo.
        fees_quote:     Comisiones simuladas en USDT.
    """
    sql = """
        UPDATE paper_trades
        SET exit_timestamp = ?,
            exit_price     = ?,
            exit_reason    = ?,
            pnl_quote      = ?,
            pnl_pct        = ?,
            fees_quote     = ?,
            status         = 'CLOSED'
        WHERE id = ?
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(sql, (
            exit_timestamp, exit_price, exit_reason,
            pnl_quote, pnl_pct, fees_quote,
            trade_id,
        ))
        conn.commit()

    logger.info(
        "paper_trade cerrado — id=%d exit_reason=%s exit_price=%.4f pnl=%.2f USDT (%.2f%%)",
        trade_id, exit_reason, exit_price, pnl_quote, pnl_pct * 100,
    )


def log_account_snapshot(
    db_path: str,
    timestamp: str,
    par: str,
    timeframe: str,
    equity: float,
    cash: float,
    open_trades: int,
) -> None:
    """
    Inserta una fila en account_snapshots para la curva de equity vela a vela.

    Args:
        db_path:      Ruta al archivo SQLite.
        timestamp:    ISO 8601 del cierre de la vela.
        par:          Ticker en formato "BASE/QUOTE".
        timeframe:    Timeframe evaluado (e.g. "1h").
        equity:       Balance total en USDT (incluye P&L no realizado de posiciones abiertas).
        cash:         USDT disponible (no asignado a posiciones).
        open_trades:  Cantidad de trades abiertos en este momento.
    """
    sql = """
        INSERT INTO account_snapshots (timestamp, par, timeframe, equity, cash, open_trades)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(sql, (timestamp, par, timeframe, equity, cash, open_trades))
        conn.commit()

    logger.debug(
        "account_snapshot — ts=%s equity=%.2f cash=%.2f open_trades=%d",
        timestamp, equity, cash, open_trades,
    )
