"""
Tipos compartidos entre módulos del proyecto trading_brain.

Estos TypedDicts definen el contrato de datos entre context_builder.py y brain.py.
Cualquier cambio aquí requiere actualizar docs/contrato_cerebro.md.
"""

from typing import TypedDict


class Indicadores(TypedDict):
    """Indicadores técnicos para un timeframe dado."""

    rsi: float              # RSI(14), rango [0, 100]
    ema_rapida: float       # EMA(21), precio
    ema_lenta: float        # EMA(50), precio
    ema_rapida_prev: float  # EMA(21) de la vela anterior (para detección de cruce)
    ema_lenta_prev: float   # EMA(50) de la vela anterior
    atr: float              # ATR(14), en unidades del par
    volumen: float          # volumen de la vela de cierre
    volumen_promedio: float  # SMA(20) del volumen


class IndicadoresDiario(TypedDict):
    """Indicadores técnicos para el timeframe 1D (incluye EMA 200)."""

    rsi: float
    ema_rapida: float       # EMA(21)
    ema_lenta: float        # EMA(50)
    ema_rapida_prev: float  # EMA(21) de la vela anterior (para detección de cruce)
    ema_lenta_prev: float   # EMA(50) de la vela anterior
    ema_largo: float        # EMA(200) — solo en 1D
    atr: float
    volumen: float
    volumen_promedio: float


class Estructura(TypedDict):
    """Estructura de precio para un timeframe dado."""

    precio_actual: float           # close de la vela evaluada
    maximos_recientes: list[float]  # últimos 5 máximos (viejo → nuevo)
    minimos_recientes: list[float]  # últimos 5 mínimos (viejo → nuevo)
    tendencia: str                 # "alcista" | "bajista" | "lateral"


class ContextoTimeframe(TypedDict):
    """Contexto completo para un timeframe: indicadores + estructura."""

    indicadores: Indicadores
    estructura: Estructura


class ContextoTimeframeDiario(TypedDict):
    """Contexto completo para el timeframe 1D: indicadores (con EMA 200) + estructura."""

    indicadores: IndicadoresDiario
    estructura: Estructura


class Portfolio(TypedDict):
    """Estado actual del portfolio."""

    posicion_actual: str           # "LONG" | "SHORT" | "NONE"
    riesgo_disponible_pct: float   # % del capital disponible, rango [0.0, 1.0]



class ContextoMercado(TypedDict):
    """
    Dict completo de entrada al cerebro (brain.py).

    Armado íntegramente por context_builder.py.
    Schema canónico en docs/contrato_cerebro.md.
    """

    par: str              # e.g. "BTC/USDT"
    timestamp: str        # ISO 8601, cierre de la última vela 1H
    mercado_tipo: str     # "spot" | "futuro"
    senal_base: str       # "LONG" | "SHORT" | "NONE"
    portfolio: Portfolio
    timeframes: dict      # claves: "4h", "1d", "1h"


class DecisionCerebro(TypedDict):
    """Salida del cerebro (brain.py). Schema canónico en docs/contrato_cerebro.md."""

    regimen: str                    # "tendencia_alcista" | "tendencia_bajista" | "rango" | "volatil"
    confianza_regimen: float        # [0.0, 1.0]
    evaluacion_senal: str           # "confirmar" | "vetar" | "neutral"
    conviccion: float               # [0.0, 1.0]
    multiplicador_riesgo: float     # [0.0, 1.0]
    factores_clave: list[str]       # longitud [1, 5]
    racional: str                   # máx 280 caracteres
    alertas: list[str]              # puede ser vacío
