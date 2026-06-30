"""
Armador de contexto multi-timeframe para trading_brain — Fase 1.

Descarga velas con ccxt, calcula indicadores con pandas-ta,
y devuelve el dict de entrada al cerebro (ContextoMercado).

Restricción: este módulo NO importa anthropic.
"""

import logging
import os
from datetime import timezone

import ccxt
import pandas as pd

from src.types import ContextoMercado
from src.strategy import calcular_senal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Indicadores implementados con pandas puro (sin pandas-ta)
# pandas-ta no tiene distribución Linux en PyPI; usamos las fórmulas estándar.
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder's smoothing: alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    # Wilder's smoothing: alpha = 1/period
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


# Parámetros fijos de descarga (docs/indicadores.md)
VELAS_DESCARGAR = 200
VELAS_WARMUP = 50          # se descartan; las EMAs largas no están estabilizadas
VELAS_VALIDAS = 150        # últimas velas usadas para estructura y señal
VENTANA_ESTRUCTURA = 20    # rolling window para maximos/minimos recientes
N_MAXIMOS = 5              # cantidad de puntos en maximos_recientes / minimos_recientes

# HUECO DE SPEC: EMA(200) en 1D necesita al menos 200 velas válidas (post-warmup).
# Con la descarga estándar de 200 y descarte de 50, quedan solo 150 — insuficientes.
# Decisión conservadora: para 1D se descargan 250 velas, de modo que tras el warmup
# queden ≥200 velas válidas para calcular EMA(200). Ver bitácora 2026-06-15.
VELAS_DESCARGAR_1D = 250

TIMEFRAMES = ["4h", "1d", "1h"]


# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------

def _crear_exchange() -> ccxt.Exchange:
    """
    Crea e inicializa el exchange a partir de variables de entorno.

    Variables requeridas:
        CCXT_EXCHANGE  — nombre del exchange (e.g. "binance")
        CCXT_TESTNET   — "true" | "false"
    """
    exchange_id = os.environ["CCXT_EXCHANGE"]
    testnet = os.getenv("CCXT_TESTNET", "false").lower() == "true"

    exchange_class = getattr(ccxt, exchange_id)
    exchange: ccxt.Exchange = exchange_class()

    if testnet:
        exchange.set_sandbox_mode(True)
        logger.info("Exchange %s en modo testnet/sandbox", exchange_id)
    else:
        logger.info("Exchange %s en modo producción", exchange_id)

    return exchange


# ---------------------------------------------------------------------------
# Descarga de velas
# ---------------------------------------------------------------------------

def _descargar_ohlcv(
    exchange: ccxt.Exchange,
    par: str,
    timeframe: str,
    limit: int = VELAS_DESCARGAR,
) -> pd.DataFrame:
    """
    Descarga `limit` velas y devuelve un DataFrame con columnas
    [timestamp, open, high, low, close, volume].

    Descarta las primeras VELAS_WARMUP velas; retorna el resto.
    """
    logger.debug("Descargando %d velas %s %s", limit, par, timeframe)
    raw = exchange.fetch_ohlcv(par, timeframe=timeframe, limit=limit)

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")

    # Descartar warmup (las primeras velas tienen EMAs con inicialización incompleta)
    df = df.iloc[VELAS_WARMUP:]

    logger.debug(
        "Velas válidas %s %s: %d (desde %s hasta %s)",
        par, timeframe, len(df),
        df.index[0].isoformat(), df.index[-1].isoformat(),
    )
    return df


# ---------------------------------------------------------------------------
# Cálculo de indicadores
# ---------------------------------------------------------------------------

