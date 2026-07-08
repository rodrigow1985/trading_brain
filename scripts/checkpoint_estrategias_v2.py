"""
Checkpoint estrategias v2 — valida cada situación con velas sintéticas.

Construye DataFrames OHLCV diseñados para disparar (y no disparar) cada una
de las 10 situaciones, sin red ni LLM. Además prueba el anti-duplicados
(scanner_state) con una DB temporal.

Uso:
    python scripts/checkpoint_estrategias_v2.py           # solo sintético
    python scripts/checkpoint_estrategias_v2.py --real    # + BTC/USDT y AAPL reales
"""

import argparse
import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategies import v2
from src.strategies.indicadores import ema

N = 400
FALLOS: list[str] = []


def _df_base(n: int = N, precio: float = 100.0, vol: float = 1000.0) -> pd.DataFrame:
    """Velas planas: open=high=low=close=precio, volumen constante."""
    idx = pd.date_range(end="2026-07-05", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open":   [precio] * n,
        "high":   [precio] * n,
        "low":    [precio] * n,
        "close":  [precio] * n,
        "volume": [vol] * n,
    }, index=idx)


def _check(nombre: str, cumple: bool, esperado: bool, detalle: dict) -> None:
    ok = cumple == esperado
    estado = "OK  " if ok else "FAIL"
    print(f"  [{estado}] {nombre}: cumple={cumple} esperado={esperado} {detalle if cumple else ''}")
    if not ok:
        FALLOS.append(nombre)


# ---------------------------------------------------------------------------
# Casos por situación
# ---------------------------------------------------------------------------

def caso_sit1() -> None:
    print("SIT1 — Toque de EMA20")
    df = _df_base()
    # 10 velas a 110 (precio alejado >2% de la EMA) y toque en la última
    df.iloc[-11:, df.columns.get_loc("close")] = 110.0
    df.iloc[-11:, df.columns.get_loc("open")] = 110.0
    df.iloc[-11:, df.columns.get_loc("high")] = 110.5
    df.iloc[-11:, df.columns.get_loc("low")] = 109.5
    ema20_prev = float(ema(df["close"], 20).iloc[-1])
    df.iloc[-1, df.columns.get_loc("low")] = ema20_prev * 0.999  # toca la EMA
    df.iloc[-1, df.columns.get_loc("close")] = 108.0
    cumple, m = v2._sit1_toque_ema20(df)
    _check("toque tras alejamiento", cumple, True, m["detalle"])

    # Contraejemplo: precio pegado a la EMA hace días → no alerta
    df2 = _df_base()
    cumple2, m2 = v2._sit1_toque_ema20(df2)
    _check("pegado a la EMA no alerta", cumple2, False, m2["detalle"])


def caso_sit2() -> None:
    print("SIT2 — Cruce confirmado de EMA20")
    df = _df_base()
    df.iloc[-3, df.columns.get_loc("close")] = 99.0    # abajo de la EMA
    df.iloc[-2, df.columns.get_loc("close")] = 102.0   # 2 cierres arriba
    df.iloc[-1, df.columns.get_loc("close")] = 103.0
    df.iloc[-2:, df.columns.get_loc("volume")] = 2000.0  # cruce con volumen
    cumple, m = v2._sit2_cruce_ema20(df)
    _check("cruce alcista 2 cierres", cumple, True, m["detalle"])
    if cumple and not m["detalle"]["con_volumen"]:
        FALLOS.append("SIT2 con_volumen")
        print("  [FAIL] con_volumen debería ser True")

    # Un solo cierre arriba → no confirma
    df2 = _df_base()
    df2.iloc[-2, df2.columns.get_loc("close")] = 99.0
    df2.iloc[-1, df2.columns.get_loc("close")] = 103.0
    cumple2, m2 = v2._sit2_cruce_ema20(df2)
    _check("1 solo cierre no confirma", cumple2, False, m2["detalle"])


