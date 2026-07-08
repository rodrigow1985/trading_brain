"""
Paquete de estrategias del scanner, versionado.

Cada versión vive en su propio módulo (v1.py, v2.py) y expone
`get_estrategias() -> list[Estrategia]`. La versión activa se elige con la
variable de entorno SCANNER_STRATEGY_SET:

    SCANNER_STRATEGY_SET=v1  → las 4 estrategias originales (RSI 4H, EMA20 1D)
    SCANNER_STRATEGY_SET=v2  → screener de situaciones técnicas 1D (default)

Rollback instantáneo: cambiar la variable en .env y reiniciar el scanner.
El snapshot de código de la v1 también está taggeado en git: `estrategias-v1`.
"""

import logging
import os

from src.strategies.base import Estrategia

log = logging.getLogger(__name__)

VERSION_DEFAULT = "v2"


def get_strategy_set() -> str:
    """Devuelve la versión de estrategias activa ("v1" | "v2")."""
    version = os.environ.get("SCANNER_STRATEGY_SET", VERSION_DEFAULT).strip().lower()
    if version not in ("v1", "v2"):
        log.warning(
            "SCANNER_STRATEGY_SET=%s no reconocido — usando %s", version, VERSION_DEFAULT
        )
        return VERSION_DEFAULT
    return version


def get_estrategias() -> list[Estrategia]:
    """Devuelve las estrategias habilitadas de la versión activa."""
    version = get_strategy_set()
    if version == "v1":
        from src.strategies import v1
        return v1.get_estrategias()
    from src.strategies import v2
    return v2.get_estrategias()
