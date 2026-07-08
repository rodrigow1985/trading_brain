"""
Contrato común de las estrategias del scanner.

Una Estrategia es una condición técnica evaluable sobre un DataFrame OHLCV.
`evaluar(df)` devuelve (cumple, metricas):

  - cumple:   bool — la última vela cerrada dispara la condición
  - metricas: dict con claves estándar para el notifier:
        precio, rsi, ema20, dist_ema20_pct, vol_ratio
    y una clave "detalle" (dict) con los datos extra específicos de la
    estrategia (dirección, pivotes, ratio de volumen, etc.).

Restricciones:
  - NO importar ccxt ni anthropic — solo pandas.
  - Las estrategias v2 se evalúan siempre sobre velas CERRADAS; el scanner
    descarta la vela en curso antes de llamar a evaluar().
"""

from dataclasses import dataclass
from typing import Callable

import pandas as pd

EvaluarFn = Callable[[pd.DataFrame], tuple[bool, dict]]


@dataclass(frozen=True)
class Estrategia:
    """Definición declarativa de una estrategia del scanner."""

    id: str             # identificador estable (se persiste en DB y logs)
    nombre: str         # label legible para Telegram
    timeframe: str      # timeframe donde se evalúa la condición ("1d", "4h")
    senal_base: str     # "NONE" | "LONG" | "SHORT" (NONE = alerta informativa)
    evaluar: EvaluarFn
    solo_acciones: bool = False  # True → no aplica a cripto (ej. gaps)