def caso_sit3() -> None:
    print("SIT3 — RSI sobrecompra tras subida")
    df = _df_base()
    # Subida sostenida del 0.7% diario en las últimas 60 ruedas
    closes = df["close"].to_numpy().copy()
    for i in range(N - 60, N):
        closes[i] = closes[i - 1] * 1.007
    df["close"] = closes
    df["open"] = df["close"]
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    cumple, m = v2._sit3_rsi_sobrecompra(df)
    _check("subida sostenida + RSI alto", cumple, True, m["detalle"])

    cumple2, m2 = v2._sit3_rsi_sobrecompra(_df_base())
    _check("plano no alerta", cumple2, False, m2["detalle"])


def caso_sit4() -> None:
    print("SIT4 — RSI sobreventa tras caída")
    df = _df_base()
    closes = df["close"].to_numpy().copy()
    for i in range(N - 60, N):
        closes[i] = closes[i - 1] * 0.993
    df["close"] = closes
    df["open"] = df["close"]
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    cumple, m = v2._sit4_rsi_sobreventa(df)
    _check("caída sostenida + RSI bajo", cumple, True, m["detalle"])


def caso_sit5() -> None:
    print("SIT5 — Divergencia RSI/precio")
    df = _df_base(precio=80.0)
    closes = df["close"].to_numpy().copy()
    # Rally fuerte hacia el pivote 1 (RSI alto)
    for i in range(N - 26, N - 16):
        closes[i] = closes[i - 1] * 1.035
    # Retroceso
    for i in range(N - 16, N - 11):
        closes[i] = closes[i - 1] * 0.97
    # Subida lenta hacia el pivote 2: precio más alto, RSI más bajo
    objetivo = closes[N - 17] * 1.02
    paso = (objetivo / closes[N - 12]) ** (1 / 9)
    for i in range(N - 11, N - 2):
        closes[i] = closes[i - 1] * paso
    # Las 2 velas de confirmación del pivote 2 caen
    closes[N - 2] = closes[N - 3] * 0.97
    closes[N - 1] = closes[N - 2] * 0.98
    df["close"] = closes
    df["open"] = df["close"]
    df["high"] = df["close"] * 1.002
    df["low"] = df["close"] * 0.998
    cumple, m = v2._sit5_divergencia_rsi(df)
    _check("divergencia bajista", cumple, True, m["detalle"])


def caso_sit6() -> None:
    print("SIT6 — Vela de rechazo en EMA20")
    df = _df_base()
    # Pin bar alcista: mecha inferior larga que toca la EMA (≈100)
    df.iloc[-1, df.columns.get_loc("open")] = 100.5
    df.iloc[-1, df.columns.get_loc("low")] = 99.4
    df.iloc[-1, df.columns.get_loc("high")] = 100.9
    df.iloc[-1, df.columns.get_loc("close")] = 100.8
    cumple, m = v2._sit6_rechazo_ema20(df)
    _check("pin bar alcista en EMA20", cumple, True, m["detalle"])


def caso_sit7() -> None:
    print("SIT7 — Pico de volumen anómalo")
    df = _df_base()
    df.iloc[-1, df.columns.get_loc("volume")] = 5000.0  # 5× el promedio
    cumple, m = v2._sit7_pico_volumen(df)
    _check("volumen 5x", cumple, True, m["detalle"])

    cumple2, m2 = v2._sit7_pico_volumen(_df_base())
    _check("volumen normal no alerta", cumple2, False, m2["detalle"])


def caso_sit8() -> None:
    print("SIT8 — Squeeze de Bollinger")
    df = _df_base()
    rng = np.random.default_rng(42)
    closes = df["close"].to_numpy().copy()
    # Alta volatilidad histórica, compresión en los últimos 25 días
    for i in range(N - 90, N - 25):
        closes[i] = 100 + 8 * np.sin(i / 3) + rng.normal(0, 2)
    for i in range(N - 25, N):
        closes[i] = closes[N - 26] + rng.normal(0, 0.2)
    df["close"] = closes
    df["open"] = df["close"]
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    cumple, m = v2._sit8_squeeze_bollinger(df)
    _check("compresión tras volatilidad", cumple, True, m["detalle"])


