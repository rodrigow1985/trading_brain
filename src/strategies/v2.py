"""
Estrategias v2 — Screener de Situaciones Técnicas (Daily).

Detecta SITUACIONES técnicas en timeframe diario y alerta para análisis manual.
No genera señales long/short: todas las situaciones son informativas
(senal_base=NONE). Spec completa en docs/estrategias_v2.md.

  SIT1  Toque de EMA20 (con precio previamente alejado)
  SIT2  Cruce confirmado de EMA20 (2 cierres)
  SIT3  RSI sobrecompra tras tendencia alcista
  SIT4  RSI sobreventa tras tendencia bajista
  SIT5  Divergencia RSI/precio (pivotes)
  SIT6  Vela de rechazo en la EMA20 (pin bar)
  SIT7  Pico de volumen anómalo
  SIT8  Compresión de volatilidad (squeeze de Bollinger)
  SIT9  Máximo/mínimo de 52 semanas (250 ruedas)
  SIT10 Gap significativo en la apertura (solo acciones)

Todas las condiciones se evalúan sobre velas CERRADAS — el scanner descarta
la vela en curso antes de llamar a evaluar(). Por defecto están todas
habilitadas; SCANNER_V2_SITUACIONES="1,2,5" restringe a un subconjunto.
"""

import logging
import os

import pandas as pd

from src.strategies.base import Estrategia
from src.strategies.indicadores import bollinger_ancho, ema, rsi, sma

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parámetros globales (spec) — overrideables por entorno
# ---------------------------------------------------------------------------

EMA_PERIODO = 20
RSI_PERIODO = 14
VOL_PROM_PERIODO = 20

VENTANA_DIVERGENCIA = 30   # ruedas hacia atrás para buscar pivotes (SIT5)
PIVOTE_CONFIRMACION = 2    # velas a cada lado que confirman un pivote (SIT5)
TENDENCIA_RUEDAS = 20      # ventana del contexto de tendencia (SIT3/SIT4)
BB_VENTANA = 90            # días de historia del ancho de Bollinger (SIT8)
BB_PERCENTIL = 0.20        # el ancho actual debe estar en el 20% más bajo (SIT8)
EXTREMO_RUEDAS = 250       # máximo/mínimo de 52 semanas (SIT9)


def _tolerancia_ema() -> float:
    """Distancia máxima para considerar 'toque' de la EMA20 (0.5% default)."""
    return float(os.environ.get("SCANNER_V2_TOLERANCIA_EMA_PCT", "0.5")) / 100


def _dist_alejado() -> float:
    """Distancia mínima previa a la EMA20 para que un toque sea alertable (2%)."""
    return float(os.environ.get("SCANNER_V2_ALEJADO_PCT", "2")) / 100


def _rsi_sobrecompra() -> float:
    return float(os.environ.get("SCANNER_V2_RSI_SOBRECOMPRA", "70"))


def _rsi_sobreventa() -> float:
    return float(os.environ.get("SCANNER_V2_RSI_SOBREVENTA", "30"))


def _umbral_tendencia() -> float:
    """Variación mínima en 20 ruedas para confirmar tendencia (8% default)."""
    return float(os.environ.get("SCANNER_V2_TENDENCIA_PCT", "8")) / 100


def _vol_spike_ratio() -> float:
    return float(os.environ.get("SCANNER_V2_VOL_SPIKE_RATIO", "2.5"))


def _gap_pct() -> float:
    return float(os.environ.get("SCANNER_V2_GAP_PCT", "2")) / 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vol_promedio_previo(df: pd.DataFrame) -> float:
    """SMA(20) del volumen EXCLUYENDO la última vela (para no diluir picos)."""
    if "volume" not in df.columns or len(df) < VOL_PROM_PERIODO + 1:
        return 0.0
    val = float(sma(df["volume"].shift(1), VOL_PROM_PERIODO).iloc[-1])
    return val if pd.notna(val) else 0.0


def _metricas_base(df: pd.DataFrame) -> dict:
    """Métricas estándar de la última vela cerrada (contexto de toda alerta)."""
    close = df["close"]
    precio = float(close.iloc[-1])
    rsi_val = float(rsi(close, RSI_PERIODO).iloc[-1])
    ema20_val = float(ema(close, EMA_PERIODO).iloc[-1])
    dist_pct = (precio - ema20_val) / ema20_val

    vol_prom = _vol_promedio_previo(df)
    vol_actual = float(df["volume"].iloc[-1]) if "volume" in df.columns else 0.0
    vol_ratio = vol_actual / vol_prom if vol_prom > 0 else 1.0

    return {
        "precio":         precio,
        "rsi":            rsi_val,
        "ema20":          ema20_val,
        "dist_ema20_pct": dist_pct * 100,
        "vol_ratio":      vol_ratio,
        "detalle":        {},
    }


