"""
Scanner 1D — Fase 4+.

Escanea múltiples activos (cripto + acciones) evaluando condiciones técnicas.
Las estrategias están versionadas en src/strategies/ y se eligen con
SCANNER_STRATEGY_SET en .env:

  v1 — 4 estrategias originales (RSI 4H, EMA20 1D; ver src/strategies/v1.py)
  v2 — screener de situaciones técnicas 1D (default; ver docs/estrategias_v2.md)

Flujo v2 por activo:
  1. Descarga 1D y descarta la vela en curso (solo velas CERRADAS)
  2. Evalúa las 10 situaciones — todas informativas (senal_base=NONE)
  3. Anti-duplicados: una situación ya alertada no se repite hasta resetearse
     (estado persistido en SQLite, ver src/scanner_state.py)
  4. Confluencia: 2+ situaciones simultáneas → alerta PRIORITARIA
  5. Un solo mensaje por ticker: cerebro (contextualizar) + chart 1D

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
from datetime import datetime, timezone
from typing import Optional

import ccxt
import pandas as pd

from src.brain import contextualizar
from src.charting import generar_chart_png
from src import scanner_state
from src.strategies import get_strategy_set
from src.strategies.base import Estrategia
from src.strategies.indicadores import atr as _atr
from src.strategies.indicadores import ema as _ema
from src.strategies.indicadores import rsi as _rsi
from src.strategies.indicadores import sma as _sma
from src.types import ContextoMercado

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parámetros de descarga
# ---------------------------------------------------------------------------

N_VELAS_4H  = 200
N_VELAS_1D  = 300
N_VELAS_1D_V2 = 400  # v2 necesita 250 ruedas (52w) + warmup + margen
N_VELAS_1H  = 200
N_VELAS_1W  = 104
VELAS_WARMUP = 50

VENTANA_ESTRUCTURA  = 20
N_PUNTOS_ESTRUCTURA = 5

EMA20_PERIODO = 20
EMA50_PERIODO = 50
RSI_PERIODO   = 14


# ---------------------------------------------------------------------------
# Detección del tipo de activo
# ---------------------------------------------------------------------------

def _es_accion(par: str) -> bool:
    """Ticker sin '/' → acción (ej. AAPL). Con '/' → cripto (ej. BTC/USDT)."""
    return "/" not in par


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


def _solo_velas_cerradas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Descarta la vela diaria en curso: una vela cuya fecha (UTC) es hoy o
    posterior todavía no cerró. Las estrategias v2 solo evalúan velas cerradas.
    """
    if df.empty:
        return df
    hoy = datetime.now(timezone.utc).date()
    if df.index[-1].date() >= hoy:
        return df.iloc[:-1]
    return df


# ---------------------------------------------------------------------------
# Filtro de tendencia MTF (solo señales LONG/SHORT de la v1)
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
# Flujo v1 — estrategias originales (idéntico al comportamiento pre-refactor)
# ---------------------------------------------------------------------------