def caso_sit9() -> None:
    print("SIT9 — Máximo/mínimo de 52 semanas")
    df = _df_base()
    closes = np.linspace(100, 150, N)  # sube todo el período → cierre = máximo
    df["close"] = closes
    df["open"] = df["close"]
    df["high"] = df["close"] * 1.001
    df["low"] = df["close"] * 0.999
    cumple, m = v2._sit9_extremo_52w(df)
    _check("máximo de 250 ruedas", cumple, True, m["detalle"])

    cumple2, m2 = v2._sit9_extremo_52w(_df_base())
    _check("plano no es extremo", cumple2, False, m2["detalle"])


def caso_sit10() -> None:
    print("SIT10 — Gap de apertura")
    df = _df_base()
    df.iloc[-1, df.columns.get_loc("open")] = 110.0   # gap up del 10%
    df.iloc[-1, df.columns.get_loc("high")] = 111.0
    df.iloc[-1, df.columns.get_loc("close")] = 108.0  # cerrándose
    cumple, m = v2._sit10_gap(df)
    _check("gap up 10%", cumple, True, m["detalle"])

    cumple2, m2 = v2._sit10_gap(_df_base())
    _check("sin gap no alerta", cumple2, False, m2["detalle"])


def caso_anti_duplicados() -> None:
    print("Anti-duplicados (scanner_state)")
    from src import scanner_state

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        scanner_state.init(db_path)
        assert not scanner_state.estaba_activa(db_path, "TEST", "SIT1")
        scanner_state.actualizar(db_path, "TEST", "SIT1", activa=True, alerto=True)
        assert scanner_state.estaba_activa(db_path, "TEST", "SIT1"), "debería estar activa"
        scanner_state.actualizar(db_path, "TEST", "SIT1", activa=False)
        assert not scanner_state.estaba_activa(db_path, "TEST", "SIT1"), "debería resetearse"
        scanner_state.actualizar(db_path, "TEST", "SIT1", activa=True, alerto=True)
        assert scanner_state.estaba_activa(db_path, "TEST", "SIT1")
        print("  [OK  ] alerta -> activa -> reset -> re-alerta")
    except AssertionError as exc:
        FALLOS.append(f"scanner_state: {exc}")
        print(f"  [FAIL] {exc}")
    finally:
        os.remove(db_path)


def caso_real(pares: list[str]) -> None:
    """Evalúa las 10 situaciones sobre datos reales, sin LLM ni Telegram."""
    from src.scanner import _aplicar_warmup, _descargar, _es_accion, _solo_velas_cerradas

    for par in pares:
        print(f"\nDatos reales — {par}")
        df = _solo_velas_cerradas(_descargar(par, "1d", 400))
        df_valid = _aplicar_warmup(df)
        print(f"  velas cerradas: {len(df_valid)} (última: {df_valid.index[-1].date()})")
        for est in v2.TODAS:
            if est.solo_acciones and not _es_accion(par):
                continue
            cumple, m = est.evaluar(df_valid)
            marca = "→ CUMPLE" if cumple else ""
            print(f"  {est.id:24s} {marca} {m['detalle'] if cumple else ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="además evalúa BTC/USDT y AAPL reales")
    args = parser.parse_args()

    for caso in (caso_sit1, caso_sit2, caso_sit3, caso_sit4, caso_sit5,
                 caso_sit6, caso_sit7, caso_sit8, caso_sit9, caso_sit10,
                 caso_anti_duplicados):
        caso()
        print()

    if args.real:
        caso_real(["BTC/USDT", "AAPL"])

    if FALLOS:
        print(f"\n{len(FALLOS)} caso(s) fallaron: {FALLOS}")
        sys.exit(1)
    print("\nTodos los casos sintéticos pasaron.")
