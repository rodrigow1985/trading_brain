---
agente: desarrollador
fecha: 2026-06-15
tarea: Implementar Fase 1 — Armador de contexto (src/types.py, src/context_builder.py, scripts/fase1_checkpoint.py)
fase: Fase 1
estado: completado
archivos_creados:
  - src/types.py
  - src/context_builder.py
  - scripts/fase1_checkpoint.py
  - .env
archivos_modificados: []
---

## Resumen

Se implementó la Fase 1 completa: TypedDicts de tipos compartidos, armador de contexto multi-timeframe con ccxt y pandas-ta, y el script de checkpoint de verificación.

El checkpoint corre exitosamente contra Binance (producción, no testnet) y devuelve contexto válido para BTC/USDT con los tres timeframes (4H, 1D, 1H), todos los indicadores calculados y todos los campos presentes y no-None.

## Output del checkpoint o tests

```
23:08:19 [INFO] src.context_builder — Construyendo contexto: par=BTC/USDT mercado=spot posicion=NONE riesgo=1.00
23:08:19 [INFO] src.context_builder — Exchange binance en modo producción
23:08:19 [INFO] src.context_builder — Procesando timeframe 4h
23:08:22 [INFO] src.context_builder — Procesando timeframe 1d
23:08:23 [INFO] src.context_builder — Procesando timeframe 1h
23:08:23 [INFO] src.context_builder — Contexto construido — timestamp 1H: 2026-06-16T02:00:00+00:00

CONTEXTO COMPLETO:
{
  "par": "BTC/USDT",
  "timestamp": "2026-06-16T02:00:00+00:00",
  "mercado_tipo": "spot",
  "senal_base": "NONE",
  "portfolio": { "posicion_actual": "NONE", "riesgo_disponible_pct": 1.0 },
  "timeframes": {
    "4h": {
      "indicadores": { "rsi": 63.80, "ema_rapida": 65137.75, "ema_lenta": 64538.26,
                       "atr": 725.45, "volumen": 1021.01, "volumen_promedio": 2226.21 },
      "estructura":  { "precio_actual": 66358.0, "tendencia": "alcista",
                       "maximos_recientes": [66233.9, 67292.14, 67292.14, 67292.14, 67292.14],
                       "minimos_recientes": [63100.8, 63532.0,  63532.0,  63532.0,  63532.0] }
    },
    "1d": {
      "indicadores": { "rsi": 43.95, "ema_rapida": 66906.73, "ema_lenta": 70548.75,
                       "ema_largo": 77434.97, "atr": 2154.98, "volumen": 1021.01,
                       "volumen_promedio": 21180.16 },
      "estructura":  { "precio_actual": 66358.0, "tendencia": "bajista",
                       "maximos_recientes": [77322.01, 77322.01, 75930.01, 74449.3, 73884.38],
                       "minimos_recientes": [60884.62, 60884.62, 60884.62, 60884.62, 60884.62] }
    },
    "1h": {
      "indicadores": { "rsi": 56.27, "ema_rapida": 66229.38, "ema_lenta": 65570.25,
                       "atr": 327.08, "volumen": 106.75, "volumen_promedio": 745.99 },
      "estructura":  { "precio_actual": 66358.0, "tendencia": "alcista",
                       "maximos_recientes": [67292.14, 67292.14, 67292.14, 67292.14, 67292.14],
                       "minimos_recientes": [65596.86, 65596.86, 65596.86, 65596.86, 65596.86] }
    }
  }
}

Todos los campos requeridos están presentes y no son None.
CHECKPOINT FASE 1: PASÓ
```

Verificación de import:
```
$ grep -n "import anthropic" src/context_builder.py
(sin salida — restricción cumplida)
```

## Decisiones de implementación tomadas

1. **Timestamp de la vela 1H:** Se extrae del índice del DataFrame descargado (campo `timestamp` de ccxt), convertido a UTC con ISO 8601. Es el timestamp de apertura de la última vela, que en 1H equivale al cierre de la vela anterior.

2. **`_construir_contexto_timeframe` devuelve tupla `(dict, str)`:** Para evitar una segunda descarga redundante de 1H solo para obtener el timestamp. Retorna el sub-contexto y el timestamp ISO juntos.

3. **Normalización de `mercado_tipo`:** El parámetro acepta `"future"` (valor de `CCXT_MARKET_TYPE`) y lo normaliza a `"futuro"` según `contrato_cerebro.md`.

4. **Estructura de precio — rolling max/min sobre `close`:** Usada como simplificación de Fase 1 según lo documentado en `indicadores.md`. Las listas tienen siempre exactamente 5 elementos porque se toma `dropna().iloc[-5:]`.

5. **Pendiente de EMA para tendencia:** Se calcula como `ema[i] - ema[i-3]` exactamente como especifica `indicadores.md`.

6. **`.env` creado:** No existía el archivo `.env` (solo `.env.example`). Se creó con valores de desarrollo (sin testnet, con placeholder para `ANTHROPIC_API_KEY`).

## Huecos de spec encontrados

### CRÍTICO: EMA(200) en 1D con la descarga estándar
- **Qué falta:** `indicadores.md` dice descargar 200 velas y descartar las primeras 50, dejando 150 válidas. Pero EMA(200) necesita al menos 200 velas — pandas-ta devuelve `None` con solo 150.
- **En qué doc debería estar:** `docs/indicadores.md`, sección "Parámetros de descarga".
- **Decisión conservadora tomada:** Para el timeframe `1d` se descargan `VELAS_DESCARGAR_1D = 250` velas. Tras descartar 50 warmup quedan 200 velas válidas, suficientes para EMA(200). Los demás timeframes siguen con 200.

### MENOR: Velas de estructura en 1D con 250 descargas
- La spec dice "Usar solo las últimas 150 velas válidas para calcular estructura". Con 250 descargadas y 50 de warmup, quedan 200 válidas para 1D. La estructura (rolling max/min) se calcula sobre esas 200 — no sobre 150. Esto no rompe el contrato pero sí es un desvío de la especificación para 1D.
- **Asumido:** Calcular estructura sobre todas las velas post-warmup es más conservador y no degrada la calidad.

## Estado del checkpoint
✅ Pasó — todos los campos presentes, no-None, listas de longitud 5, tendencia válida, RSI en rango, import restriction verificada.
