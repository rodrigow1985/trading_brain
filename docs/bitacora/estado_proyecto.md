# Estado del Proyecto — trading_brain

> Documento de continuidad. Actualizar al final de cada sesión de trabajo.
> Última actualización: 2026-07-03 (Scanner multi-estrategia + gráficos + fallback Groq→Gemini)

---

## Fase actual: Scanner 4H multi-estrategia en producción (rama feat/chart-image)

---

## Resumen de fases

| Fase | Descripción | Estado |
|---|---|---|
| Fase 0 | Scaffolding, .env, hello.py | ✅ Completada |
| Fase 1 | Armador de contexto MTF (context_builder.py) | ✅ Completada |
| Fase 2 | El cerebro (brain.py) | ✅ Completada |
| Fase 3 | Validación pasiva (harness + SQLite) | ✅ Completada |
| Fase 4 | Loop paper end-to-end | ✅ Completada |
| Fase 4+ | Notificaciones Telegram | ✅ Implementadas |
| Fase 4+ | Scanner 4H multi-activo (estrategia única) | ✅ Implementado |
| Fase 4+ | Scanner multi-estrategia + gráficos | ✅ Implementado — rama feat/chart-image |
| Fase 5 | Iteración del prompt y métricas | ⏳ Pendiente |

---

## Archivos existentes

### Código
```
src/
├── types.py            ✅ TypedDicts compartidos
├── context_builder.py  ✅ Armador de contexto MTF
├── brain.py            ✅ Cerebro LLM — analizar() + contextualizar(); fallback Groq→Gemini
├── strategy.py         ✅ Señal base: cruce EMA21/EMA50 en 1H
├── paper_trader.py     ✅ Simulador de trades
├── scheduler.py        ✅ Loop paper por vela 1H
├── logger.py           ✅ Persistencia SQLite
├── notifier.py         ✅ Notificaciones Telegram (texto + foto sendPhoto)
├── scanner.py          ✅ Scanner multi-estrategia (4 estrategias, 4H/1D, vol_ratio, chart)
├── charting.py         ✅ Generación de PNG con mplfinance (velas + EMA20 + RSI)
└── watchlist.py        ✅ Lista editable de activos (6 cripto + 11 acciones)

scripts/
├── hello.py              ✅ Checkpoint Fase 0
├── fase1_checkpoint.py   ✅ Checkpoint Fase 1
├── fase2_checkpoint.py   ✅ Checkpoint Fase 2
├── validate_brain.py     ✅ Harness validación pasiva Fase 3
├── run_scheduler.py      ✅ Entrypoint scheduler Fase 4 (loop 1H, cruce EMAs)
├── run_scanner.py        ✅ Entrypoint scanner 4H (loop 4H, multi-estrategia)
└── consultar_cerebro.py  ✅ Consulta manual ad-hoc al cerebro
```

### Docker
```
Dockerfile           ✅ python:3.11-slim, PYTHONPATH=/app, volumen /app/data
docker-compose.yml   ✅ servicio brain + volumen ./data
.dockerignore        ✅
data/.gitkeep        ✅
```

### Documentación
```
CLAUDE.md                              ✅
docs/arquitectura.md                   ✅
docs/contrato_cerebro.md               ✅
docs/indicadores.md                    ✅
docs/system_prompt.md                  ✅
docs/log_schema.md                     ✅
docs/paper_trader.md                   ✅
docs/pares.md                          ✅
docs/images/
  └── imagen-ejemplo-robot.jpg         ✅ Referencia visual para formato de mensajes Telegram
docs/bitacora/analista/
  ├── 2026-06-15_revision_consistencia_inicial.md  ✅
  ├── 2026-06-16_hueco_ema200_indicadores.md        ✅
  └── 2026-06-16_revision_fase2_brain.md            ✅
docs/bitacora/desarrollador/
  ├── 2026-06-15_fase1_context_builder.md           ✅
  ├── 2026-06-16_fase2_brain.md                     ✅
  ├── 2026-06-16_refactor_multi_provider.md         ✅
  ├── 2026-06-16_fase3_logger_harness.md            ✅
  ├── 2026-06-20_telegram_notifier.md               ✅
  ├── 2026-07-01_scanner_4h.md                      ✅
  └── 2026-07-03_scanner_multi_estrategia_graficos.md ✅
```

### Configuración
```
.env.example    ✅
.env            ✅ (NO commitear — LLM_PROVIDER=groq, fallback a Gemini)
.gitignore      ✅
requirements.txt ✅ — mplfinance + requests agregados
.claude/agents/
├── analista.md     ✅
└── desarrollador.md ✅
```

---

## Decisiones técnicas tomadas

| Decisión | Valor | Dónde está documentado |
|---|---|---|
| Dependencias | requirements.txt | CLAUDE.md |
| Salida LLM | Tool use (no JSON mode) | docs/system_prompt.md |
| multiplicador_riesgo | [0.0, 1.0] | docs/contrato_cerebro.md |
| Exchange | Binance | CLAUDE.md |
| EMAs | 21 (rápida) / 50 (lenta) / 200 (solo 1D) | docs/indicadores.md |
| Timeframes | Top-down: 4H → 1D → 1H | docs/indicadores.md |
| Señal base scheduler | Cruce EMA21/EMA50 en 1H + RSI | docs/indicadores.md |
| Scanner EMA20_TOQUE | Evaluado en 1D (no 4H) | bitacora 2026-07-03 |
| Scanner umbral EMA20 | ±1% (bajado de 2% por ruido excesivo) | bitacora 2026-07-03 |
| Cerebro en scanner | contextualizar() — no veta, solo complementa | bitacora 2026-07-01 |
| LLM provider | Groq primario; fallback a Gemini si 429 | bitacora 2026-07-03 |
| Modelo Gemini fallback | gemini-flash-lite-latest via REST directo (sin SDK) | bitacora 2026-07-03 |
| Gráficos | mplfinance nightclouds, 80 velas, EMA20 + RSI subplot | bitacora 2026-07-03 |
| Formato Telegram | Foto + caption con secciones Indicadores / Análisis IA | docs/images/imagen-ejemplo-robot.jpg |

---

## Proveedor LLM activo

```
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
# Fallback automático → Gemini REST (gemini-flash-lite-latest) si Groq devuelve 429
# Gemini se llama vía REST directo (?key= query param), sin SDK
# GEMINI_MODEL= vacío → usa gemini-flash-lite-latest (default en _modelo_gemini())
```

---

## Próximos pasos

1. **Foto en Telegram:** la primera foto falla (400) pero el fallback a texto funciona. Investigar causa raíz (puede ser rate limit de la primera request al bot).
2. **Groq tokens:** se agotan en el primer escaneo del día. Considerar Dev Tier o reducir assets.
3. **Log SQLite del scanner:** persistir matches en `brain_calls` o tabla nueva para análisis posterior.
4. **Noticias:** agregar contexto fundamental al análisis del cerebro.
5. **Merge feat/chart-image → main** cuando el formato esté validado en producción.

---

## Contexto para retomar en una sesión nueva

- El proyecto está en `C:\Users\rodri\Workspace\GitHub\trading_brain`
- El usuario opera en Windows con PowerShell / Git Bash
- Rama activa: `feat/chart-image` (pendiente merge a main)
- Los agentes se invocan con `/agent:analista` o `/agent:desarrollador`
- El scanner corre con `docker compose run --rm brain python scripts/run_scanner.py`
- Para test inmediato: agregar `--ahora`
