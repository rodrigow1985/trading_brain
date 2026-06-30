"""
Paper trader — Fase 4.

Simula trades en paper (sin dinero real) procesando una vela a la vez.
Aplica las reglas de sizing, stop loss, comisiones y slippage definidas
en docs/paper_trader.md.

Restricciones innegociables:
- CERO trading con dinero real — solo simulación.
- NO importar ccxt, pandas, pandas_ta ni anthropic.
- Logging con el módulo estándar logging, no print.
- Type hints en todas las funciones públicas.
- Las variables de entorno de configuración se leen en runtime, no en importación.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src import logger as db_logger
from src import notifier
from src.strategy import calcular_senal
from src.types import ContextoMercado, DecisionCerebro

log = logging.getLogger(__name__)

# Comisión taker Binance spot (0.1 %) y slippage estimado (0.05 %)
_FEE_PCT = 0.001
_SLIPPAGE_PCT = 0.0005


@dataclass
class EstadoPaperTrader:
    """Estado completo del paper trader en un momento dado."""

    equity: float
    cash: float
    posicion_actual: str            # "LONG" | "SHORT" | "NONE"
    entry_price: float | None       # precio de entrada con slippage
    stop_price: float | None        # precio del stop loss
    position_size: float | None     # tamaño en moneda base
    entry_timestamp: str | None     # ISO 8601 del momento de apertura
    candles_open: int               # velas que lleva abierta la posición
    brain_call_id: int | None       # id de brain_calls que originó el trade
    velas_desde_cierre: int         # velas desde el último cierre (restricción re-entrada)

    # Datos auxiliares para el cálculo de P&L al cerrar
    _trade_id: int | None = field(default=None, repr=False)
    _risk_amount: float | None = field(default=None, repr=False)
    _multiplicador_riesgo: float | None = field(default=None, repr=False)
    _equity_al_abrir: float | None = field(default=None, repr=False)
    _nocional_entrada: float | None = field(default=None, repr=False)


def crear_estado(initial_balance: float) -> EstadoPaperTrader:
    """
    Inicializa el estado del paper trader con balance completo en cash, sin posición.

    Args:
        initial_balance: Balance inicial en USDT (PAPER_INITIAL_BALANCE).

    Returns:
        EstadoPaperTrader inicializado.
    """
    log.info("Creando estado paper trader — balance inicial: %.2f USDT", initial_balance)
    return EstadoPaperTrader(
        equity=initial_balance,
        cash=initial_balance,
        posicion_actual="NONE",
        entry_price=None,
        stop_price=None,
        position_size=None,
        entry_timestamp=None,
        candles_open=0,
        brain_call_id=None,
        velas_desde_cierre=1,  # 1 para permitir entrar en la primera vela
    )


def procesar_vela(
    estado: EstadoPaperTrader,
    contexto: ContextoMercado,
    decision: DecisionCerebro,
    brain_call_id: int,
    vela_ohlcv: dict,
    db_path: str,
) -> EstadoPaperTrader:
    """
    Procesa una vela completa del loop paper.

    Orden de evaluación:
    1. Si hay posición abierta: evaluar TIMEOUT → STOP_HIT → señal opuesta / SIGNAL_CLOSE.
    2. Si no hay posición y la señal confirma: intentar abrir trade.
    3. Actualizar velas_desde_cierre.
    4. Insertar account_snapshot en SQLite.

    Args:
        estado:        Estado actual del paper trader.
        contexto:      ContextoMercado de la vela evaluada.
        decision:      DecisionCerebro devuelta por analizar().
        brain_call_id: id insertado en brain_calls para esta vela.
        vela_ohlcv:    Diccionario con keys: open, high, low, close.
        db_path:       Ruta al archivo SQLite.

    Returns:
        EstadoPaperTrader actualizado.
    """
    par = contexto["par"]
    timestamp = contexto["timestamp"]
    senal_base = calcular_senal(contexto)

    # Leer variables de entorno en runtime
    initial_balance = float(os.environ.get("PAPER_INITIAL_BALANCE", "10000"))
    risk_pct        = float(os.environ.get("PAPER_RISK_PCT", "0.01"))
    atr_mult        = float(os.environ.get("PAPER_ATR_STOP_MULT", "2.0"))
    max_hold        = int(os.environ.get("PAPER_MAX_HOLD_CANDLES", "20"))
    cash_minimo     = initial_balance * 0.05

    # Clonar el estado para no mutar el original
    s = EstadoPaperTrader(**estado.__dict__)

    hubo_cierre = False

    # -----------------------------------------------------------------------
    # Paso 1 — Evaluar posición existente
    # -----------------------------------------------------------------------
    if s.posicion_actual != "NONE":
        s.candles_open += 1

        exit_reason: str | None = None
        exit_price: float | None = None

        # --- TIMEOUT (se evalúa primero) ---
        if s.candles_open >= max_hold:
            exit_reason = "TIMEOUT"
            exit_price = float(vela_ohlcv["close"])
            log.info(
                "TIMEOUT — posición %s cerrada tras %d velas (límite: %d)",
                s.posicion_actual, s.candles_open, max_hold,
            )

        # --- STOP_HIT ---
        elif s.posicion_actual == "LONG" and float(vela_ohlcv["low"]) <= s.stop_price:
            exit_reason = "STOP_HIT"
            exit_price = s.stop_price
            log.info(
                "STOP_HIT LONG — low=%.4f <= stop=%.4f",
                vela_ohlcv["low"], s.stop_price,
            )

        elif s.posicion_actual == "SHORT" and float(vela_ohlcv["high"]) >= s.stop_price:
            exit_reason = "STOP_HIT"
            exit_price = s.stop_price
            log.info(
                "STOP_HIT SHORT — high=%.4f >= stop=%.4f",
                vela_ohlcv["high"], s.stop_price,
            )

        # --- Señal contraria u OPPOSITE_SIGNAL / SIGNAL_CLOSE ---
        else:
            es_opuesta = (
                (s.posicion_actual == "LONG" and senal_base == "SHORT") or
                (s.posicion_actual == "SHORT" and senal_base == "LONG")
            )
            if es_opuesta:
                exit_reason = "OPPOSITE_SIGNAL"
                exit_price = float(vela_ohlcv["close"])
                log.info(
                    "OPPOSITE_SIGNAL — posición %s cerrada por señal %s",
                    s.posicion_actual, senal_base,
                )
            elif senal_base == "NONE":
                exit_reason = "SIGNAL_CLOSE"
                exit_price = float(vela_ohlcv["close"])
                log.info(
                    "SIGNAL_CLOSE — posición %s cerrada por ausencia de señal",
                    s.posicion_actual,
                )

        # --- Cierre efectivo ---
        if exit_reason is not None and exit_price is not None:
            entry_p  = s.entry_price        # precio de entrada (con slippage ya aplicado)
            pos_size = s.position_size

            fee_open  = entry_p * pos_size * _FEE_PCT
            fee_close = exit_price * pos_size * _FEE_PCT
            fees = fee_open + fee_close

            if s.posicion_actual == "LONG":
                gross_pnl = (exit_price - entry_p) * pos_size
            else:  # SHORT
                gross_pnl = (entry_p - exit_price) * pos_size

            pnl_quote = gross_pnl - fees
            risk_amount = s._risk_amount if s._risk_amount else 0.0
            pnl_pct = pnl_quote / risk_amount if risk_amount > 0 else 0.0

            s.equity += pnl_quote
            s.cash = s.equity  # en spot, al cerrar toda la posición cash = equity

            exit_ts = datetime.now(timezone.utc).isoformat()
            db_logger.log_paper_trade_close(
                db_path=db_path,
                trade_id=s._trade_id,
                exit_timestamp=exit_ts,
                exit_price=exit_price,
                exit_reason=exit_reason,
                pnl_quote=pnl_quote,
                pnl_pct=pnl_pct,
                fees_quote=fees,
            )

            log.info(
                "Trade cerrado — dir=%s pnl=%.2f USDT (%.1f%%) fees=%.2f equity=%.2f",
                s.posicion_actual, pnl_quote, pnl_pct * 100, fees, s.equity,
            )

            try:
                notifier.notificar_trade_cerrado(
                    par=par,
                    direccion=s.posicion_actual,
                    entry_price=entry_p,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl_quote=pnl_quote,
                    pnl_pct=pnl_pct,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Error en notifier.notificar_trade_cerrado: %s", exc)

            # Resetear estado de posición
            s.posicion_actual = "NONE"
            s.entry_price = None
            s.stop_price = None
            s.position_size = None
            s.entry_timestamp = None
            s.candles_open = 0
            s.brain_call_id = None
            s._trade_id = None
            s._risk_amount = None
            s._multiplicador_riesgo = None
            s._equity_al_abrir = None
            s._nocional_entrada = None
            s.velas_desde_cierre = 0
            hubo_cierre = True

    # -----------------------------------------------------------------------
    # Paso 2 — Intentar abrir nueva posición
    # -----------------------------------------------------------------------
    if (
        not hubo_cierre
        and s.posicion_actual == "NONE"
        and decision["evaluacion_senal"] == "confirmar"
        and decision["multiplicador_riesgo"] > 0.0
        and s.velas_desde_cierre >= 1
        and s.cash >= cash_minimo
        and senal_base in ("LONG", "SHORT")
    ):
        atr_1h = float(contexto["timeframes"]["1h"]["indicadores"]["atr"])

        if atr_1h == 0:
            log.warning("ATR 1H = 0 — no se puede calcular stop_distance, omitiendo apertura")
        else:
            risk_amount = s.equity * risk_pct * decision["multiplicador_riesgo"]
            stop_dist   = atr_mult * atr_1h
            position_size = risk_amount / stop_dist

            open_price = float(vela_ohlcv["open"])
            slippage   = open_price * _SLIPPAGE_PCT

            if senal_base == "LONG":
                entry_with_slip = open_price + slippage
                stop_price_new  = entry_with_slip - stop_dist
            else:  # SHORT
                entry_with_slip = open_price - slippage
                stop_price_new  = entry_with_slip + stop_dist

            # Verificar que el nocional no supere el cash disponible
            nocional = entry_with_slip * position_size
            if nocional > s.cash:
                position_size = s.cash / entry_with_slip
                nocional = s.cash
                log.warning(
                    "Nocional ajustado al cash disponible — nuevo size=%.6f nocional=%.2f",
                    position_size, nocional,
                )

            entry_ts = datetime.now(timezone.utc).isoformat()
            trade_id = db_logger.log_paper_trade_open(
                db_path=db_path,
                brain_call_id=brain_call_id,
                par=par,
                timeframe="1h",
                direction=senal_base,
                entry_timestamp=entry_ts,
                entry_price=entry_with_slip,
                stop_price=stop_price_new,
                position_size=position_size,
                risk_amount_quote=risk_amount,
                multiplicador_riesgo=decision["multiplicador_riesgo"],
            )

            s.posicion_actual      = senal_base
            s.entry_price          = entry_with_slip
            s.stop_price           = stop_price_new
            s.position_size        = position_size
            s.entry_timestamp      = entry_ts
            s.candles_open         = 0
            s.brain_call_id        = brain_call_id
            s._trade_id            = trade_id
            s._risk_amount         = risk_amount
            s._multiplicador_riesgo = decision["multiplicador_riesgo"]
            s._equity_al_abrir     = s.equity
            s._nocional_entrada    = nocional

            # En spot: el cash se usa para comprar la posición
            s.cash -= nocional

            log.info(
                "Trade abierto — id=%d dir=%s entry=%.4f stop=%.4f size=%.6f "
                "risk=%.2f USDT mult=%.2f",
                trade_id, senal_base, entry_with_slip, stop_price_new,
                position_size, risk_amount, decision["multiplicador_riesgo"],
            )

            try:
                notifier.notificar_trade_abierto(
                    par=par,
                    direccion=senal_base,
                    entry_price=entry_with_slip,
                    stop_price=stop_price_new,
                    position_size=position_size,
                    risk_amount=risk_amount,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Error en notifier.notificar_trade_abierto: %s", exc)

    # -----------------------------------------------------------------------
    # Paso 3 — Actualizar velas_desde_cierre
    # -----------------------------------------------------------------------
    if not hubo_cierre:
        # Si se acaba de abrir, velas_desde_cierre ya estaba en >= 1
        # Si no se hizo nada, incrementar el contador
        if s.posicion_actual == "NONE":
            s.velas_desde_cierre += 1
        # Si se abrió una posición, no tocar velas_desde_cierre (es irrelevante mientras hay pos)

    # -----------------------------------------------------------------------
    # Paso 4 — Account snapshot
    # -----------------------------------------------------------------------
    close_price = float(vela_ohlcv["close"])
    if s.posicion_actual == "LONG" and s.entry_price is not None and s.position_size is not None:
        equity_real = s.cash + (close_price - s.entry_price) * s.position_size
    elif s.posicion_actual == "SHORT" and s.entry_price is not None and s.position_size is not None:
        equity_real = s.cash + (s.entry_price - close_price) * s.position_size
    else:
        equity_real = s.equity

    open_trades_count = 1 if s.posicion_actual != "NONE" else 0
    db_logger.log_account_snapshot(
        db_path=db_path,
        timestamp=timestamp,
        par=par,
        timeframe="1h",
        equity=equity_real,
        cash=s.cash,
        open_trades=open_trades_count,
    )

    log.debug(
        "Snapshot — equity_real=%.2f cash=%.2f posicion=%s",
        equity_real, s.cash, s.posicion_actual,
    )

    return s
