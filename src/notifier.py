"""
Notifier — notificaciones via Telegram.

Variables de entorno requeridas:
  TELEGRAM_BOT_TOKEN  — token del bot (de @BotFather)
  TELEGRAM_CHAT_ID    — ID numérico del chat destino (de @userinfobot)

Si alguna variable no está configurada, todas las funciones retornan
silenciosamente sin lanzar excepciones.
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

# Argentina = UTC-3 (sin horario de verano desde 2008)
_TZ_ARG = timezone(timedelta(hours=-3))


def _fmt_ts(iso_timestamp: str) -> str:
    """Convierte ISO 8601 UTC a hora Argentina legible."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        dt_arg = dt.astimezone(_TZ_ARG)
        return dt_arg.strftime("%d/%m/%Y %H:%M (ARG)")
    except Exception:
        return iso_timestamp


def _enviar(texto: str) -> None:
    """Envía mensaje HTML al chat configurado. Silencioso si no hay config."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps(
            {"chat_id": chat_id, "text": texto, "parse_mode": "HTML"}
        ).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:  # noqa: BLE001
        log.warning("Error enviando notificación Telegram: %s", exc)


def notificar_inicio(par: str, balance_inicial: float) -> None:
    """Al arrancar el scheduler."""
    _enviar(
        f"<b>Trading Brain iniciado</b>\n"
        f"Par: <code>{par}</code>\n"
        f"Capital virtual: <b>{balance_inicial:,.2f} USDT</b>\n"
        f"Esperando señales..."
    )


def notificar_senal(
    par: str, senal: str, precio: float, rsi: float, regimen: str
) -> None:
    """Cuando la estrategia detecta un cruce de EMAs."""
    direccion = "COMPRA" if senal == "LONG" else "VENTA"
    _enviar(
        f"<b>Señal detectada — {par}</b>\n"
        f"Dirección: <b>{direccion}</b>\n"
        f"Precio: <code>{precio:,.2f} USDT</code>\n"
        f"RSI 1H: <code>{rsi:.1f}</code>\n"
        f"Tendencia: {regimen}\n"
        f"<i>Evaluando con el cerebro...</i>"
    )


def notificar_decision(
    par: str,
    senal: str,
    evaluacion: str,
    multiplicador: float,
    conviccion: float,
    racional: str,
    alertas: list[str],
) -> None:
    """Después de que el cerebro evalúa la señal."""
    if evaluacion == "confirmar":
        header = f"<b>Cerebro: CONFIRMA — {par}</b>"
    elif evaluacion == "vetar":
        header = f"<b>Cerebro: VETA — {par}</b>"
    else:
        header = f"<b>Cerebro: neutral — {par}</b>"

    alertas_str = "\n".join(f"  · {a}" for a in alertas) if alertas else "  · Ninguna"
    _enviar(
        f"{header}\n"
        f"Riesgo autorizado: <b>{multiplicador * 100:.0f}%</b>  |  Convicción: {conviccion:.0%}\n"
        f"<i>{racional}</i>\n"
        f"Alertas:\n{alertas_str}"
    )


def notificar_trade_abierto(
    par: str,
    direccion: str,
    entry_price: float,
    stop_price: float,
    position_size: float,
    risk_amount: float,
) -> None:
    """Cuando el paper trader abre un trade."""
    dir_str = "LONG (compra)" if direccion == "LONG" else "SHORT (venta)"
    distancia_pct = abs(entry_price - stop_price) / entry_price * 100
    _enviar(
        f"<b>Trade abierto — {par}</b>\n"
        f"Dirección: <b>{dir_str}</b>\n"
        f"Entrada:   <code>{entry_price:,.2f} USDT</code>\n"
        f"Stop loss: <code>{stop_price:,.2f} USDT</code>  ({distancia_pct:.1f}% de distancia)\n"
        f"Tamaño:    <code>{position_size:.6f} BTC</code>\n"
        f"Riesgo:    <code>{risk_amount:.2f} USDT</code>"
    )


def notificar_trade_cerrado(
    par: str,
    direccion: str,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    pnl_quote: float,
    pnl_pct: float,
) -> None:
    """Cuando el paper trader cierra un trade."""
    resultado = "Ganancia" if pnl_quote >= 0 else "Perdida"
    signo = "+" if pnl_quote >= 0 else ""
    razones = {
        "STOP_HIT":        "Stop loss tocado",
        "SIGNAL_CLOSE":    "Señal cerrada",
        "OPPOSITE_SIGNAL": "Señal opuesta",
        "TIMEOUT":         "Tiempo máximo alcanzado",
    }
    razon_str = razones.get(exit_reason, exit_reason)
    _enviar(
        f"<b>Trade cerrado — {par} {direccion}</b>\n"
        f"Razón: {razon_str}\n"
        f"Entrada: <code>{entry_price:,.2f}</code>  →  Cierre: <code>{exit_price:,.2f}</code>\n"
        f"{resultado}: <b>{signo}{pnl_quote:.2f} USDT  ({signo}{pnl_pct * 100:.2f}%)</b>"
    )


def notificar_scanner_match(
    par: str,
    precio: float,
    ema20: float,
    dist_ema20_pct: float,
    rsi_4h: float,
) -> None:
    """Cuando el scanner detecta un activo que cumple la condición 4H + tendencia alcista 1D/1W."""
    signo = "+" if dist_ema20_pct >= 0 else ""
    _enviar(
        f"<b>Scanner 4H — setup detectado</b>\n"
        f"Activo: <code>{par}</code>\n"
        f"Precio: <code>{precio:,.4f}</code>\n"
        f"EMA20 (4H): <code>{ema20:,.4f}</code>  ({signo}{dist_ema20_pct:.2f}%)\n"
        f"RSI 4H: <code>{rsi_4h:.1f}</code> — sobreventa\n"
        f"Tendencia 1D y 1W: alcista\n"
        f"<i>Consultando al cerebro...</i>"
    )


def notificar_fallback(par: str, razon: str) -> None:
    """Cuando el cerebro activa el fallback."""
    _enviar(
        f"<b>Alerta — cerebro en modo seguro</b>\n"
        f"Par: {par}\n"
        f"Error: <code>{razon}</code>\n"
        f"<i>No se opera hasta que el cerebro responda correctamente.</i>"
    )


def notificar_vela(
    par: str,
    timestamp: str,
    senal: str,
    regimen: str,
    evaluacion: str,
    equity: float,
) -> None:
    """Resumen de cada vela procesada."""
    ts_str = _fmt_ts(timestamp)
    senal_str = senal if senal != "NONE" else "Sin señal"

    regimenes = {
        "tendencia_alcista": "Tendencia alcista",
        "tendencia_bajista": "Tendencia bajista",
        "rango":             "Lateral (rango)",
        "volatil":           "Volatil",
    }
    evaluaciones = {
        "confirmar": "Confirmado",
        "vetar":     "Vetado",
        "neutral":   "Sin accion",
    }

    _enviar(
        f"<b>Vela 1H cerrada — {ts_str}</b>\n"
        f"Par: <code>{par}</code>  |  {senal_str}\n"
        f"Mercado: {regimenes.get(regimen, regimen)}\n"
        f"Cerebro: {evaluaciones.get(evaluacion, evaluacion)}\n"
        f"Capital: <b>{equity:,.2f} USDT</b>"
    )
