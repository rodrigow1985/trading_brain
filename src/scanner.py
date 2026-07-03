"""
Scanner 4H — Fase 4+.

Escanea múltiples activos (cripto + acciones) evaluando condiciones técnicas
en el timeframe 4H. Soporta cuatro estrategias configurables via .env:

  SCANNER_RSI_SOBREVENTA       — RSI < umbral          → alerta informativa (NONE)
  SCANNER_RSI_SOBRECOMPRA      — RSI > umbral          → alerta informativa (NONE)
  SCANNER_EMA20_TOQUE          — precio ± dist% EMA20  → alerta informativa (NONE)
  SCANNER_EMA20_RSI_SOBREVENTA — EMA20 toque + RSI sob → señal LONG (con filtro 1D/1W)

Alertas (senal_base=NONE): notifican siempre que la condición se cumpla en 4H,
sin filtro de tendencia. El cerebro analiza qué significa sin imponer dirección.

Señales (senal_base=LONG): requieren 1D y 1W alcistas. El cerebro contextualiza
con sesgo alcista.

Tipos de activos:
  - Cripto: "BTC/USDT" (ccxt/Binance)
  - Acciones: "AAPL" (yfinance/Yahoo Finance)

Restricciones:
  - NO importa anthropic directamente — usa brain.contextualizar()
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
# Configuración de estrategias
# ---------------------------------------------------------------------------

# Todas las estrategias disponibles (en orden de evaluación)
_TODAS_ESTRATEGIAS: list[str] = [
    "RSI_SOBREVENTA",
    "RSI_SOBRECOMPRA",
    "EMA20_TOQUE",
    "EMA20_RSI_SOBREVENTA",
]

# Señal base por estrategia:
#   NONE  → alerta informativa, sin filtro MTF, cerebro analiza sin dirección forzada
#   LONG  → señal con filtro 1D/1W alcistas, cerebro enfoca perspectiva alcista
_SENAL_BASE: dict[str, str] = {
    "RSI_SOBREVENTA":       "NONE",
    "RSI_SOBRECOMPRA":      "NONE",
    "EMA20_TOQUE":          "NONE",
    "EMA20_RSI_SOBREVENTA": "LONG",
}

# Timeframe de evaluación de cada estrategia
_ESTRATEGIA_TF: dict[str, str] = {
    "RSI_SOBREVENTA":       "4h",
    "RSI_SOBRECOMPRA":      "4h",
    "EMA20_TOQUE":          "1d",
    "EMA20_RSI_SOBREVENTA": "4h",
}

# ---------------------------------------------------------------------------
# Parámetros de indicadores
# ---------------------------------------------------------------------------

EMA20_PERIODO = 20
EMA50_PERIODO = 50
RSI_PERIODO   = 14

N_VELAS_4H  = 200
N_VELAS_1D  = 300
N_VELAS_1H  = 200
N_VELAS_1W  = 104
VELAS_WARMUP = 50

VENTANA_ESTRUCTURA  = 20
N_PUNTOS_ESTRUCTURA = 5


# ---------------------------------------------------------------------------
# Helpers de entorno
# ---------------------------------------------------------------------------

def _estrategias_activas() -> list[str]:
    """Lee las estrategias habilitadas en el entorno (SCANNER_<NOMBRE>=true)."""
    return [
        e for e in _TODAS_ESTRATEGIAS
        if os.environ.get(f"SCANNER_{e}", "false").lower() == "true"
    ]


def _umbral_rsi_sobreventa() -> float:
    return float(os.environ.get("SCANNER_RSI_SOBREVENTA_UMBRAL", "35"))


def _umbral_rsi_sobrecompra() -> float:
    return float(os.environ.get("SCANNER_RSI_SOBRECOMPRA_UMBRAL", "70"))


def _umbral_dist_ema20() -> float:
    return float(os.environ.get("SCANNER_EMA20_DISTANCIA_PCT", "2")) / 100


# ---------------------------------------------------------------------------
# Detección del tipo de activo
# ---------------------------------------------------------------------------

def _es_accion(par: str) -> bool:
    """Ticker sin '/' → acción (ej. AAPL). Con '/' → cripto (ej. BTC/USDT)."""
    return "/" not in par


# ---------------------------------------------------------------------------
# Indicadores (pandas puro)
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
    exchange = _crear_exchange()
    raw = exchange.fetch_ohlcv(par, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def _descargar_accion(ticker: str, timeframe: str, limit: int) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance no instalado. Ejecutar: pip install yfinance>=0.2.0")

    t = yf.Ticker(ticker)

    if timeframe in ("1h", "4h"):
        df_raw = t.history(period="2y", interval="1h", auto_adjust=True)
    elif timeframe == "1d":
        df_raw = t.history(period="5y", interval="1d", auto_adjust=True)
    elif timeframe == "1w":
        df_raw = t.history(period="5y", interval="1wk", auto_adjust=True)
    else:
        raise ValueError(f"Timeframe no soportado para acciones: {timeframe}")

    if df_raw.empty:
        raise ValueError(f"yfinance no devolvió datos para {ticker} ({timeframe})")

    df_raw.columns = [c.lower() for c in df_raw.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df_raw.columns]
    df = df_raw[cols].copy()

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    if timeframe == "4h":
        df = (
            df.resample("4h")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )

    return df


def _descargar(par: str, timeframe: str, limit: int) -> pd.DataFrame:
    if _es_accion(par):
        return _descargar_accion(par, timeframe, limit)
    return _descargar_crypto(par, timeframe, limit)


def _aplicar_warmup(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[VELAS_WARMUP:] if len(df) > VELAS_WARMUP else df


# ---------------------------------------------------------------------------
# Evaluación de condiciones por estrategia
# ---------------------------------------------------------------------------

def _evaluar_estrategia(df_valid: pd.DataFrame, estrategia_id: str) -> tuple[bool, dict]:
    """
    Evalúa si la última vela del df cumple la condición de la estrategia.

    Returns:
        (cumple, metricas) donde metricas incluye precio, rsi, ema20, dist_ema20_pct, vol_ratio.
    """
    close     = df_valid["close"]
    precio    = float(close.iloc[-1])
    rsi_val   = float(_rsi(close, RSI_PERIODO).iloc[-1])
    ema20_val = float(_ema(close, EMA20_PERIODO).iloc[-1])
    dist_pct  = (precio - ema20_val) / ema20_val

    vol_actual = float(df_valid["volume"].iloc[-1]) if "volume" in df_valid.columns else 0.0
    vol_prom_s = _sma(df_valid["volume"], 20) if "volume" in df_valid.columns else pd.Series([1.0])
    vol_prom   = float(vol_prom_s.iloc[-1]) if not vol_prom_s.empty else 1.0
    vol_ratio  = vol_actual / vol_prom if vol_prom > 0 else 1.0

    metricas = {
        "precio":         precio,
        "rsi":            rsi_val,
        "ema20":          ema20_val,
        "dist_ema20_pct": dist_pct * 100,
        "vol_ratio":      vol_ratio,
    }

    if estrategia_id == "RSI_SOBREVENTA":
        return rsi_val < _umbral_rsi_sobreventa(), metricas

    elif estrategia_id == "RSI_SOBRECOMPRA":
        return rsi_val > _umbral_rsi_sobrecompra(), metricas

    elif estrategia_id == "EMA20_TOQUE":
        return abs(dist_pct) <= _umbral_dist_ema20(), metricas

    elif estrategia_id == "EMA20_RSI_SOBREVENTA":
        cumple = abs(dist_pct) <= _umbral_dist_ema20() and rsi_val < _umbral_rsi_sobreventa()
        return cumple, metricas

    else:
        log.warning("Estrategia desconocida: %s", estrategia_id)
        return False, metricas


# ---------------------------------------------------------------------------
# Filtro de tendencia MTF
# ---------------------------------------------------------------------------

def _tendencia_alcista_1d(df: pd.DataFrame) -> bool:
    return float(df["close"].iloc[-1]) > float(_ema(df["close"], EMA50_PERIODO).iloc[-1])


def _tendencia_alcista_1w(df: pd.DataFrame) -> bool:
    return float(df["close"].iloc[-1]) > float(_ema(df["close"], EMA20_PERIODO).iloc[-1])


def _tendencia_bajista_1d(df: pd.DataFrame) -> bool:
    return float(df["close"].iloc[-1]) < float(_ema(df["close"], EMA50_PERIODO).iloc[-1])


def _tendencia_bajista_1w(df: pd.DataFrame) -> bool:
    return float(df["close"].iloc[-1]) < float(_ema(df["close"], EMA20_PERIODO).iloc[-1])


def _pasa_filtro_tendencia(df_1d: pd.DataFrame, df_1w: pd.DataFrame, senal: str) -> bool:
    """
    NONE → sin filtro (alerta siempre pasa)
    LONG → 1D alcista + 1W alcista
    SHORT → 1D bajista + 1W bajista
    """
    if senal == "LONG":
        return _tendencia_alcista_1d(df_1d) and _tendencia_alcista_1w(df_1w)
    if senal == "SHORT":
        return _tendencia_bajista_1d(df_1d) and _tendencia_bajista_1w(df_1w)
    return True  # NONE: alerta informativa, sin filtro MTF


# ---------------------------------------------------------------------------
# Construcción del contexto para el cerebro
# ---------------------------------------------------------------------------

def _construir_tf_ctx(df: pd.DataFrame, es_diario: bool = False) -> dict:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    rsi_s    = _rsi(close, RSI_PERIODO)
    ema21_s  = _ema(close, 21)
    ema50_s  = _ema(close, 50)
    atr_s    = _atr(high, low, close)
    vol_prom = _sma(volume, 20)

    indicadores: dict = {
        "rsi":              float(rsi_s.iloc[-1]),
        "ema_rapida":       float(ema21_s.iloc[-1]),
        "ema_lenta":        float(ema50_s.iloc[-1]),
        "ema_rapida_prev":  float(ema21_s.iloc[-2]),
        "ema_lenta_prev":   float(ema50_s.iloc[-2]),
        "atr":              max(float(atr_s.iloc[-1]), 1e-8),
        "volumen":          float(volume.iloc[-1]),
        "volumen_promedio": max(float(vol_prom.iloc[-1]), 1e-8),
    }

    if es_diario:
        indicadores["ema_largo"] = float(_ema(close, 200).iloc[-1])

    rolling_max = close.rolling(VENTANA_ESTRUCTURA).max()
    rolling_min = close.rolling(VENTANA_ESTRUCTURA).min()
    maximos = rolling_max.dropna().iloc[-N_PUNTOS_ESTRUCTURA:].tolist()
    minimos = rolling_min.dropna().iloc[-N_PUNTOS_ESTRUCTURA:].tolist()

    while len(maximos) < N_PUNTOS_ESTRUCTURA:
        maximos.insert(0, maximos[0] if maximos else float(close.iloc[0]))
    while len(minimos) < N_PUNTOS_ESTRUCTURA:
        minimos.insert(0, minimos[0] if minimos else float(close.iloc[0]))

    precio = float(close.iloc[-1])
    ema21  = indicadores["ema_rapida"]
    ema50  = indicadores["ema_lenta"]

    if precio > ema21 > ema50:
        tendencia = "alcista"
    elif precio < ema21 < ema50:
        tendencia = "bajista"
    else:
        tendencia = "lateral"

    return {
        "indicadores": indicadores,
        "estructura": {
            "precio_actual":    precio,
            "maximos_recientes": [float(v) for v in maximos[:N_PUNTOS_ESTRUCTURA]],
            "minimos_recientes": [float(v) for v in minimos[:N_PUNTOS_ESTRUCTURA]],
            "tendencia":        tendencia,
        },
    }


def _construir_contexto_par(
    par: str,
    df_4h: pd.DataFrame,
    df_1d: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_1w: Optional[pd.DataFrame] = None,
) -> ContextoMercado:
    ctx_4h = _construir_tf_ctx(_aplicar_warmup(df_4h))
    ctx_1d = _construir_tf_ctx(_aplicar_warmup(df_1d), es_diario=True)
    ctx_1h = _construir_tf_ctx(_aplicar_warmup(df_1h))

    ultimo_ts = df_1h.index[-1]
    if ultimo_ts.tzinfo is None:
        ultimo_ts = ultimo_ts.replace(tzinfo=timezone.utc)

    timeframes: dict = {"4h": ctx_4h, "1d": ctx_1d, "1h": ctx_1h}

    if df_1w is not None:
        df_1w_valid = _aplicar_warmup(df_1w)
        if len(df_1w_valid) >= N_PUNTOS_ESTRUCTURA + 1:
            timeframes["1w"] = _construir_tf_ctx(df_1w_valid)

    return {
        "par":         par,
        "timestamp":   ultimo_ts.isoformat(),
        "mercado_tipo": "spot",
        "senal_base":  "NONE",  # se sobreescribe en escanear()
        "portfolio": {
            "posicion_actual":      "NONE",
            "riesgo_disponible_pct": 1.0,
        },
        "timeframes": timeframes,
    }


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def escanear(pares: list[str]) -> list[dict]:
    """
    Escanea todos los activos con las estrategias habilitadas en .env.

    Flujo por activo:
      1. Descarga 4H → evalúa estrategias 4H (RSI_SOBREVENTA, RSI_SOBRECOMPRA, EMA20_RSI_SOBREVENTA)
      2. Descarga 1D → evalúa estrategias 1D (EMA20_TOQUE) + sirve para filtro MTF
      3. Descarga 1W y 1H solo si algo pasó
      4. Filtro MTF: alertas (NONE) siempre pasan; señales (LONG) requieren 1D + 1W alcistas
      5. Llama al cerebro (contextualizar) y agrega al resultado

    Returns:
        Lista de dicts: {par, estrategia, senal, timeframe, metricas, analisis}
    """
    activas = _estrategias_activas()
    if not activas:
        log.warning("No hay estrategias activas. Configurar SCANNER_* en .env")
        return []

    activas_4h = [e for e in activas if _ESTRATEGIA_TF[e] == "4h"]
    activas_1d = [e for e in activas if _ESTRATEGIA_TF[e] == "1d"]

    log.info("Estrategias activas: %s", ", ".join(activas))
    resultados: list[dict] = []

    for par in pares:
        log.info("Escaneando %s...", par)
        try:
            # --- Paso 1: 4H siempre (datos base + estrategias 4H) ---
            df_4h = _descargar(par, "4h", N_VELAS_4H)
            df_4h_valid = _aplicar_warmup(df_4h)

            pasaron: list[tuple[str, dict, str]] = []  # (estrategia, metricas, timeframe)

            for est in activas_4h:
                cumple, metricas = _evaluar_estrategia(df_4h_valid, est)
                if cumple:
                    log.info(
                        "%s — PASA 4H [%s]: rsi=%.1f dist_ema20=%.2f%%",
                        par, est, metricas["rsi"], metricas["dist_ema20_pct"],
                    )
                    pasaron.append((est, metricas, "4h"))
                else:
                    log.debug("%s — descartado 4H [%s]", par, est)

            # --- Paso 2: 1D (para estrategias 1D y/o filtro MTF de señales 4H) ---
            necesita_1d = bool(activas_1d) or bool(pasaron)
            if not necesita_1d:
                continue

            df_1d = _descargar(par, "1d", N_VELAS_1D)
            df_1d_valid = _aplicar_warmup(df_1d)

            for est in activas_1d:
                cumple, metricas = _evaluar_estrategia(df_1d_valid, est)
                if cumple:
                    log.info(
                        "%s — PASA 1D [%s]: rsi=%.1f dist_ema20=%.2f%%",
                        par, est, metricas["rsi"], metricas["dist_ema20_pct"],
                    )
                    pasaron.append((est, metricas, "1d"))
                else:
                    log.debug("%s — descartado 1D [%s]", par, est)

            if not pasaron:
                continue

            # --- Paso 3: 1W y 1H (solo si algo pasó) ---
            df_1w = _descargar(par, "1w", N_VELAS_1W)
            df_1h = _descargar(par, "1h", N_VELAS_1H)
            df_1w_valid = _aplicar_warmup(df_1w)

            # --- Paso 4: filtro MTF + contextualización ---
            for est, metricas, tf in pasaron:
                senal = _SENAL_BASE[est]

                if not _pasa_filtro_tendencia(df_1d_valid, df_1w_valid, senal):
                    log.info(
                        "%s — [%s] no pasa filtro tendencia MTF (senal=%s)", par, est, senal
                    )
                    continue

                log.info("%s — [%s] pasa MTF — contextualizando con cerebro...", par, est)

                contexto = _construir_contexto_par(par, df_4h, df_1d, df_1h, df_1w)
                contexto["senal_base"] = senal
                analisis = contextualizar(contexto)

                resultados.append({
                    "par":        par,
                    "estrategia": est,
                    "senal":      senal,
                    "timeframe":  tf,
                    "metricas":   metricas,
                    "analisis":   analisis,
                })
                log.info(
                    "%s — [%s] agregado (nivel=%s)", par, est, analisis["nivel_atencion"]
                )

        except Exception as exc:  # noqa: BLE001
            log.error("Error escaneando %s: %s", par, exc, exc_info=True)
            continue

    log.info(
        "Scanner completado: %d alertas/señales en %d activos", len(resultados), len(pares)
    )
    return resultados
