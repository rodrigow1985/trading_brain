"""
Entrypoint del scheduler paper trader — Fase 4.

Uso:
    docker compose run --rm brain python scripts/run_scheduler.py
    docker compose run --rm brain python -m src.scheduler
"""

import os
import sys

# Asegurarse de que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scheduler import run

if __name__ == "__main__":
    par = os.environ.get("TRADING_PAR", "BTC/USDT")
    mercado_tipo = os.environ.get("CCXT_MARKET_TYPE", "spot")

    # Normalizar "future" → "futuro" (el context_builder lo hace también, pero por consistencia)
    if mercado_tipo == "future":
        mercado_tipo = "futuro"

    run(par=par, mercado_tipo=mercado_tipo)
