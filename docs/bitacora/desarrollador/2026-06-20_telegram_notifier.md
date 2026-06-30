# Bitácora Desarrollador — 2026-06-20: Telegram Notifier

## Qué se implementó

Notificaciones via Telegram para el loop paper. Componentes nuevos/modificados:

- `src/notifier.py` — módulo nuevo, stdlib pura (sin dependencias externas)
- `src/scheduler.py` — integración de notificaciones en el loop
- `src/paper_trader.py` — notificaciones de trade abierto y trade cerrado
- `.env.example` — variables `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`

---

## Diseño

### `src/notifier.py`

Función base `_enviar(texto)` privada que llama a la Bot API de Telegram via `urllib.request`. Si `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID` no están en el entorno, retorna inmediatamente sin error — el scheduler nunca se rompe por problemas de notificaciones.

Funciones públicas implementadas:

| Función | Cuándo se llama |
|---|---|
| `notificar_inicio` | Al arrancar el scheduler |
| `notificar_senal` | Cuando la estrategia detecta LONG o SHORT (con régimen del cerebro) |
| `notificar_decision` | Después de que el cerebro evalúa una señal LONG o SHORT |
| `notificar_trade_abierto` | Cuando el paper trader abre un trade (en `paper_trader.py`) |
| `notificar_trade_cerrado` | Cuando el paper trader cierra un trade (en `paper_trader.py`) |
| `notificar_fallback` | Cuando `FALLBACK_ACTIVADO` aparece en `decision["alertas"]` |
| `notificar_vela` | Al final de cada vela, siempre |

Formato: texto plano con `<b>` HTML (Telegram `parse_mode: HTML`). Sin emojis. El `&` en "P&L" se escapa como `&amp;` para no romper el parser HTML de Telegram.

### Integración en `scheduler.py`

- `notificar_senal` y `notificar_decision` se llaman juntas después del cerebro, dentro del bloque `if senal_base in ("LONG", "SHORT")`. El régimen viene de `decision["regimen"]` — más preciso que llamarla antes del cerebro.
- `notificar_fallback` se llama si `"FALLBACK_ACTIVADO" in decision["alertas"]`.
- `notificar_vela` se llama al final de cada ciclo, siempre.
- Todas las llamadas van dentro de `try/except` con `log.warning`.

### Integración en `paper_trader.py`

- `notificar_trade_cerrado` se llama inmediatamente después de `log_paper_trade_close`, con los valores `entry_p`, `exit_price`, `exit_reason`, `pnl_quote`, `pnl_pct` ya calculados.
- `notificar_trade_abierto` se llama después de `log_paper_trade_open`, con `entry_with_slip`, `stop_price_new`, `position_size`, `risk_amount`.
- Ambas dentro de `try/except` con `log.warning`.

---

## Checkpoint

```
docker compose run --rm brain python -c "... (7 funciones) ..."
```

Resultado: los 7 mensajes se enviaron sin errores de Python. El módulo importa correctamente. La API de Telegram devolvió `400 Bad Request: chat not found` porque el `TELEGRAM_CHAT_ID` en `.env` apunta a un chat donde el bot aún no fue iniciado. El `try/except` en `_enviar` capturó el error como `log.warning` y el script completó con `"Mensajes enviados"` — comportamiento correcto.

### Para activar las notificaciones

1. En Telegram: enviar `/start` al bot correspondiente al `TELEGRAM_BOT_TOKEN`.
2. Verificar el `TELEGRAM_CHAT_ID` con `@userinfobot`.
3. Reiniciar el scheduler — la próxima vela enviará `notificar_vela`.

---

## Restricciones verificadas

- `notifier.py` no importa `ccxt`, `pandas`, `pandas_ta` ni `anthropic`.
- Usa únicamente `urllib.request`, `urllib.parse`, `json`, `os`, `logging` (stdlib).
- Silencioso si las variables de entorno no están configuradas.
- Ninguna excepción de Telegram puede romper el loop del scheduler.