def _toco_ema(low: float, high: float, ema_val: float, tol: float) -> bool:
    """La vela tocó o cruzó la banda EMA ± tolerancia."""
    return low <= ema_val * (1 + tol) and high >= ema_val * (1 - tol)


def _pivotes(serie: pd.Series, tipo: str, desde: int) -> list[int]:
    """
    Índices posicionales de pivotes confirmados (2 velas a cada lado).

    tipo: "max" → el valor supera estrictamente a los 2 vecinos de cada lado.
          "min" → el valor es estrictamente menor a los 2 vecinos de cada lado.
    """
    n = len(serie)
    vals = serie.to_numpy()
    out: list[int] = []
    for i in range(max(PIVOTE_CONFIRMACION, desde), n - PIVOTE_CONFIRMACION):
        vecinos = [vals[i - 2], vals[i - 1], vals[i + 1], vals[i + 2]]
        if tipo == "max" and all(vals[i] > v for v in vecinos):
            out.append(i)
        elif tipo == "min" and all(vals[i] < v for v in vecinos):
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# SIT1 — Toque de EMA20
# ---------------------------------------------------------------------------

def _sit1_toque_ema20(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    n = len(df)
    if n < EMA_PERIODO + 8:
        return False, m

    ema20_s = ema(df["close"], EMA_PERIODO)
    tol = _tolerancia_ema()
    alejado = _dist_alejado()

    # Toque en alguna de las últimas 2 velas cerradas
    for idx in (n - 1, n - 2):
        if idx - 5 < 0:
            continue
        e = float(ema20_s.iloc[idx])
        if not _toco_ema(float(df["low"].iloc[idx]), float(df["high"].iloc[idx]), e, tol):
            continue

        # Las 5 velas anteriores al toque estuvieron alejadas > 2% de su EMA20
        dists = [
            (float(df["close"].iloc[j]) - float(ema20_s.iloc[j])) / float(ema20_s.iloc[j])
            for j in range(idx - 5, idx)
        ]
        if not all(abs(d) > alejado for d in dists):
            continue

        desde_arriba = sum(dists) > 0
        m["detalle"] = {
            "direccion": "desde arriba (posible soporte)" if desde_arriba
                         else "desde abajo (posible resistencia)",
            "dist_actual_pct": m["dist_ema20_pct"],
        }
        return True, m

    return False, m


# ---------------------------------------------------------------------------
# SIT2 — Cruce confirmado de EMA20 (2 cierres)
# ---------------------------------------------------------------------------

def _sit2_cruce_ema20(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if len(df) < EMA_PERIODO + 3:
        return False, m

    close = df["close"]
    ema20_s = ema(close, EMA_PERIODO)

    c3, c2, c1 = (float(close.iloc[i]) for i in (-3, -2, -1))
    e3, e2, e1 = (float(ema20_s.iloc[i]) for i in (-3, -2, -1))

    alcista = c3 < e3 and c2 > e2 and c1 > e1
    bajista = c3 > e3 and c2 < e2 and c1 < e1
    if not (alcista or bajista):
        return False, m

    vol_prom = _vol_promedio_previo(df)
    vol_conf = float(df["volume"].iloc[-2:].mean()) if "volume" in df.columns else 0.0
    con_volumen = vol_prom > 0 and vol_conf > vol_prom

    m["detalle"] = {
        "direccion": "alcista (cierra arriba de EMA20)" if alcista
                     else "bajista (cierra abajo de EMA20)",
        "dist_cierre_pct": m["dist_ema20_pct"],
        "con_volumen": con_volumen,
    }
    return True, m


# ---------------------------------------------------------------------------
# SIT3 / SIT4 — RSI extremo tras tendencia
# ---------------------------------------------------------------------------

def _velas_consecutivas(rsi_s: pd.Series, umbral: float, sobre: bool) -> int:
    count = 0
    for val in reversed(rsi_s.to_numpy()):
        if (sobre and val >= umbral) or (not sobre and val <= umbral):
            count += 1
        else:
            break
    return count


def _sit3_rsi_sobrecompra(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if len(df) < TENDENCIA_RUEDAS + 1:
        return False, m

    close = df["close"]
    rsi_s = rsi(close, RSI_PERIODO)
    umbral = _rsi_sobrecompra()
    var_20r = float(close.iloc[-1]) / float(close.iloc[-(TENDENCIA_RUEDAS + 1)]) - 1

    if not (float(rsi_s.iloc[-1]) >= umbral and var_20r >= _umbral_tendencia()):
        return False, m

    m["detalle"] = {
        "rsi": float(rsi_s.iloc[-1]),
        "suba_20_ruedas_pct": var_20r * 100,
        "velas_consecutivas_sobrecompra": _velas_consecutivas(rsi_s, umbral, sobre=True),
    }
    return True, m


def _sit4_rsi_sobreventa(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if len(df) < TENDENCIA_RUEDAS + 1:
        return False, m

    close = df["close"]
    rsi_s = rsi(close, RSI_PERIODO)
    umbral = _rsi_sobreventa()
    var_20r = float(close.iloc[-1]) / float(close.iloc[-(TENDENCIA_RUEDAS + 1)]) - 1

    if not (float(rsi_s.iloc[-1]) <= umbral and var_20r <= -_umbral_tendencia()):
        return False, m

    m["detalle"] = {
        "rsi": float(rsi_s.iloc[-1]),
        "caida_20_ruedas_pct": var_20r * 100,
        "velas_consecutivas_sobreventa": _velas_consecutivas(rsi_s, umbral, sobre=False),
    }
    return True, m


# ---------------------------------------------------------------------------
# SIT5 — Divergencia RSI/precio
# ---------------------------------------------------------------------------

def _sit5_divergencia_rsi(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    n = len(df)
    if n < VENTANA_DIVERGENCIA + RSI_PERIODO:
        return False, m

    rsi_s = rsi(df["close"], RSI_PERIODO)
    desde = n - VENTANA_DIVERGENCIA

    # El pivote más reciente debe estar recién confirmado (sus 2 velas de
    # confirmación son las últimas 2 cerradas) para que la alerta sea oportuna.
    minimo_reciente = n - PIVOTE_CONFIRMACION - 2

    # Divergencia bajista: máximo más alto en precio, más bajo en RSI
    piv_max = _pivotes(df["high"], "max", desde)
    if len(piv_max) >= 2 and piv_max[-1] >= minimo_reciente:
        p1, p2 = piv_max[-2], piv_max[-1]
        precio1, precio2 = float(df["high"].iloc[p1]), float(df["high"].iloc[p2])
        rsi1, rsi2 = float(rsi_s.iloc[p1]), float(rsi_s.iloc[p2])
        if precio2 > precio1 and rsi2 < rsi1:
            m["detalle"] = {
                "tipo": "bajista (precio sube, RSI baja)",
                "maximo_previo": precio1, "rsi_previo": rsi1,
                "maximo_actual": precio2, "rsi_actual": rsi2,
            }
            return True, m

    # Divergencia alcista: mínimo más bajo en precio, más alto en RSI
    piv_min = _pivotes(df["low"], "min", desde)
    if len(piv_min) >= 2 and piv_min[-1] >= minimo_reciente:
        p1, p2 = piv_min[-2], piv_min[-1]
        precio1, precio2 = float(df["low"].iloc[p1]), float(df["low"].iloc[p2])
        rsi1, rsi2 = float(rsi_s.iloc[p1]), float(rsi_s.iloc[p2])
        if precio2 < precio1 and rsi2 > rsi1:
            m["detalle"] = {
                "tipo": "alcista (precio baja, RSI sube)",
                "minimo_previo": precio1, "rsi_previo": rsi1,
                "minimo_actual": precio2, "rsi_actual": rsi2,
            }
            return True, m

    return False, m


# ---------------------------------------------------------------------------
# SIT6 — Vela de rechazo en la EMA20 (pin bar)
# ---------------------------------------------------------------------------

def _sit6_rechazo_ema20(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if len(df) < EMA_PERIODO + 1:
        return False, m

    o = float(df["open"].iloc[-1])
    h = float(df["high"].iloc[-1])
    low = float(df["low"].iloc[-1])
    c = float(df["close"].iloc[-1])
    e = m["ema20"]

    rango = h - low
    if rango <= 0 or not _toco_ema(low, h, e, _tolerancia_ema()):
        return False, m

    mecha_inf = min(o, c) - low
    mecha_sup = h - max(o, c)

    rechazo_alcista = (
        mecha_inf >= 0.6 * rango and c >= h - rango / 3 and c > e
    )
    rechazo_bajista = (
        mecha_sup >= 0.6 * rango and c <= low + rango / 3 and c < e
    )
    if not (rechazo_alcista or rechazo_bajista):
        return False, m

    vol_prom = _vol_promedio_previo(df)
    vol_actual = float(df["volume"].iloc[-1]) if "volume" in df.columns else 0.0

    m["detalle"] = {
        "tipo": "alcista (EMA20 como soporte)" if rechazo_alcista
                else "bajista (EMA20 como resistencia)",
        "mecha_pct_rango": (mecha_inf if rechazo_alcista else mecha_sup) / rango * 100,
        "con_volumen": vol_prom > 0 and vol_actual > vol_prom,
    }
    return True, m


# ---------------------------------------------------------------------------
# SIT7 — Pico de volumen anómalo
# ---------------------------------------------------------------------------

def _sit7_pico_volumen(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if "volume" not in df.columns or len(df) < VOL_PROM_PERIODO + 2:
        return False, m

    vol_prom = _vol_promedio_previo(df)
    if vol_prom <= 0:
        return False, m

    ratio = float(df["volume"].iloc[-1]) / vol_prom
    if ratio < _vol_spike_ratio():
        return False, m

    o = float(df["open"].iloc[-1])
    c = float(df["close"].iloc[-1])

    # Ubicación: un pico de volumen en soporte/resistencia es más relevante
    zonas: list[str] = []
    if abs(m["dist_ema20_pct"]) <= 2.0:
        zonas.append("EMA20")
    max_20r = float(df["high"].iloc[-(VOL_PROM_PERIODO + 1):-1].max())
    min_20r = float(df["low"].iloc[-(VOL_PROM_PERIODO + 1):-1].min())
    if c >= max_20r * 0.98:
        zonas.append("máximo de 20 ruedas")
    if c <= min_20r * 1.02:
        zonas.append("mínimo de 20 ruedas")

    m["detalle"] = {
        "ratio_volumen": ratio,
        "direccion_vela": "alcista" if c >= o else "bajista",
        "en_zona": " + ".join(zonas) if zonas else "sin nivel de referencia cercano",
    }
    return True, m


# ---------------------------------------------------------------------------
# SIT8 — Compresión de volatilidad (squeeze de Bollinger)
# ---------------------------------------------------------------------------

def _sit8_squeeze_bollinger(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    ancho_s = bollinger_ancho(df["close"], EMA_PERIODO, 2.0).dropna()
    if len(ancho_s) < BB_VENTANA:
        return False, m

    ventana = ancho_s.iloc[-BB_VENTANA:]
    umbral = float(ventana.quantile(BB_PERCENTIL))
    ancho_actual = float(ancho_s.iloc[-1])

    if ancho_actual > umbral:
        return False, m

    dias = _velas_consecutivas(ventana, umbral, sobre=False)
    m["detalle"] = {
        "ancho_bandas_pct": ancho_actual * 100,
        "dias_compresion": dias,
    }
    return True, m


# ---------------------------------------------------------------------------
# SIT9 — Máximo/mínimo de 52 semanas
# ---------------------------------------------------------------------------

def _sit9_extremo_52w(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if len(df) < EXTREMO_RUEDAS + 1:
        return False, m

    close = df["close"]
    previos = close.iloc[-(EXTREMO_RUEDAS + 1):-1]
    c = float(close.iloc[-1])

    # Desigualdad estricta: igualar el extremo previo es "testear el nivel",
    # no un extremo nuevo (y evita alertar sobre series planas).
    if c > float(previos.max()):
        # Sin niveles previos por encima en toda la historia descargada
        sin_referencia = c >= float(close.max())
        m["detalle"] = {
            "tipo": "máximo de 52 semanas",
            "maximo_previo": float(previos.max()),
            "referencia_tecnica": "sin referencia previa (zona de descubrimiento)"
                                  if sin_referencia else "hay niveles anteriores",
        }
        return True, m

    if c < float(previos.min()):
        sin_referencia = c <= float(close.min())
        m["detalle"] = {
            "tipo": "mínimo de 52 semanas",
            "minimo_previo": float(previos.min()),
            "referencia_tecnica": "sin referencia previa (zona de descubrimiento)"
                                  if sin_referencia else "hay niveles anteriores",
        }
        return True, m

    return False, m


# ---------------------------------------------------------------------------
# SIT10 — Gap significativo en la apertura (solo acciones)
# ---------------------------------------------------------------------------

def _sit10_gap(df: pd.DataFrame) -> tuple[bool, dict]:
    m = _metricas_base(df)
    if len(df) < 2:
        return False, m

    cierre_prev = float(df["close"].iloc[-2])
    apertura = float(df["open"].iloc[-1])
    cierre = float(df["close"].iloc[-1])
    if cierre_prev <= 0:
        return False, m

    gap = (apertura - cierre_prev) / cierre_prev
    if abs(gap) < _gap_pct():
        return False, m

    # Con la vela cerrada: ¿la rueda cerró achicando o extendiendo el gap?
    cerrandose = (gap > 0 and cierre < apertura) or (gap < 0 and cierre > apertura)
    m["detalle"] = {
        "gap_pct": gap * 100,
        "direccion": "alcista (gap up)" if gap > 0 else "bajista (gap down)",
        "evolucion": "cerrándose" if cerrandose else "extendiéndose",
    }
    return True, m


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

TODAS: list[Estrategia] = [
    Estrategia(id="SIT1_TOQUE_EMA20",      nombre="Toque de EMA20",                     timeframe="1d", senal_base="NONE", evaluar=_sit1_toque_ema20),
    Estrategia(id="SIT2_CRUCE_EMA20",      nombre="Cruce confirmado de EMA20",          timeframe="1d", senal_base="NONE", evaluar=_sit2_cruce_ema20),
    Estrategia(id="SIT3_RSI_SOBRECOMPRA",  nombre="RSI sobrecompra tras subida",        timeframe="1d", senal_base="NONE", evaluar=_sit3_rsi_sobrecompra),
    Estrategia(id="SIT4_RSI_SOBREVENTA",   nombre="RSI sobreventa tras caída",          timeframe="1d", senal_base="NONE", evaluar=_sit4_rsi_sobreventa),
    Estrategia(id="SIT5_DIVERGENCIA_RSI",  nombre="Divergencia RSI/precio",             timeframe="1d", senal_base="NONE", evaluar=_sit5_divergencia_rsi),
    Estrategia(id="SIT6_RECHAZO_EMA20",    nombre="Vela de rechazo en EMA20",           timeframe="1d", senal_base="NONE", evaluar=_sit6_rechazo_ema20),
    Estrategia(id="SIT7_PICO_VOLUMEN",     nombre="Pico de volumen anómalo",            timeframe="1d", senal_base="NONE", evaluar=_sit7_pico_volumen),
    Estrategia(id="SIT8_SQUEEZE_BOLLINGER", nombre="Compresión de volatilidad (squeeze)", timeframe="1d", senal_base="NONE", evaluar=_sit8_squeeze_bollinger),
    Estrategia(id="SIT9_EXTREMO_52W",      nombre="Máximo/mínimo de 52 semanas",        timeframe="1d", senal_base="NONE", evaluar=_sit9_extremo_52w),
    Estrategia(id="SIT10_GAP",             nombre="Gap significativo en apertura",      timeframe="1d", senal_base="NONE", evaluar=_sit10_gap, solo_acciones=True),
]

_NUMERO_A_ID: dict[str, str] = {e.id.split("_")[0].removeprefix("SIT"): e.id for e in TODAS}


def get_estrategias() -> list[Estrategia]:
    """
    Situaciones v2 habilitadas.

    Por defecto todas. SCANNER_V2_SITUACIONES="1,2,5" habilita solo esas.
    """
    filtro = os.environ.get("SCANNER_V2_SITUACIONES", "").strip()
    if not filtro:
        return list(TODAS)

    numeros = {t.strip() for t in filtro.split(",") if t.strip()}
    ids = {_NUMERO_A_ID[n] for n in numeros if n in _NUMERO_A_ID}
    invalidos = numeros - set(_NUMERO_A_ID)
    if invalidos:
        log.warning("SCANNER_V2_SITUACIONES contiene valores inválidos: %s", invalidos)

    activas = [e for e in TODAS if e.id in ids]
    if not activas:
        log.warning("SCANNER_V2_SITUACIONES no habilitó ninguna situación — usando todas")
        return list(TODAS)
    return activas