def _escanear_v1(pares: list[str], estrategias: list[Estrategia]) -> list[dict]:
    activas_4h = [e for e in estrategias if e.timeframe == "4h"]
    activas_1d = [e for e in estrategias if e.timeframe == "1d"]

    resultados: list[dict] = []

    for par in pares:
        log.info("Escaneando %s...", par)
        try:
            # --- Paso 1: 4H siempre (datos base + estrategias 4H) ---
            df_4h = _descargar(par, "4h", N_VELAS_4H)
            df_4h_valid = _aplicar_warmup(df_4h)

            pasaron: list[tuple[Estrategia, dict]] = []

            for est in activas_4h:
                cumple, metricas = est.evaluar(df_4h_valid)
                if cumple:
                    log.info(
                        "%s — PASA 4H [%s]: rsi=%.1f dist_ema20=%.2f%%",
                        par, est.id, metricas["rsi"], metricas["dist_ema20_pct"],
                    )
                    pasaron.append((est, metricas))
                else:
                    log.debug("%s — descartado 4H [%s]", par, est.id)

            # --- Paso 2: 1D (para estrategias 1D y/o filtro MTF de señales 4H) ---
            necesita_1d = bool(activas_1d) or bool(pasaron)
            if not necesita_1d:
                continue

            df_1d = _descargar(par, "1d", N_VELAS_1D)
            df_1d_valid = _aplicar_warmup(df_1d)

            for est in activas_1d:
                cumple, metricas = est.evaluar(df_1d_valid)
                if cumple:
                    log.info(
                        "%s — PASA 1D [%s]: rsi=%.1f dist_ema20=%.2f%%",
                        par, est.id, metricas["rsi"], metricas["dist_ema20_pct"],
                    )
                    pasaron.append((est, metricas))
                else:
                    log.debug("%s — descartado 1D [%s]", par, est.id)

            if not pasaron:
                continue

            # --- Paso 3: 1W y 1H (solo si algo pasó) ---
            df_1w = _descargar(par, "1w", N_VELAS_1W)
            df_1h = _descargar(par, "1h", N_VELAS_1H)
            df_1w_valid = _aplicar_warmup(df_1w)

            # --- Paso 4: filtro MTF + contextualización ---
            for est, metricas in pasaron:
                senal = est.senal_base

                if not _pasa_filtro_tendencia(df_1d_valid, df_1w_valid, senal):
                    log.info(
                        "%s — [%s] no pasa filtro tendencia MTF (senal=%s)", par, est.id, senal
                    )
                    continue

                log.info("%s — [%s] pasa MTF — contextualizando con cerebro...", par, est.id)

                contexto = _construir_contexto_par(par, df_4h, df_1d, df_1h, df_1w)
                contexto["senal_base"] = senal
                analisis = contextualizar(contexto)

                # Chart: usa el df del timeframe de la estrategia
                df_chart = df_1d if est.timeframe == "1d" else df_4h
                chart_png: "bytes | None" = None
                try:
                    chart_png = generar_chart_png(df_chart, par, est.timeframe)
                except Exception as exc_chart:
                    log.warning("%s — [%s] no se pudo generar chart: %s", par, est.id, exc_chart)

                resultados.append({
                    "par":          par,
                    "strategy_set": "v1",
                    "estrategia":   est.id,
                    "senal":        senal,
                    "timeframe":    est.timeframe,
                    "metricas":     metricas,
                    "analisis":     analisis,
                    "chart_png":    chart_png,
                })
                log.info(
                    "%s — [%s] agregado (nivel=%s)", par, est.id, analisis["nivel_atencion"]
                )

        except Exception as exc:  # noqa: BLE001
            log.error("Error escaneando %s: %s", par, exc, exc_info=True)
            continue

    return resultados


# ---------------------------------------------------------------------------
# Flujo v2 — screener de situaciones técnicas 1D
# ---------------------------------------------------------------------------

