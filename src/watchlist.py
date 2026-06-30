"""
Watchlist de activos para el scanner 4H.

Editar directamente esta lista para agregar o quitar activos.
  - Cripto: formato "BASE/USDT" (ccxt standard, Binance spot)
  - Acciones: ticker de Yahoo Finance (ej. "AAPL", "NVDA")
"""

CRYPTO: list[str] = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
]

ACCIONES: list[str] = [
    "AAPL",
    "NVDA",
    "MSFT",
    "META",
    "GOOGL",
    "AMZN",
    "TSLA",
    "AMD",
    "MELI",
    "INTC",
    "MU"
]

# Lista completa usada por el scanner
TODOS: list[str] = CRYPTO + ACCIONES
