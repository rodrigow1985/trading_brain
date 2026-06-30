# Reglas del Paper Trader

Define cómo funciona el simulador de trades en `paper_trader.py`. Estas reglas son las que determinan el P&L simulado — tienen que ser lo suficientemente realistas para que los resultados de la Fase 3/4 sean informativos, pero no tan complejos que esconden bugs.

---

## Cuenta virtual

| Parámetro | Valor | Configurable |
|---|---|---|
| Balance inicial | 10.000 USDT | Sí, via `PAPER_INITIAL_BALANCE` en `.env` |
| Moneda de referencia | USDT | No |
| Posiciones máximas simultáneas | 1 por par | No (por ahora) |

---

## Sizing de posición

El tamaño de cada trade se calcula para que, si el stop se activa, la pérdida sea exactamente `risk_amount`:

```
risk_pct      = 0.01  (1% del equity por trade)
risk_amount   = equity * risk_pct * multiplicador_riesgo
stop_distance = 2 * ATR  (distancia del precio de entrada al stop)
position_size = risk_amount / stop_distance  (en unidades de base currency)
```

**Ejemplo (BTC/USDT, equity = 10.000 USDT, ATR = 500, multiplicador = 0.8):**
```
risk_amount   = 10.000 * 0.01 * 0.8 = 80 USDT
stop_distance = 2 * 500 = 1.000 USDT
position_size = 80 / 1.000 = 0.08 BTC
```

Si `multiplicador_riesgo = 0.0` → `risk_amount = 0` → no abrir posición.

---

## Precio de entrada

**Open de la vela siguiente** a la vela de la señal.

No usamos el close de la vela de la señal porque eso implicaría saber el resultado antes del cierre — lookahead bias. El open de la siguiente vela es la primera oportunidad realista de entrada.

---

## Stop loss

```
LONG:  stop_price = entry_price - (2 * ATR)
SHORT: stop_price = entry_price + (2 * ATR)
```

El stop es fijo (no trailing) en esta versión. No se mueve una vez abierto.

El stop se evalúa vela a vela usando el **low** de cada vela para LONG (¿tocó el mínimo el stop?) y el **high** para SHORT.

---

## Take profit

No hay take profit fijo. La posición se cierra por una de estas razones:

| Razón | `exit_reason` en el log |
|---|---|
| El stop fue tocado (low/high de la vela) | `STOP_HIT` |
| La estrategia base genera señal en la dirección opuesta | `OPPOSITE_SIGNAL` |
| La estrategia base deja de tener señal activa (vuelve a `NONE`) | `SIGNAL_CLOSE` |
| Se superaron N velas sin que el trade alcance el stop ni genere nueva señal | `TIMEOUT` |

- `SIGNAL_CLOSE`: se activa en la primera vela en que `senal_base` vuelve a `"NONE"` mientras hay una posición abierta.
- `TIMEOUT`: se activa cuando el trade lleva `PAPER_MAX_HOLD_CANDLES` velas abierto sin haber cerrado por ninguna otra razón. N = 20 velas (configurable via `PAPER_MAX_HOLD_CANDLES` en `.env`). Evalúa `TIMEOUT` **antes** de evaluar `SIGNAL_CLOSE` en cada vela.

---

## Comisiones y slippage

| Concepto | Valor | Base |
|---|---|---|
| Comisión por operación | 0.1% del nocional | Binance spot taker fee estándar |
| Slippage | 0.05% del precio de entrada | Estimación conservadora para BTC en horario normal |

```
fee_open  = entry_price * position_size * 0.001
fee_close = exit_price  * position_size * 0.001
slippage  = entry_price * 0.0005  (se suma al precio de entrada en LONG, se resta en SHORT)
```

El slippage se aplica solo en la apertura (la entrada de mercado es el momento de mayor incertidumbre de precio).

---

## Cálculo de P&L al cierre

```python
# LONG
gross_pnl = (exit_price - entry_price_with_slippage) * position_size
fees      = fee_open + fee_close
pnl_quote = gross_pnl - fees
pnl_pct   = pnl_quote / risk_amount   # relativo al capital en riesgo, no al nocional

# SHORT
gross_pnl = (entry_price_with_slippage - exit_price) * position_size
# resto igual
```

---

## Actualización del equity

```
equity_nuevo = equity_anterior + pnl_quote  (al cierre de cada trade)
```

El equity en tiempo real (mientras el trade está abierto) se calcula como:
```
equity_real = cash + (precio_actual - entry_price) * position_size  (para LONG)
```

Esto alimenta la tabla `account_snapshots` vela a vela.

---

## Restricciones operativas

- **Sin margin ni apalancamiento** — spot only en esta versión. El nocional de la posición no puede superar el cash disponible.
- **Sin posiciones parciales** — una posición por par, o abierta o cerrada.
- **Sin re-entrada inmediata** — después de cerrar un trade (por cualquier razón), esperar al menos 1 vela antes de poder abrir otro en el mismo par.
- **Cash mínimo** — si el equity cae por debajo del 5% de `PAPER_INITIAL_BALANCE` (default: 500 USDT con balance de 10.000), no abrir nuevas posiciones. El código calcula este umbral como `PAPER_INITIAL_BALANCE * 0.05` — no es un valor fijo de 500 USDT. Loguear la condición como alerta.

---

## Qué NO modela el paper trader

Estas simplificaciones son intencionales — agregarlas después si los resultados lo justifican:

- Liquidez / book depth (asumimos fill completo siempre)
- Funding rate (solo spot por ahora)
- Gaps de precio entre velas (asumimos que el stop se activa exactamente al precio fijado)
- Impacto de mercado (posiciones chicas vs el volumen de Binance)
- Impuestos

---

## Variables de entorno

Todas las siguientes variables ya están en `.env.example`:

| Variable | Valor default | Descripción |
|---|---|---|
| `PAPER_INITIAL_BALANCE` | `10000` | Balance inicial en USDT |
| `PAPER_RISK_PCT` | `0.01` | Riesgo por trade (1% del equity) |
| `PAPER_ATR_STOP_MULT` | `2.0` | Multiplicador ATR para el stop loss |
| `PAPER_MAX_HOLD_CANDLES` | `20` | Velas máximas antes de cerrar por timeout |
| `DB_PATH` | `trading_brain.db` | Ruta del archivo SQLite |
