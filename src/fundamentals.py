"""
Contexto fundamental para el análisis Buffett — lógica determinística.

Baja de yfinance el precio actual y los estados financieros anuales de una
acción y arma el dict de contexto que consume brain.analizar_buffett().
El LLM solo razona sobre estos datos — nunca inventa un precio ni una métrica.

Restricciones:
  - NO importar anthropic/groq/google — este módulo es 100% datos.
  - Solo acciones (tickers Yahoo Finance). Cripto no aplica al marco Buffett.
"""

import logging
import math
from typing import Any, Optional

import pandas as pd

log = logging.getLogger(__name__)

MAX_ANIOS = 4
MAX_DESCRIPCION = 700


def _f(valor: Any) -> Optional[float]:
    """Convierte a float; None si falta o no es un número finito."""
    try:
        v = float(valor)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _fila(df: pd.DataFrame, *nombres: str) -> list[Optional[float]]:
    """
    Valores anuales de la primera fila que exista (nuevo → viejo, MAX_ANIOS).
    Los nombres de fila varían entre versiones de yfinance — se prueban alias.
    """
    if df is None or df.empty:
        return []
    for nombre in nombres:
        if nombre in df.index:
            return [_f(v) for v in df.loc[nombre].iloc[:MAX_ANIOS]]
    return []


def _pct(numerador: Optional[float], denominador: Optional[float]) -> Optional[float]:
    if numerador is None or not denominador:
        return None
    return round(numerador / denominador * 100, 1)


def _ratio_a_pct(ratio: Optional[float]) -> Optional[float]:
    """yfinance devuelve márgenes/ROE como ratio (0.71 = 71%)."""
    return round(ratio * 100, 1) if ratio is not None else None


def construir_contexto_fundamental(ticker: str) -> dict:
    """
    Arma el contexto fundamental de una acción para el análisis Buffett.

    Raises:
        ValueError: si el ticker no devuelve datos (inexistente o sin cobertura).
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance no instalado. Ejecutar: pip install yfinance>=0.2.0")

    t = yf.Ticker(ticker)
    advertencias: list[str] = []

    info: dict = {}
    try:
        info = t.info or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("%s — no se pudo leer info: %s", ticker, exc)

    precio = _f(info.get("currentPrice")) or _f(info.get("regularMarketPrice"))
    if precio is None:
        try:
            precio = _f(t.fast_info["last_price"])
        except Exception:  # noqa: BLE001
            precio = None
    if precio is None:
        raise ValueError(f"No se pudo obtener el precio actual de {ticker}")

    try:
        ingresos_df = t.income_stmt
    except Exception:  # noqa: BLE001
        ingresos_df = pd.DataFrame()
    try:
        cashflow_df = t.cashflow
    except Exception:  # noqa: BLE001
        cashflow_df = pd.DataFrame()
    try:
        balance_df = t.balance_sheet
    except Exception:  # noqa: BLE001
        balance_df = pd.DataFrame()

    if ingresos_df is None or ingresos_df.empty:
        advertencias.append("Sin estado de resultados anual — análisis limitado")
        ingresos_df = pd.DataFrame()

    anios = [str(c)[:4] for c in ingresos_df.columns[:MAX_ANIOS]] if not ingresos_df.empty else []

    ingresos    = _fila(ingresos_df, "Total Revenue", "Operating Revenue")
    bruto       = _fila(ingresos_df, "Gross Profit")
    operativo   = _fila(ingresos_df, "Operating Income", "Total Operating Income As Reported")
    neto        = _fila(ingresos_df, "Net Income", "Net Income Common Stockholders")
    eps         = _fila(ingresos_df, "Diluted EPS", "Basic EPS")
    dya         = _fila(cashflow_df, "Depreciation And Amortization",
                        "Depreciation Amortization Depletion")
    capex       = _fila(cashflow_df, "Capital Expenditure")
    fcf_hist    = _fila(cashflow_df, "Free Cash Flow")
    dividendos  = _fila(cashflow_df, "Cash Dividends Paid", "Common Stock Dividend Paid")
    recompras   = _fila(cashflow_df, "Repurchase Of Capital Stock")
    equity      = _fila(balance_df, "Stockholders Equity", "Common Stock Equity")
    deuda_total = _fila(balance_df, "Total Debt")

    def _en(lista: list, i: int) -> Optional[float]:
        return lista[i] if i < len(lista) else None

    historico: list[dict] = []
    for i, anio in enumerate(anios):
        ni, da, cx = _en(neto, i), _en(dya, i), _en(capex, i)
        # capex viene con signo negativo en yfinance; owner earnings = NI + D&A − |capex|
        owner = round(ni + da + cx, 0) if None not in (ni, da, cx) else None
        historico.append({
            "anio":                anio,
            "ingresos":            _en(ingresos, i),
            "margen_bruto_pct":    _pct(_en(bruto, i), _en(ingresos, i)),
            "margen_operativo_pct": _pct(_en(operativo, i), _en(ingresos, i)),
            "beneficio_neto":      ni,
            "eps_diluido":         _en(eps, i),
            "roe_pct":             _pct(ni, _en(equity, i)),
            "dya":                 da,
            "capex":               cx,
            "owner_earnings_aprox": owner,
            "dividendos_pagados":  _en(dividendos, i),
            "recompras_acciones":  _en(recompras, i),
        })

    if historico and historico[0]["owner_earnings_aprox"] is None:
        advertencias.append("Owner earnings incompletas (falta D&A o CapEx)")
    advertencias.append(
        "CapEx total (no se distingue mantenimiento vs. crecimiento) — "
        "owner earnings aproximadas por exceso de castigo"
    )

    descripcion = str(info.get("longBusinessSummary", ""))[:MAX_DESCRIPCION]

    return {
        "ticker":        ticker.upper(),
        "nombre":        info.get("longName") or ticker.upper(),
        "sector":        info.get("sector"),
        "industria":     info.get("industry"),
        "descripcion":   descripcion or None,
        "moneda":        info.get("currency", "USD"),
        "precio_actual": precio,
        "rango_52w": {
            "minimo": _f(info.get("fiftyTwoWeekLow")),
            "maximo": _f(info.get("fiftyTwoWeekHigh")),
        },
        "market_cap":          _f(info.get("marketCap")),
        "acciones_en_circulacion": _f(info.get("sharesOutstanding")),
        "per_trailing":        _f(info.get("trailingPE")),
        "per_forward":         _f(info.get("forwardPE")),
        "dividend_yield_pct":  _f(info.get("dividendYield")),
        "metricas_actuales": {
            "roe_pct":             _ratio_a_pct(_f(info.get("returnOnEquity"))),
            "margen_bruto_pct":    _ratio_a_pct(_f(info.get("grossMargins"))),
            "margen_operativo_pct": _ratio_a_pct(_f(info.get("operatingMargins"))),
            "margen_neto_pct":     _ratio_a_pct(_f(info.get("profitMargins"))),
            "deuda_sobre_equity":  _f(info.get("debtToEquity")),
            "free_cash_flow":      _f(info.get("freeCashflow")),
            "deuda_total":         _en(deuda_total, 0),
            "fcf_ultimo_anio":     _en(fcf_hist, 0),
        },
        "historico_anual": historico,
        "advertencias":    advertencias,
    }