def _escanear_v2(pares: list[str], estrategias: list[Estrategia]) -> list[dict]:
    db_path = os.environ.get("DB_PATH", "trading_brain.db")
    scanner_state.init(db_path)

    resultados: list[dict] = []

    for par in pares:
        log.info("Escaneando %s...", par)
        try:
            aplicables = [
                e for e in estrategias if not (e.solo_acciones and not _es_accion(par))
            ]
            if not aplicables:
                continue

            # --- Paso 1: 1D, solo velas cerradas ---
            df_1d = _solo_velas_cerradas(_descargar(par, "1d", N_VELAS_1D_V2))
            df_valid = _aplicar_warmup(df_1d)
            if df_valid.empty:
                log.warning("%s — sin velas cerradas suficientes", par)
                continue

            # --- Paso 2: evaluar situaciones ---
            disparadas: list[tuple[Estrategia, dict]] = []
            for est in aplicables:
                cumple, metricas = est.evaluar(df_valid)
                if cumple:
                    log.info("%s — CUMPLE [%s]: %s", par, est.id, metricas.get("detalle"))
                    disparadas.append((est, metricas))

            ids_disparadas = {e.id for e, _ in disparadas}

            # --- Paso 3: anti-duplicados (no re-alertar situaciones activas) ---
            nuevas = [
                (e, m) for e, m in disparadas
                if not scanner_state.estaba_activa(db_path, par, e.id)
            ]
            ids_nuevas = {e.id for e, _ in nuevas}

            for est in aplicables:
                scanner_state.actualizar(
                    db_path, par, est.id,
                    activa=est.id in ids_disparadas,
                    alerto=est.id in ids_nuevas,
                )

            if not nuevas:
                if disparadas:
                    log.info(
                        "%s — %d situación(es) siguen activas, ya alertadas: %s",
                        par, len(disparadas), ", ".join(sorted(ids_disparadas)),
                    )
                continue

            # --- Paso 4: confluencia ---
            prioritaria = len(disparadas) >= 2
            activas_previas = [
                e.nombre for e, _ in disparadas if e.id not in ids_nuevas
            ]

            # --- Paso 5: contexto MTF + cerebro (una sola llamada por ticker) ---
            df_4h = _descargar(par, "4h", N_VELAS_4H)
            df_1h = _descargar(par, "1h", N_VELAS_1H)
            df_1w = _descargar(par, "1w", N_VELAS_1W)

            contexto = _construir_contexto_par(par, df_4h, df_1d, df_1h, df_1w)
            contexto["senal_base"] = "NONE"
            contexto["situaciones_detectadas"] = [
                {"id": e.id, "nombre": e.nombre, "detalle": m.get("detalle", {})}
                for e, m in disparadas
            ]
            analisis = contextualizar(contexto)

            chart_png: "bytes | None" = None
            try:
                chart_png = generar_chart_png(df_1d, par, "1d")
            except Exception as exc_chart:
                log.warning("%s — no se pudo generar chart: %s", par, exc_chart)

            resultados.append({
                "par":             par,
                "strategy_set":    "v2",
                "senal":           "NONE",
                "timeframe":       "1d",
                "fecha_vela":      df_valid.index[-1].date().isoformat(),
                "prioritaria":     prioritaria,
                "situaciones": [
                    {
                        "id":      e.id,
                        "nombre":  e.nombre,
                        "detalle": m.get("detalle", {}),
                    }
                    for e, m in nuevas
                ],
                "activas_previas": activas_previas,
                "metricas":        nuevas[0][1],  # contexto de indicadores del ticker
                "analisis":        analisis,
                "chart_png":       chart_png,
            })
            log.info(
                "%s — %d situación(es) nueva(s)%s (nivel=%s)",
                par, len(nuevas),
                " [PRIORITARIA]" if prioritaria else "",
                analisis["nivel_atencion"],
            )

        except Exception as exc:  # noqa: BLE001
            log.error("Error escaneando %s: %s", par, exc, exc_info=True)
            continue

    return resultados


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

def escanear(pares: list[str]) -> list[dict]:
    """
    Escanea todos los activos con el set de estrategias activo
    (SCANNER_STRATEGY_SET en .env: "v1" | "v2").

    Returns:
        v1 → lista de dicts {par, strategy_set, estrategia, senal, timeframe,
             metricas, analisis, chart_png}
        v2 → lista de dicts {par, strategy_set, senal, timeframe, fecha_vela,
             prioritaria, situaciones, activas_previas, metricas, analisis,
             chart_png} — un dict por ticker con situaciones nuevas.
    """
    from src.strategies import get_estrategias

    version = get_strategy_set()
    estrategias = get_estrategias()
    if not estrategias:
        log.warning("No hay estrategias activas (set=%s).", version)
        return []

    log.info(
        "Set de estrategias: %s — activas: %s",
        version, ", ".join(e.id for e in estrategias),
    )

    if version == "v1":
        resultados = _escanear_v1(pares, estrategias)
    else:
        resultados = _escanear_v2(pares, estrategias)

    log.info(
        "Scanner completado (%s): %d alertas en %d activos",
        version, len(resultados), len(pares),
    )
    return resultados
