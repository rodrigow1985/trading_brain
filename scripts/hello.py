"""Fase 0 — checkpoint: verifica que el entorno está configurado correctamente."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def main() -> None:
    key = os.getenv("ANTHROPIC_API_KEY")
    exchange = os.getenv("CCXT_EXCHANGE", "binance")
    testnet = os.getenv("CCXT_TESTNET", "true")
    market_type = os.getenv("CCXT_MARKET_TYPE", "spot")

    if not key:
        print("ERROR: ANTHROPIC_API_KEY no encontrada. Copiar .env.example -> .env y completar.")
        sys.exit(1)

    masked = key[:8] + "..." + key[-4:]
    print("Trading Brain — Fase 0 OK")
    print(f"  ANTHROPIC_API_KEY : {masked}")
    print(f"  exchange          : {exchange}")
    print(f"  testnet           : {testnet}")
    print(f"  market_type       : {market_type}")


if __name__ == "__main__":
    main()
