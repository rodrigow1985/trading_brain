# Análisis Buffett — /buffett por Telegram

Análisis fundamental estilo Warren Buffett (value investing) bajo demanda,
via comando de Telegram. Independiente del scanner técnico.

## Uso

Escribirle al bot: `/buffett KO` (cualquier ticker de Yahoo Finance).
Solo acciones — el marco no aplica a cripto. Solo responde al chat de
`TELEGRAM_CHAT_ID`; cualquier otro chat se ignora.

```bash
# Levantar el bot (long-polling de getUpdates)
docker compose run -d --rm brain python scripts/telegram_bot.py
```

## Arquitectura (respeta el principio determinístico/LLM)

| Módulo | Rol |
|---|---|
| `src/fundamentals.py` | Determinístico: baja de yfinance precio actual + 4 años de estados financieros (márgenes, ROE, EPS, D&A, CapEx, dividendos, recompras) y calcula owner earnings aproximadas por año. |
| `brain.analizar_buffett()` | LLM: aplica el marco de 5 fases (círculo de competencia → moat → gestión → valoración → DCA) SOLO sobre los datos provistos. Nunca inventa un precio. Mismo fallback de proveedores Groq→Gemini. |
| `scripts/telegram_bot.py` | Long-polling, parseo de comandos, respuestas HTML con fallback a texto plano. |

## Marco de análisis (system prompt)

1. **Círculo de competencia** — negocio simple y predecible o descarte.
2. **Moat** — marca/costos/switching/regulación, verificado con márgenes, ROE y EPS consistentes.
3. **Gestión** — test del dólar retenido: reinversión, adquisiciones, recompras, dividendos.
4. **Valoración** — owner earnings normalizadas × múltiplo según ancho del moat (8x a 25x); margen de seguridad 20–50% según predictibilidad.
5. **DCA** — 4 niveles de entrada desde Pmax = valor intrínseco × (1 − margen).

Veredicto final: COMPRARÍA / NO COMPRARÍA / ESPERAR CORRECCIÓN, siempre con
el disclaimer "Análisis educativo, no es recomendación de inversión."

## Limitaciones conocidas

- yfinance no separa CapEx de mantenimiento vs. crecimiento → owner earnings
  castigadas por exceso (se le informa al LLM en `advertencias`).
- Historia contable limitada a 4 años anuales.
- La calidad del análisis depende del modelo configurado (`LLM_PROVIDER`).
