"""
Charting — genera PNG de velas para adjuntar en Telegram.

Dependencias: mplfinance>=0.12.10a1 (lazy import para no romper si no está instalado).
"""

import io
import logging

import pandas as pd

log = logging.getLogger(__name__)

N_VELAS_CHART = 80
_MPF_STYLE    = "nightclouds"


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def generar_chart_png(
    df: pd.DataFrame,
    par: str,
    timeframe: str,
    n_velas: int = N_VELAS_CHART,
) -> bytes:
    """
    Genera gráfico de velas + EMA20 + RSI subplot (estilo oscuro).

    Args:
        df:         DataFrame OHLCV con índice DatetimeIndex.
        par:        Ticker (ej. "BTC/USDT", "MSFT").
        timeframe:  Timeframe string (ej. "4h", "1d").
        n_velas:    Cantidad de velas a mostrar.

    Returns:
        PNG como bytes. Lanza ImportError si mplfinance no está instalado.
    """
    try:
        import mplfinance as mpf
        import matplotlib
        matplotlib.use("Agg")  # sin display — modo headless
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "mplfinance no instalado. Agregar mplfinance>=0.12.10a1 a requirements.txt"
        ) from exc

    df_raw   = df.iloc[-n_velas:].copy()
    close    = df_raw["close"]
    ema20    = _ema(close, 20).values
    rsi_vals = _rsi(close, 14).values

    # mplfinance requiere columnas capitalizadas
    df_mpf = df_raw.rename(columns={
        "open":   "Open",
        "high":   "High",
        "low":    "Low",
        "close":  "Close",
        "volume": "Volume",
    })[["Open", "High", "Low", "Close", "Volume"]]

    # mplfinance no soporta timezone-aware index en todas las versiones
    if df_mpf.index.tz is not None:
        df_mpf.index = df_mpf.index.tz_localize(None)

    level_70 = [70.0] * len(df_mpf)
    level_30 = [30.0] * len(df_mpf)

    addplots = [
        mpf.make_addplot(ema20,    type="line", color="#f0a500", width=1.8, panel=0, label="EMA20"),
        mpf.make_addplot(rsi_vals, type="line", color="#a855f7", width=1.2, panel=2, ylabel="RSI"),
        mpf.make_addplot(level_70, type="line", color="#ef4444", linestyle="--", width=0.7, panel=2),
        mpf.make_addplot(level_30, type="line", color="#22c55e", linestyle="--", width=0.7, panel=2),
    ]

    titulo = f"{par}  ·  {timeframe.upper()}"

    fig, _ = mpf.plot(
        df_mpf,
        type="candle",
        addplot=addplots,
        style=_MPF_STYLE,
        title=titulo,
        volume=True,
        panel_ratios=(4, 1, 2),
        figsize=(10, 7),
        returnfig=True,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
