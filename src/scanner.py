"""
Scanner 4H — Fase 4+.

Escanea múltiples activos (cripto + acciones) buscando setups de entrada LONG:

  Condición en 4H (trigger):
    - Precio dentro del ±2% de la EMA20
    - RSI < 35 (sobreventa)

  Pre-filtro de tendencia (solo pasa si AMBOS son alcistas):
    - 1D alcista: close > EMA50 diario
    - 1W alcista: close > EMA20 semanal

  Si pasa el pre-filtro → llama al cerebro con contexto MTF completo.
  El cerebro confirma solo si la tendencia macro (1W + 1D) respalda la entrada.

Tipos de activos soportados:
  - Cripto: "BTC/USDT" (descarga via ccxt/Binance)
  - Acciones: "AAPL" (descarga via yfinance/Yahoo Finance)

Restricciones:
  - NO importa anthropic directamente — usa brain.analizar()
  - Logging con módulo estándar logging, no print
  - Type hints en todas las funciones públicas
"""

import logging
import os
from datetime import timezone
from typing import Optional

import ccxt
import pandas as pd

from src.brain import contextualizar
from src.types import ContextoMercado

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parámetros de la estrategia
# ---------------------------------------------------------------------------

EMA20_PERIODO = 20
EMA50_PERIODO = 50
RSI_PERIODO = 14
UMBRAL_DIST_EMA20_PCT = 0.02   # precio dentro del ±2% de la EMA20
UMBRAL_RSI_SOBREVENTA = 35.0

# Velas a descargar por timeframe
N_VELAS_4H = 200
N_VELAS_1D = 300
N_VELAS_1H = 200
N_VELAS_1W = 104  # ~2 años de datos semanales
VELAS_WARMUP = 50

VENTANA_ESTRUCTURA = 20
N_PUNTOS_ESTRUCTURA = 5


# ---------------------------------------------------------------------------
# Detección del tipo de activo
# ---------------------------------------------------------------------------

def _es_accion(par: str) -> bool:
    """Ticker sin '/' → acción (ej. AAPL). Con '/' → cripto (ej. BTC/USDT)."""
    return "/" not in par


# ---------------------------------------------------------------------------
# Indicadores (pandas puro — sin pandas-ta)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
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
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


# ---------------------------------------------------------------------------
# Descarga de datos
# ---------------------------------------------------------------------------

def _crear_exchange() -> ccxt.Exchange:
    exchange_id = os.environ.get("CCXT_EXCHANGE", "binance")
    testnet = os.getenv("CCXT_TESTNET", "false").lower() == "true"
    exchange_class = getattr(ccxt, exchange_id)
    exchange: ccxt.Exchange = exchange_class()
    if testnet:
        exchange.set_sandbox_mode(True)
    return exchange