def _calcular_indicadores(df: pd.DataFrame, es_diario: bool = False) -> dict:
    """
    Calcula RSI, EMAs, ATR y volumen sobre el DataFrame dado.

    Si es_diario=True, agrega ema_largo (EMA 200).
    Devuelve los valores de la última vela del DataFrame.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    rsi_series = _rsi(close, period=14)
    ema_rapida_series = _ema(close, period=21)
    ema_lenta_series = _ema(close, period=50)
    atr_series = _atr(high, low, close, period=14)
    volumen_promedio_series = _sma(volume, period=20)

    indicadores: dict = {
        "rsi": float(rsi_series.iloc[-1]),
        "ema_rapida": float(ema_rapida_series.iloc[-1]),
        "ema_lenta": float(ema_lenta_series.iloc[-1]),
        "ema_rapida_prev": float(ema_rapida_series.iloc[-2]),
        "ema_lenta_prev": float(ema_lenta_series.iloc[-2]),
        "atr": float(atr_series.iloc[-1]),
        "volumen": float(volume.iloc[-1]),
        "volumen_promedio": float(volumen_promedio_series.iloc[-1]),
    }

    if es_diario:
        ema_largo_series = _ema(close, period=200)
        indicadores["ema_largo"] = float(ema_largo_series.iloc[-1])

    return indicadores


# ---------------------------------------------------------------------------
# Cálculo de tendencia
# ---------------------------------------------------------------------------

def _calcular_tendencia(df: pd.DataFrame, indicadores: dict) -> str:
    """
    Determina la tendencia según la lógica de EMAs definida en docs/indicadores.md.

    Alcista:  precio > ema_rapida > ema_lenta, ambas con pendiente positiva
    Bajista:  precio < ema_rapida < ema_lenta, ambas con pendiente negativa
    Lateral:  cualquier otro caso

    Pendiente: ema[i] - ema[i-3]  (>0 positiva, <0 negativa)
    """
    close = df["close"]
    ema_rapida_series = _ema(close, period=21)
    ema_lenta_series = _ema(close, period=50)

    precio_actual = float(close.iloc[-1])
    ema_rapida_actual = indicadores["ema_rapida"]
    ema_lenta_actual = indicadores["ema_lenta"]

    # Necesitamos al menos 4 velas para calcular la pendiente (i vs i-3)
    if len(ema_rapida_series) < 4 or len(ema_lenta_series) < 4:
        logger.warning("Datos insuficientes para calcular pendiente — tendencia: lateral")
        return "lateral"

    pendiente_rapida = float(ema_rapida_series.iloc[-1]) - float(ema_rapida_series.iloc[-4])
    pendiente_lenta = float(ema_lenta_series.iloc[-1]) - float(ema_lenta_series.iloc[-4])

    es_alcista = (
        precio_actual > ema_rapida_actual > ema_lenta_actual
        and pendiente_rapida > 0
        and pendiente_lenta > 0
    )
    es_bajista = (
        precio_actual < ema_rapida_actual < ema_lenta_actual
        and pendiente_rapida < 0
        and pendiente_lenta < 0
    )

    if es_alcista:
        return "alcista"
    if es_bajista:
        return "bajista"
    return "lateral"


# ---------------------------------------------------------------------------
# Cálculo de estructura
# ---------------------------------------------------------------------------

def _calcular_estructura(df: pd.DataFrame, indicadores: dict) -> dict:
    """
    Calcula la estructura de precio: precio actual, máximos/mínimos recientes y tendencia.

    Máximos y mínimos: rolling max/min de las últimas VENTANA_ESTRUCTURA velas,
    tomando los últimos N_MAXIMOS valores (de más viejo a más nuevo).

    Fase 1: rolling max/min sobre close (simplificación documentada en indicadores.md).
    """
    close = df["close"]

    rolling_max = close.rolling(VENTANA_ESTRUCTURA).max()
    rolling_min = close.rolling(VENTANA_ESTRUCTURA).min()

    # Tomar los últimos N_MAXIMOS valores válidos
    maximos = rolling_max.dropna().iloc[-N_MAXIMOS:].tolist()
    minimos = rolling_min.dropna().iloc[-N_MAXIMOS:].tolist()

    tendencia = _calcular_tendencia(df, indicadores)

    return {
        "precio_actual": float(close.iloc[-1]),
        "maximos_recientes": [float(v) for v in maximos],
        "minimos_recientes": [float(v) for v in minimos],
        "tendencia": tendencia,
    }


# ---------------------------------------------------------------------------
# Construcción del contexto por timeframe
# ---------------------------------------------------------------------------

def _construir_contexto_timeframe(
    exchange: ccxt.Exchange,
    par: str,
    timeframe: str,
) -> tuple[dict, str]:
    """
    Descarga velas y calcula indicadores + estructura para un timeframe.
    Devuelve (sub-dict {indicadores, estructura}, timestamp_iso de la última vela).

    Para 1D se descargan VELAS_DESCARGAR_1D (250) velas para que EMA(200)
    tenga suficientes datos post-warmup.
    """
    es_diario = timeframe == "1d"
    limit = VELAS_DESCARGAR_1D if es_diario else VELAS_DESCARGAR
    df = _descargar_ohlcv(exchange, par, timeframe, limit=limit)
    indicadores = _calcular_indicadores(df, es_diario=es_diario)
    estructura = _calcular_estructura(df, indicadores)

    # Timestamp de la última vela (cierre)
    ultimo_ts = df.index[-1]
    if ultimo_ts.tzinfo is None:
        ultimo_ts = ultimo_ts.replace(tzinfo=timezone.utc)
    timestamp_iso = ultimo_ts.isoformat()

    return {
        "indicadores": indicadores,
        "estructura": estructura,
    }, timestamp_iso


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def construir_contexto(
    par: str,
    mercado_tipo: str,
    posicion_actual: str,
    riesgo_disponible_pct: float,
) -> ContextoMercado:
    """
    Construye el contexto multi-timeframe completo para el cerebro.

    Args:
        par:                  Ticker en formato "BASE/QUOTE" (e.g. "BTC/USDT").
        mercado_tipo:         "spot" | "futuro". La variable de entorno CCXT_MARKET_TYPE
                              usa "spot"/"future"; este parámetro acepta el valor ya mapeado
                              ("futuro") o el valor crudo ("future") y lo normaliza.
        posicion_actual:      "LONG" | "SHORT" | "NONE"
        riesgo_disponible_pct: Porcentaje del capital disponible, rango [0.0, 1.0].

    Returns:
        ContextoMercado listo para pasarse a brain.py.
    """
    # Normalizar "future" → "futuro" según contrato_cerebro.md
    if mercado_tipo == "future":
        mercado_tipo = "futuro"

    logger.info(
        "Construyendo contexto: par=%s mercado=%s posicion=%s riesgo=%.2f",
        par, mercado_tipo, posicion_actual, riesgo_disponible_pct,
    )

    exchange = _crear_exchange()

    timeframes_ctx: dict = {}
    timestamp_1h: str = ""

    for tf in TIMEFRAMES:
        logger.info("Procesando timeframe %s", tf)
        ctx_tf, ts_tf = _construir_contexto_timeframe(exchange, par, tf)
        timeframes_ctx[tf] = ctx_tf

        if tf == "1h":
            timestamp_1h = ts_tf

    # Calcular señal base usando strategy.py (Fase 4).
    # Se arma un contexto preliminar para pasárselo a calcular_senal().
    _contexto_preliminar: ContextoMercado = {
        "par": par,
        "timestamp": timestamp_1h,
        "mercado_tipo": mercado_tipo,
        "senal_base": "NONE",  # placeholder
        "portfolio": {
            "posicion_actual": posicion_actual,
            "riesgo_disponible_pct": riesgo_disponible_pct,
        },
        "timeframes": timeframes_ctx,
    }
    senal_base = calcular_senal(_contexto_preliminar)
    logger.info("Señal base calculada: %s", senal_base)

    contexto: ContextoMercado = {
        "par": par,
        "timestamp": timestamp_1h,
        "mercado_tipo": mercado_tipo,
        "senal_base": senal_base,
        "portfolio": {
            "posicion_actual": posicion_actual,
            "riesgo_disponible_pct": riesgo_disponible_pct,
        },
        "timeframes": timeframes_ctx,
    }

    logger.info("Contexto construido — timestamp 1H: %s", timestamp_1h)
    return contexto
