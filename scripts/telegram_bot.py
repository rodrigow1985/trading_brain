"""
Bot de Telegram — comandos entrantes.

Escucha mensajes via long-polling (getUpdates) y responde comandos:

    /buffett TICKER   — análisis value investing estilo Warren Buffett
                        (fundamentals reales de yfinance + LLM)
    /help             — lista de comandos

Usa su PROPIO bot de Telegram (TELEGRAM_COMMAND_BOT_TOKEN), separado del bot
de alertas (TELEGRAM_BOT_TOKEN): el token de alertas lo comparte otro proceso
con polling activo (top-briefing) y dos consumidores de getUpdates sobre el
mismo token chocan con 409 Conflict. Sin fallback deliberadamente.

Seguridad: solo responde a mensajes del chat configurado en TELEGRAM_CHAT_ID.
Cualquier otro chat se ignora en silencio.

Uso:
    docker compose run -d --rm brain python scripts/telegram_bot.py
"""

import logging
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src.brain import analizar_buffett
from src.fundamentals import construir_contexto_fundamental

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

POLL_TIMEOUT = 50  # segundos de long-polling por request
_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")

_AYUDA = (
    "<b>Comandos disponibles</b>\n\n"
    "🎩 /buffett TICKER — análisis value investing estilo Warren Buffett "
    "(ej: <code>/buffett KO</code>)\n"
    "ℹ️ /help — esta ayuda\n\n"
    "<i>Solo acciones (tickers de Yahoo Finance). "
    "El marco Buffett no aplica a cripto.</i>"
)


def _api(metodo: str) -> str:
    token = os.environ["TELEGRAM_COMMAND_BOT_TOKEN"]
    return f"https://api.telegram.org/bot{token}/{metodo}"


def _responder(chat_id: str, texto: str) -> None:
    """Envía respuesta HTML; si Telegram rechaza el HTML, reintenta en texto plano."""
    try:
        r = requests.post(
            _api("sendMessage"),
            json={"chat_id": chat_id, "text": texto[:4096], "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code == 400:
            log.warning("HTML rechazado por Telegram — reenviando como texto plano")
            requests.post(
                _api("sendMessage"),
                json={"chat_id": chat_id, "text": texto[:4096]},
                timeout=15,
            )
    except Exception as exc:  # noqa: BLE001
        log.error("Error enviando respuesta: %s", exc)


def _accion_escribiendo(chat_id: str) -> None:
    try:
        requests.post(
            _api("sendChatAction"),
            json={"chat_id": chat_id, "action": "typing"},
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        pass


def _comando_buffett(chat_id: str, args: str) -> None:
    ticker = args.strip().upper()

    if not ticker:
        _responder(chat_id, "Indicá un ticker: <code>/buffett KO</code>")
        return
    if "/" in ticker or not _TICKER_RE.match(ticker):
        _responder(
            chat_id,
            f"<code>{ticker}</code> no parece un ticker de acción válido. "
            "El análisis Buffett aplica solo a empresas (ej: AAPL, KO, MELI).",
        )
        return

    _responder(chat_id, f"🎩 Analizando <b>{ticker}</b> — bajando fundamentals...")
    _accion_escribiendo(chat_id)

    try:
        contexto = construir_contexto_fundamental(ticker)
    except Exception as exc:  # noqa: BLE001
        log.warning("Fundamentals fallaron para %s: %s", ticker, exc)
        _responder(
            chat_id,
            f"No pude obtener datos fundamentales de <b>{ticker}</b>. "
            "¿El ticker existe en Yahoo Finance?",
        )
        return

    _accion_escribiendo(chat_id)
    analisis = analizar_buffett(contexto)
    if not analisis:
        _responder(
            chat_id,
            f"El análisis de <b>{ticker}</b> falló (LLM no disponible). "
            "Probá de nuevo en unos minutos.",
        )
        return

    _responder(chat_id, analisis)


def _procesar_mensaje(mensaje: dict, chat_autorizado: str) -> None:
    chat_id = str(mensaje.get("chat", {}).get("id", ""))
    texto = (mensaje.get("text") or "").strip()

    if chat_id != chat_autorizado:
        log.warning("Mensaje de chat no autorizado (%s) — ignorado", chat_id)
        return
    if not texto:
        return

    # "/buffett@MiBot KO" → comando="/buffett", args="KO"
    partes = texto.split(maxsplit=1)
    comando = partes[0].split("@")[0].lower()
    args = partes[1] if len(partes) > 1 else ""

    log.info("Comando recibido: %s %s", comando, args)

    if comando == "/buffett":
        _comando_buffett(chat_id, args)
    elif comando in ("/help", "/start", "/ayuda"):
        _responder(chat_id, _AYUDA)
    elif comando.startswith("/"):
        _responder(chat_id, f"Comando desconocido: <code>{comando}</code>\n\n{_AYUDA}")
    # texto sin "/" se ignora


def run() -> None:
    token = os.environ.get("TELEGRAM_COMMAND_BOT_TOKEN", "")
    chat_autorizado = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_autorizado:
        log.error("TELEGRAM_COMMAND_BOT_TOKEN / TELEGRAM_CHAT_ID no configurados — saliendo")
        sys.exit(1)
    if token == os.environ.get("TELEGRAM_BOT_TOKEN", ""):
        log.error(
            "TELEGRAM_COMMAND_BOT_TOKEN es igual a TELEGRAM_BOT_TOKEN — ese token "
            "ya tiene otro consumidor de getUpdates (409). Crear un bot dedicado "
            "con @BotFather. Saliendo."
        )
        sys.exit(1)

    log.info("=== Bot de Telegram iniciado — escuchando comandos (/buffett) ===")
    offset = 0

    while True:
        try:
            r = requests.get(
                _api("getUpdates"),
                params={"offset": offset, "timeout": POLL_TIMEOUT},
                timeout=POLL_TIMEOUT + 10,
            )
            r.raise_for_status()
            updates = r.json().get("result", [])
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("Error en getUpdates: %s — reintento en 10s", exc)
            time.sleep(10)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            mensaje = update.get("message") or update.get("edited_message")
            if not mensaje:
                continue
            try:
                _procesar_mensaje(mensaje, chat_autorizado)
            except Exception as exc:  # noqa: BLE001
                log.error("Error procesando mensaje: %s", exc, exc_info=True)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Bot interrumpido por el usuario. Cerrando.")
