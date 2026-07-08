"""
Estrategias v1 — las 4 originales del scanner (snapshot git: `estrategias-v1`).

  RSI_SOBREVENTA        4H  alerta (NONE)
  RSI_SOBRECOMPRA       4H  alerta (NONE)
  EMA20_TOQUE           1D  alerta (NONE)
  EMA20_RSI_SOBREVENTA  4H  señal LONG (requiere filtro MTF 1D/1W alcista)

Se habilitan individualmente con SCANNER_<ID>=true en .env, igual que siempre.
La lógica de evaluación es idéntica a la versión previa al refactor.
"""

import logging
import os

import pandas as pd

from src.strategies.base import Estrategia
from src.strategies.indicadores import ema, rsi, sma

log = logging.getLogger(__name__)

EMA20_PERIODO = 20
RSI_PERIODO = 14


def _umbral_rsi_sobreventa() -> float:
    return float(os.environ.get("SCANNER_RSI_SOBREVENTA_UMBRAL", "35"))


def _umbral_rsi_sobrecompra() -> float:
    return float(os.environ.get("SCANNER_RSI_SOBRECOMPRA_UMBRAL", "70"))


def _umbral_dist_ema20() -> float:
    return float(os.environ.get("SCANNER_EMA20_DISTANCIA_PCT", "2")) / 100


def _metricas(df: pd.DataFrame) -> dict:
    """Métricas estándar de la última vela (mismo cálculo que la v1 original)."""
    close = df["close"]
    precio = float(close.iloc[-1])
    rsi_val = float(rsi(close, RSI_PERIODO).iloc[-1])
    ema20_val = float(ema(close, EMA20_PERIODO).iloc[-1])
    dist_pct = (precio - ema20_val) / ema20_val

    vol_actual = float(df["volume"].iloc[-1]) if "volume" in df.columns else 0.0
    vol_prom_s = sma(df["volume"], 20) if "volume" in df.columns else pd.Series([1.0])
    vol_prom = float(vol_prom_s.iloc[-1]) if not vol_prom_s.empty else 1.0
    vol_ratio = vol_actual / vol_prom if vol_prom > 0 else 1.0

    return {
        "precio":         precio,
        "rsi":            rsi_val,
        "ema20":          ema20_val,
        "dist_ema20_pct": dist_pct * 100,
        "vol_ratio":      vol_ratio,
        "detalle":        {},
    }


def _eval_rsi_sobreventa(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas(df)
    return m["rsi"] < _umbral_rsi_sobreventa(), m


def _eval_rsi_sobrecompra(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas(df)
    return m["rsi"] > _umbral_rsi_sobrecompra(), m


def _eval_ema20_toque(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas(df)
    return abs(m["dist_ema20_pct"] / 100) <= _umbral_dist_ema20(), m


def _eval_ema20_rsi_sobreventa(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas(df)
    cumple = (
        abs(m["dist_ema20_pct"] / 100) <= _umbral_dist_ema20()
        and m["rsi"] < _umbral_rsi_sobreventa()
    )
    return cumple, m


TODAS: list[Estrategia] = [
    Estrategia(
        id="RSI_SOBREVENTA", nombre="RSI sobreventa", timeframe="4h",
        senal_base="NONE", evaluar=_eval_rsi_sobreventa,
    ),
    Estrategia(
        id="RSI_SOBRECOMPRA", nombre="RSI sobrecompra", timeframe="4h",
        senal_base="NONE", evaluar=_eval_rsi_sobrecompra,
    ),
    Estrategia(
        id="EMA20_TOQUE", nombre="Toque EMA20", timeframe="1d",
        senal_base="NONE", evaluar=_eval_ema20_toque,
    ),
    Estrategia(
        id="EMA20_RSI_SOBREVENTA", nombre="EMA20 + RSI sobreventa", timeframe="4h",
        senal_base="LONG", evaluar=_eval_ema20_rsi_sobreventa,
    ),
]


def get_estrategias() -> list[Estrategia]:
    """Estrategias v1 habilitadas via SCANNER_<ID>=true."""
    activas = [
        e for e in TODAS
        if os.environ.get(f"SCANNER_{e.id}", "false").lower() == "true"
    ]
    if not activas:
        log.warning("v1: no hay estrategias activas. Configurar SCANNER_* en .env")
    return activas