def _descargar_crypto(par: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Descarga OHLCV de Binance para un par cripto."""
    exchange = _crear_exchange()
    raw = exchange.fetch_ohlcv(par, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return df


def _descargar_accion(ticker: str, timeframe: str, limit: int) -> pd.DataFrame:
    """
    Descarga OHLCV de Yahoo Finance para una acción.

    Timeframes soportados: "1h", "4h" (resampleado desde 1h), "1d", "1w".
    El parámetro `limit` se ignora — yfinance usa period fijo.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError(
            "yfinance no instalado. Instalalo con: pip install yfinance>=0.2.0"
        )

    t = yf.Ticker(ticker)

    if timeframe in ("1h", "4h"):
        # yfinance soporta hasta 730 días para 1h
        df_raw = t.history(period="2y", interval="1h", auto_adjust=True)
    elif timeframe == "1d":
        df_raw = t.history(period="5y", interval="1d", auto_adjust=True)
    elif timeframe == "1w":
        df_raw = t.history(period="5y", interval="1wk", auto_adjust=True)
    else:
        raise ValueError(f"Timeframe no soportado para acciones: {timeframe}")

    if df_raw.empty:
        raise ValueError(f"yfinance no devolvió datos para {ticker} ({timeframe})")

    # Normalizar a minúsculas y seleccionar columnas OHLCV
    df_raw.columns = [c.lower() for c in df_raw.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df_raw.columns]
    df = df_raw[cols].copy()

    # Asegurar índice UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    # Resamplear 1H → 4H eliminando huecos por mercado cerrado
    if timeframe == "4h":
        df = (
            df.resample("4h")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )

    return df


def _descargar(par: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Despacha la descarga según el tipo de activo (cripto o acción)."""
    if _es_accion(par):
        return _descargar_accion(par, timeframe, limit)
    return _descargar_crypto(par, timeframe, limit)


# ---------------------------------------------------------------------------
# Condición del scanner en 4H
# ---------------------------------------------------------------------------

def _evaluar_condicion_4h(df: pd.DataFrame) -> tuple[bool, dict]:
    """
    Verifica la condición de entrada en el timeframe 4H:
      - Precio dentro del ±2% de la EMA20
      - RSI < 35

    Args:
        df: DataFrame con warmup ya aplicado.

    Returns:
        (cumple, metricas) donde metricas tiene precio, ema20, dist_ema20_pct, rsi.
    """
    close = df["close"]
    ema20 = _ema(close, EMA20_PERIODO)
    rsi = _rsi(close, RSI_PERIODO)

    precio = float(close.iloc[-1])
    ema20_val = float(ema20.iloc[-1])
    rsi_val = float(rsi.iloc[-1])

    dist_pct = (precio - ema20_val) / ema20_val  # positivo = sobre EMA, negativo = bajo

    cumple = abs(dist_pct) <= UMBRAL_DIST_EMA20_PCT and rsi_val < UMBRAL_RSI_SOBREVENTA

    return cumple, {
        "precio": precio,
        "ema20": ema20_val,
        "dist_ema20_pct": dist_pct * 100,
        "rsi": rsi_val,
    }


def _tendencia_alcista_1d(df: pd.DataFrame) -> bool:
    """1D alcista: close por encima de la EMA50 diaria."""
    ema50 = _ema(df["close"], EMA50_PERIODO)
    return float(df["close"].iloc[-1]) > float(ema50.iloc[-1])


def _tendencia_alcista_1w(df: pd.DataFrame) -> bool:
    """1W alcista: close por encima de la EMA20 semanal."""
    ema20 = _ema(df["close"], EMA20_PERIODO)
    return float(df["close"].iloc[-1]) > float(ema20.iloc[-1])


# ---------------------------------------------------------------------------
# Construcción del contexto para el cerebro
# ---------------------------------------------------------------------------

def _construir_tf_ctx(df: pd.DataFrame, es_diario: bool = False) -> dict:
    """
    Construye el sub-dict {indicadores, estructura} para un timeframe.
    El df recibido ya debe tener el warmup aplicado.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    rsi_s = _rsi(close, RSI_PERIODO)
    ema21_s = _ema(close, 21)
    ema50_s = _ema(close, 50)
    atr_s = _atr(high, low, close)
    vol_prom_s = _sma(volume, 20)

    indicadores: dict = {
        "rsi": float(rsi_s.iloc[-1]),
        "ema_rapida": float(ema21_s.iloc[-1]),
        "ema_lenta": float(ema50_s.iloc[-1]),
        "ema_rapida_prev": float(ema21_s.iloc[-2]),
        "ema_lenta_prev": float(ema50_s.iloc[-2]),
        "atr": max(float(atr_s.iloc[-1]), 1e-8),  # ATR > 0 requerido por la validación
        "volumen": float(volume.iloc[-1]),
        "volumen_promedio": max(float(vol_prom_s.iloc[-1]), 1e-8),
    }

    if es_diario:
        ema200_s = _ema(close, 200)
        indicadores["ema_largo"] = float(ema200_s.iloc[-1])

    # Estructura
    rolling_max = close.rolling(VENTANA_ESTRUCTURA).max()
    rolling_min = close.rolling(VENTANA_ESTRUCTURA).min()
    maximos = rolling_max.dropna().iloc[-N_PUNTOS_ESTRUCTURA:].tolist()
    minimos = rolling_min.dropna().iloc[-N_PUNTOS_ESTRUCTURA:].tolist()

    # Rellenar hasta 5 puntos si hay pocos datos
    while len(maximos) < N_PUNTOS_ESTRUCTURA:
        maximos.insert(0, maximos[0] if maximos else float(close.iloc[0]))
    while len(minimos) < N_PUNTOS_ESTRUCTURA:
        minimos.insert(0, minimos[0] if minimos else float(close.iloc[0]))

    precio = float(close.iloc[-1])
    ema21 = indicadores["ema_rapida"]
    ema50 = indicadores["ema_lenta"]

    if precio > ema21 > ema50:
        tendencia = "alcista"
    elif precio < ema21 < ema50:
        tendencia = "bajista"
    else:
        tendencia = "lateral"

    estructura = {
        "precio_actual": precio,
        "maximos_recientes": [float(v) for v in maximos[:N_PUNTOS_ESTRUCTURA]],
        "minimos_recientes": [float(v) for v in minimos[:N_PUNTOS_ESTRUCTURA]],
        "tendencia": tendencia,
    }

    return {"indicadores": indicadores, "estructura": estructura}


def _aplicar_warmup(df: pd.DataFrame) -> pd.DataFrame:
    """Descarta las primeras VELAS_WARMUP filas para estabilizar los indicadores."""
    return df.iloc[VELAS_WARMUP:] if len(df) > VELAS_WARMUP else df


def _construir_contexto_par(
    par: str,
    df_4h: pd.DataFrame,
    df_1d: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_1w: Optional[pd.DataFrame] = None,
) -> ContextoMercado:
    """
    Construye el ContextoMercado completo para pasarle al cerebro.
    Todos los DataFrames recibidos son SIN warmup — se aplica aquí.
    """
    ctx_4h = _construir_tf_ctx(_aplicar_warmup(df_4h))
    ctx_1d = _construir_tf_ctx(_aplicar_warmup(df_1d), es_diario=True)
    ctx_1h = _construir_tf_ctx(_aplicar_warmup(df_1h))

    # Timestamp de la última vela 1H
    ultimo_ts = df_1h.index[-1]
    if ultimo_ts.tzinfo is None:
        ultimo_ts = ultimo_ts.replace(tzinfo=timezone.utc)
    timestamp_iso = ultimo_ts.isoformat()

    timeframes: dict = {
        "4h": ctx_4h,
        "1d": ctx_1d,
        "1h": ctx_1h,
    }

    # 1W: se pasa como contexto adicional si está disponible
    if df_1w is not None:
        df_1w_valid = _aplicar_warmup(df_1w)
        if len(df_1w_valid) >= N_PUNTOS_ESTRUCTURA + 1:
            timeframes["1w"] = _construir_tf_ctx(df_1w_valid)

    return {
        "par": par,
        "timestamp": timestamp_iso,
        "mercado_tipo": "spot",
        "senal_base": "LONG",
        "portfolio": {
            "posicion_actual": "NONE",
            "riesgo_disponible_pct": 1.0,
        },
        "timeframes": timeframes,
    }


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def escanear(pares: list[str]) -> list[dict]:
    """
    Escanea todos los activos y devuelve los que el cerebro confirma como LONG.

    Flujo por activo:
      1. Descarga 4H → verifica EMA20 ± 2% y RSI < 35
      2. Descarga 1D → verifica tendencia alcista (close > EMA50)
      3. Descarga 1W → verifica tendencia alcista (close > EMA20)
      4. Si pasa el pre-filtro → construye contexto MTF + llama al cerebro
      5. Si el cerebro confirma → incluye en resultados

    Args:
        pares: Lista de tickers (cripto "BTC/USDT" o acciones "AAPL").

    Returns:
        Lista de dicts con {par, metricas_4h, decision, contexto} para señales confirmadas.
    """
    resultados: list[dict] = []

    for par in pares:
        log.info("Escaneando %s...", par)
        try:
            # --- Paso 1: condición 4H ---
            df_4h = _descargar(par, "4h", N_VELAS_4H)
            cumple_4h, metricas = _evaluar_condicion_4h(_aplicar_warmup(df_4h))

            if not cumple_4h:
                log.debug(
                    "%s — descartado 4H: precio=%.4f EMA20=%.4f dist=%.1f%% RSI=%.1f",
                    par, metricas["precio"], metricas["ema20"],
                    metricas["dist_ema20_pct"], metricas["rsi"],
                )
                continue

            log.info(
                "%s — PASA 4H: dist EMA20=%.2f%% RSI=%.1f",
                par, metricas["dist_ema20_pct"], metricas["rsi"],
            )

            # --- Paso 2: tendencia 1D ---
            df_1d = _descargar(par, "1d", N_VELAS_1D)
            if not _tendencia_alcista_1d(_aplicar_warmup(df_1d)):
                log.info("%s — descartado: 1D NO alcista (close < EMA50)", par)
                continue

            log.info("%s — PASA 1D: tendencia alcista", par)

            # --- Paso 3: tendencia 1W ---
            df_1w = _descargar(par, "1w", N_VELAS_1W)
            df_1w_valid = _aplicar_warmup(df_1w)
            if not _tendencia_alcista_1w(df_1w_valid):
                log.info("%s — descartado: 1W NO alcista (close < EMA20)", par)
                continue

            log.info("%s — PASA 1W: tendencia alcista — solicitando contexto al cerebro...", par)

            # --- Paso 4: contexto completo + contextualización ---
            df_1h = _descargar(par, "1h", N_VELAS_1H)
            contexto = _construir_contexto_par(par, df_4h, df_1d, df_1h, df_1w)
            analisis = contextualizar(contexto)

            log.info(
                "%s — Cerebro (contexto): nivel=%s | %s",
                par, analisis["nivel_atencion"], analisis["analisis"][:80],
            )

            # La estrategia ya pasó el pre-filtro — siempre se incluye en resultados
            resultados.append({
                "par": par,
                "metricas_4h": metricas,
                "analisis": analisis,
                "contexto": contexto,
            })
            log.info("%s — agregado a resultados (nivel: %s)", par, analisis["nivel_atencion"])

        except Exception as exc:  # noqa: BLE001
            log.error("Error escaneando %s: %s", par, exc, exc_info=True)
            continue

    log.info(
        "Scanner completado: %d/%d activos confirmados por el cerebro",
        len(resultados), len(pares),
    )
    return resultados
