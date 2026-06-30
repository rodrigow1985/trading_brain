"""
Estrategia base de trading — Fase 4.

Calcula la señal operativa del timeframe 1H a partir del contexto MTF.
La señal es el input para el cerebro (brain.py) — no es una decisión de ejecución.

Restricciones innegociables:
- NO importar ccxt, pandas, pandas_ta ni anthropic.
- Logging con el módulo estándar logging, no print.
- Type hints en todas las funciones públicas.
"""

import logging

from src.types import ContextoMercado

logger = logging.getLogger(__name__)


def calcular_senal(contexto: ContextoMercado) -> str:
    """
    Calcula la señal base del timeframe 1H.

    LONG:  EMA21 cruza hacia arriba EMA50
           (prev: ema_rapida <= ema_lenta, actual: ema_rapida > ema_lenta) + RSI > 50

    SHORT: EMA21 cruza hacia abajo EMA50
           (prev: ema_rapida >= ema_lenta, actual: ema_rapida < ema_lenta) + RSI < 50

    NONE:  cualquier otro caso

    Returns:
        "LONG" | "SHORT" | "NONE"
    """
    try:
        ind = contexto["timeframes"]["1h"]["indicadores"]
    except (KeyError, TypeError) as exc:
        logger.warning("No se pudo acceder a indicadores 1H: %s — devolviendo NONE", exc)
        return "NONE"

    try:
        ema_rapida      = float(ind["ema_rapida"])
        ema_lenta       = float(ind["ema_lenta"])
        ema_rapida_prev = float(ind["ema_rapida_prev"])
        ema_lenta_prev  = float(ind["ema_lenta_prev"])
        rsi             = float(ind["rsi"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Error leyendo indicadores para señal base: %s — devolviendo NONE", exc)
        return "NONE"

    cruce_alcista = (ema_rapida_prev <= ema_lenta_prev) and (ema_rapida > ema_lenta)
    cruce_bajista = (ema_rapida_prev >= ema_lenta_prev) and (ema_rapida < ema_lenta)

    if cruce_alcista and rsi > 50:
        logger.info(
            "Señal LONG — cruce alcista EMA21/EMA50 (prev: %.2f/%.2f, actual: %.2f/%.2f) RSI=%.1f",
            ema_rapida_prev, ema_lenta_prev, ema_rapida, ema_lenta, rsi,
        )
        return "LONG"

    if cruce_bajista and rsi < 50:
        logger.info(
            "Señal SHORT — cruce bajista EMA21/EMA50 (prev: %.2f/%.2f, actual: %.2f/%.2f) RSI=%.1f",
            ema_rapida_prev, ema_lenta_prev, ema_rapida, ema_lenta, rsi,
        )
        return "SHORT"

    logger.debug(
        "Señal NONE — sin cruce válido (prev: %.2f/%.2f, actual: %.2f/%.2f, RSI=%.1f)",
        ema_rapida_prev, ema_lenta_prev, ema_rapida, ema_lenta, rsi,
    )
    return "NONE"
