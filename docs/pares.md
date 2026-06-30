# Pares a Analizar

Tabla de referencia de los tickers que el cerebro evalúa. Agregar un par acá no lo activa automáticamente — hay que configurarlo en `.env` o en el scheduler. Esta tabla es el registro de intención y estado.

| Par | Mercado | Exchange | Timeframe(s) | Estado | Notas |
|---|---|---|---|---|---|
| BTC/USDT | spot | Binance | 4h · 1d · 1h | activo — fase 0 | Par inicial, referencia de desarrollo |

---

## Columnas

- **Par**: formato `BASE/QUOTE` (ccxt standard)
- **Mercado**: `spot` o `futuro`
- **Exchange**: exchange donde se opera (debe estar soportado por ccxt)
- **Timeframe(s)**: vela(s) que se evalúan; separar con coma si hay más de uno
- **Estado**: `activo`, `en prueba`, `pausado`, `descartado`
- **Notas**: razón de inclusión, particularidades del par, decisiones tomadas

---

## Cómo agregar un par

1. Agregarlo a esta tabla con estado `en prueba`
2. Correr la validación pasiva (Fase 3) durante al menos 2 semanas antes de activarlo
3. Si las métricas son aceptables, cambiar estado a `activo`
4. Si se descarta, dejar la fila con estado `descartado` y la razón en Notas (para no repetir el experimento)
