# Bitácora de cambios — trading_brain

Registro cronológico de decisiones, cambios de diseño y evolución del proyecto.
Ordenado del más reciente al más antiguo.

---

## 2026-07-03

### Scanner multi-estrategia + gráficos en Telegram

**Motivación:** el scanner original solo evaluaba un cruce EMA21/EMA50 en 1H, lo cual generaba pocas señales y no aprovechaba las alertas de interés más amplio.

**Cambios:**

#### 4 estrategias configurables via `.env`
- `SCANNER_RSI_SOBREVENTA` — RSI 4H < umbral → alerta informativa (NONE)
- `SCANNER_RSI_SOBRECOMPRA` — RSI 4H > umbral → alerta informativa (NONE)
- `EMA20_TOQUE` — precio en daily dentro de ±dist% de la EMA20 → alerta informativa (NONE)
- `EMA20_RSI_SOBREVENTA` — EMA20 toque 4H + RSI sobreventa 4H + 1D/1W alcistas → señal LONG

Cada estrategia se habilita/deshabilita con `SCANNER_<NOMBRE>=true/false`.

Umbrales configurables:
```
SCANNER_RSI_SOBREVENTA_UMBRAL=35
SCANNER_RSI_SOBRECOMPRA_UMBRAL=70
SCANNER_EMA20_DISTANCIA_PCT=1        # bajado de 2% a 1% — menos ruido
```

#### EMA20_TOQUE en daily (no 4H)
El toque a la EMA20 es significativo en timeframe diario. Evaluarlo en 4H generaba demasiado ruido. Se agregó `_ESTRATEGIA_TF` dict para categorizar estrategias por timeframe.

#### Rol del cerebro: contextualizar, no vetar
En el scanner el cerebro no puede vetar señales. Solo complementa con 5-6 líneas de análisis cualitativo: tendencia, calidad, estructura, volumen, riesgos. Usa `contextualizar()` en lugar de `analizar()`.

#### Formato de mensajes Telegram (inspirado en ejemplo "Robotito")
Estructura con secciones separadas, fiel al ejemplo analizado:
```
🟡 BTC/USDT (Binance) — Toque EMA20 📊 Neutro
Alerta informativa · Diario

Indicadores
RSI 1D: 43.0 ↓
EMA20: 95,421.50 | Dist: -1.26% ↓
Volumen: 0.9×

Análisis IA
📊 BTC/USDT | Binance | Diario

[5-6 líneas de análisis en prosa]

⚠️ Nivel: Medio
Riesgos:
  · factor 1
```

- Emojis de círculo de color: 🟢 LONG, 🔴 SHORT, 🟡 alertas
- Flechas en RSI (↑↓🔴) y volumen (📈📉)
- Se eliminó el campo "Precio" — visible en el gráfico

#### Gráficos PNG adjuntos al mensaje Telegram
- Nueva librería: `mplfinance>=0.12.10a1` + `requests>=2.31.0`
- `src/charting.py`: genera PNG en memoria con velas + EMA20 + RSI subplot (estilo nightclouds)
- `notifier._enviar_foto()`: usa Telegram `sendPhoto` via `requests` (multipart/form-data)
- Si el chart falla → fallback a mensaje de texto puro
- El timeframe del chart es el mismo que el de la estrategia (4H para RSI/EMA20_RSI, 1D para EMA20_TOQUE)

#### Fallback automático Groq → Gemini por rate limit
- Free tier de Groq: 100k tokens/día (se agota rápidamente con 17 activos)
- `_RateLimitError`: excepción interna que se lanza cuando se detecta HTTP 429 de Groq
- `_llamar_proveedor_scanner()` y `_llamar_proveedor()` capturan `_RateLimitError` y caen a Gemini
- Gemini ignora `LLM_MODEL` si no es un modelo Gemini (usa `gemini-2.0-flash` por default)
- Cadena: Groq → Gemini (si GEMINI_API_KEY disponible) → fallback texto

**Archivos modificados:**
- `src/scanner.py` — reescritura completa (multi-estrategia, timeframes, vol_ratio)
- `src/brain.py` — `_RateLimitError`, `_es_rate_limit()`, `_modelo_gemini()`, fallback en despachadores
- `src/notifier.py` — `_fmt_rsi()`, `_fmt_vol()`, `_enviar_foto()`, `notificar_scanner()` reescritura
- `src/charting.py` — nuevo módulo de generación de gráficos
- `scripts/run_scanner.py` — firma actualizada para `chart_png` y `timeframe`
- `requirements.txt` — `mplfinance`, `requests`
- `.env` / `.env.example` — estrategias y umbrales

---

## 2026-06-30

### Scanner 4H inicial + cerebro como contextualizador

**Motivación:** reemplazar el loop 1H de señal EMA21/EMA50 por un scanner multi-activo en 4H que analice cripto y acciones.

**Cambios:**

#### Watchlist multi-activo
- `src/watchlist.py`: 6 cripto (BTC, ETH, SOL, BNB, XRP, ADA) + 11 acciones (AAPL, NVDA, MSFT, META, GOOGL, AMZN, TSLA, AMD, MELI, INTC, MU)
- Descarga cripto via `ccxt/Binance` y acciones via `yfinance` (4H resampleado de 1H)

#### Cerebro como contextualizador (no vetador)
- Se separaron `analizar()` (para el scheduler, puede vetar) y `contextualizar()` (para el scanner, nunca veta)
- `_SYSTEM_PROMPT_SCANNER`: prompt direction-aware según `senal_base` (LONG/SHORT/NONE)
- Tool `contexto_scanner`: devuelve `{analisis, nivel_atencion, alertas}`

#### Filtro de tendencia MTF para señal LONG
- `EMA20_RSI_SOBREVENTA`: requiere 1D (close > EMA50) y 1W (close > EMA20) alcistas
- Alertas (NONE): sin filtro MTF, siempre pasan si la condición técnica se cumple

#### Soporte multi-proveedor LLM
- `LLM_PROVIDER`: anthropic | gemini | groq
- `LLM_MODEL`: override del modelo por proveedor
- Imports lazy de SDKs de terceros

**Archivos creados:**
- `src/scanner.py` (versión inicial), `src/watchlist.py`, `scripts/run_scanner.py`
- `scripts/consultar_cerebro.py` — consulta manual al cerebro

---

## 2026-06-19 (aprox.)

### Fases 0-2: scaffolding, context builder, cerebro inicial

- Fase 0: estructura del proyecto, `requirements.txt`, `.env.example`, `hello.py`
- Fase 1: `src/context_builder.py` — descarga OHLCV, calcula RSI/EMA/ATR con pandas-ta
- Fase 2: `src/brain.py` — `analizar()` con tool use forzado, validación de schema, fallback
- Fase 3 (parcial): `src/logger.py` — log en SQLite
- Fase 4 (parcial): loop 1H con señal EMA21/EMA50 como primer scheduler

---

## Pendientes / próximas iteraciones

- [ ] Integración de noticias al análisis del cerebro (mencionado en sesión de junio)
- [ ] Log de resultados del scanner en SQLite (actualmente solo va a Telegram)
- [ ] Métricas de calidad de las alertas (qué % de alertas EMA20_TOQUE son seguidas por movimiento relevante)
- [ ] Test del formato final del mensaje con gráfico en Telegram con Groq funcional
- [ ] Considerar modelo de Gemini específico en `.env` (`GEMINI_MODEL`) para mayor control
