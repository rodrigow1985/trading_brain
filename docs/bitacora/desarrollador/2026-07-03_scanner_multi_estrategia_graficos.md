# Bitácora Desarrollador — 2026-07-03: Scanner multi-estrategia + gráficos en Telegram

## Qué se implementó

Tres bloques de cambios en la misma sesión:

1. **Scanner multi-estrategia configurable** (4 estrategias via `.env`)
2. **Gráficos PNG adjuntos al mensaje Telegram** (`mplfinance`, estilo oscuro)
3. **Fallback automático Groq → Gemini** cuando se agota el rate limit diario

### Archivos nuevos

| Archivo | Rol |
|---|---|
| `src/charting.py` | Genera PNG en memoria (velas + EMA20 + RSI subplot) |
| `docs/bitacora/desarrollador/2026-07-03_scanner_multi_estrategia_graficos.md` | Esta entrada |

### Archivos modificados

| Archivo | Qué cambió |
|---|---|
| `src/scanner.py` | Reescritura completa: 4 estrategias, `_ESTRATEGIA_TF`, `_SENAL_BASE`, `vol_ratio` en métricas, `chart_png` en resultado |
| `src/brain.py` | `_RateLimitError`, `_es_rate_limit()`, `_modelo_gemini()`, fallback Groq→Gemini en los dos despachadores |
| `src/notifier.py` | `_fmt_rsi()`, `_fmt_vol()`, `_enviar_foto()` (sendPhoto via requests), reescritura de `notificar_scanner()` |
| `scripts/run_scanner.py` | Firma de `_notificar_resultados` actualizada: `chart_png`, `timeframe` |
| `requirements.txt` | `mplfinance>=0.12.10a1`, `requests>=2.31.0` |
| `.env` / `.env.example` | 4 estrategias + umbrales configurables; `EMA20_DISTANCIA_PCT` bajado de 2% a 1% |
| `docs/bitacora/estado_proyecto.md` | Actualizado al cierre de esta sesión |

---

## Estrategias

### 4 estrategias configurables

| Estrategia | Timeframe | Señal | Descripción |
|---|---|---|---|
| `RSI_SOBREVENTA` | 4H | NONE (alerta) | RSI < umbral |
| `RSI_SOBRECOMPRA` | 4H | NONE (alerta) | RSI > umbral |
| `EMA20_TOQUE` | **1D** | NONE (alerta) | precio dentro de ±dist% de EMA20 diaria |
| `EMA20_RSI_SOBREVENTA` | 4H | LONG | EMA20 toque + RSI sobreventa + 1D/1W alcistas |

Cada una se habilita con `SCANNER_<NOMBRE>=true` en `.env`.

### Flujo de descarga por par (eficiencia)

```
1. Descargar 4H → evaluar estrategias 4H
2. Si hay activas_1d OR algo pasó en 4H → descargar 1D → evaluar EMA20_TOQUE
3. Si algo pasó → descargar 1W y 1H
4. Por cada estrategia que pasó: filtro MTF → contextualizar() → generar chart → resultado
```

Se descarga 4H siempre (necesario para construir el contexto del cerebro). El 1D se descarga si hay al menos una estrategia 1D activa o algo pasó en 4H. El 1W y 1H solo si algo va a notificarse.

### EMA20_TOQUE en daily

La condición de toque a la EMA20 es mucho más significativa en daily que en 4H. En 4H generaba demasiado ruido (casi todos los activos cumplían en algún momento del día). Se separó por `_ESTRATEGIA_TF`:

```python
_ESTRATEGIA_TF = {
    "RSI_SOBREVENTA":       "4h",
    "RSI_SOBRECOMPRA":      "4h",
    "EMA20_TOQUE":          "1d",   # ← daily
    "EMA20_RSI_SOBREVENTA": "4h",
}
```

Umbral: `SCANNER_EMA20_DISTANCIA_PCT=1` (±1%). Con 2% capturaba demasiados activos en el contexto de mercado actual (consolidación general cerca de EMA20).

---

## Diseño

### Gráficos PNG (`src/charting.py`)

Función pura: `generar_chart_png(df, par, timeframe, n_velas=80) -> bytes`

- Calcula EMA20 y RSI(14) internamente desde el df (no depende de metricas calculadas antes)
- `mplfinance` con estilo `nightclouds` (fondo oscuro, similar al ejemplo de referencia)
- Paneles: precio+EMA20 (4 partes) / volumen (1 parte) / RSI+niveles 70/30 (2 partes)
- Genera en memoria (`BytesIO`), nunca toca disco
- `matplotlib.use("Agg")` para modo headless (sin display)
- El chart usa el timeframe de la estrategia que lo disparó (4H o 1D)

### Envío de foto Telegram (`notifier._enviar_foto`)

Usa `requests.post` con `files={"photo": ...}` (multipart/form-data). Si falla, cae silenciosamente a `_enviar()` (mensaje de texto puro). Caption limitado a 1024 chars (límite Telegram).

### Formato del mensaje (inspirado en ejemplo "Robotito")

```
🟡 BTC/USDT (Binance) — Toque EMA20 📊 Neutro
<i>Alerta informativa · Diario</i>

<b>Indicadores</b>
RSI 1D: 43.0 ↓
EMA20: 95,421.50 | Dist: -1.26% ↓
Volumen: 0.9×

<b>Análisis IA</b>
📊 BTC/USDT | Binance | Diario

[5-6 líneas de análisis en prosa del cerebro]

⚠️ Nivel: Medio
Riesgos:
  · factor concreto
```

- Círculo de color: 🟢 LONG / 🔴 SHORT / 🟡 alertas
- RSI: `↓🔴` si < 35, `↑🔴` si > 70
- Volumen: `↑📈` si > 1.5× promedio, `↓📉` si < 0.7×
- Campo "Precio" eliminado — visible en el gráfico
- "Mercado" detectado por tipo de activo: "Binance" para cripto, "Acciones" para stocks

### Fallback Groq → Gemini

Free tier de Groq: 100k tokens/día. Con 17 activos en 4 estrategias se agota en el primer escaneo.

Mecanismo:
1. `_es_rate_limit(exc)` detecta HTTP 429 por nombre de clase o string de error
2. `_llamar_groq_scanner()` lanza `_RateLimitError` (excepción interna del módulo) en lugar de retornar None
3. `_llamar_proveedor_scanner()` captura `_RateLimitError` y llama a `_llamar_gemini_scanner()`
4. `_modelo_gemini()` ignora `LLM_MODEL` si no empieza con "gemini-" (evita que Groq pase `llama-3.3-70b-versatile` a la API de Gemini)
5. Mismo patrón en el path `_llamar_proveedor()` para el scheduler

---

## Uso

```bash
# Rebuild (necesario después de agregar mplfinance/requests)
docker compose build

# Test inmediato con gráficos
docker compose run --rm brain python scripts/run_scanner.py --ahora

# Loop automático cada cierre de vela 4H
docker compose run --rm brain python scripts/run_scanner.py

# Cambiar proveedor LLM en .env
LLM_PROVIDER=groq          # primario
LLM_MODEL=llama-3.3-70b-versatile
GEMINI_API_KEY=...         # fallback automático si Groq 429
```

---

## Pendientes

- Probar el formato del mensaje con gráfico en Telegram cuando Groq tenga tokens disponibles (el test de esta sesión se hizo con Groq agotado → cerebro en fallback)
- Agregar `GEMINI_MODEL` como variable de entorno independiente para mayor control del modelo de fallback
- Log de resultados del scanner en SQLite (actualmente solo va a Telegram)
- Noticias del activo al contexto del cerebro
