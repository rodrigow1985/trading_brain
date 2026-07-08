"""
Indicadores técnicos compartidos (pandas puro, sin dependencias externas).

Movidos desde scanner.py para que las estrategias versionadas y el scanner
usen exactamente el mismo cálculo.
"""

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def bollinger_ancho(close: pd.Series, period: int = 20, n_std: float = 2.0) -> pd.Series:
    """
    Ancho relativo de las bandas de Bollinger:
    (banda superior − banda inferior) / SMA = 2·n_std·σ / SMA.
    """
    media = sma(close, period)
    std = close.rolling(window=period).std()
    return (2 * n_std * std) / media
