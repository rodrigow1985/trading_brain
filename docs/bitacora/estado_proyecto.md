# Estado del Proyecto — trading_brain

> Documento de continuidad. Actualizar al final de cada sesión de trabajo.
> Última actualización: 2026-06-20 (Telegram notifier implementado y checkpoint OK)

---

## Fase actual: Fase 4 completada + notificaciones Telegram implementadas

---

## Resumen de fases

| Fase | Descripción | Estado |
|---|---|---|
| Fase 0 | Scaffolding, .env, hello.py | ✅ Completada |
| Fase 1 | Armador de contexto MTF (context_builder.py) | ✅ Completada |
| Fase 2 | El cerebro (brain.py) | ✅ Completada — checkpoint OK (fallback/validación verificados; LLM real bloqueado por saldo) |
| Fase 3 | Validación pasiva (harness + SQLite) | ✅ Completada — checkpoint OK (2 filas insertadas, is_fallback=0) |
| Fase 4 | Loop paper end-to-end | ✅ Completada — checkpoint OK (validate_brain 2/2 con nuevos campos _prev) |
| Fase 4+ | Notificaciones Telegram | ✅ Implementadas — notifier.py + integración en scheduler y paper_trader |
| Fase 5 | Iteración del prompt y métricas | ⏳ Pendiente |

---

## Archivos existentes

### Código
```
src/
├── types.py            ✅ TypedDicts compartidos entre módulos (Fase 4: +ema_rapida_prev, +ema_lenta_prev)
├── context_builder.py  ✅ Armador de contexto MTF (Fase 4: +prev EMAs, +señal base real)
├── brain.py            ✅ Cerebro LLM (tool use, validación, fallback)
├── strategy.py         ✅ Señal base: cruce EMA21/EMA50 en 1H + RSI
├── paper_trader.py     ✅ Simulador de trades (+notificaciones trade abierto/cerrado)
├── scheduler.py        ✅ Loop paper por vela 1H (+notificaciones inicio/señal/decisión/fallback/vela)
├── logger.py           ✅ Persistencia SQLite (+log_paper_trade_open/close, +log_account_snapshot)
└── notifier.py         ✅ Notificaciones Telegram (stdlib pura, silencioso si no hay config)

scripts/
├── hello.py              ✅ Checkpoint Fase 0
├── fase1_checkpoint.py   ✅ Checkpoint Fase 1
├── fase2_checkpoint.py   ✅ Checkpoint Fase 2
├── validate_brain.py     ✅ Harness validación pasiva Fase 3
└── run_scheduler.py      ✅ Entrypoint scheduler Fase 4
```

### Docker
```
Dockerfile           ✅ python:3.11-slim, PYTHONPATH=/app, volumen /app/data
docker-compose.yml   ✅ servicio brain + volumen ./data
.dockerignore        ✅
data/.gitkeep        ✅ directorio de persistencia SQLite (no commitear contenido)
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
docs/bitacora/analista/
  ├── 2026-06-15_revision_consistencia_inicial.md  ✅
  ├── 2026-06-16_hueco_ema200_indicadores.md        ✅
  └── 2026-06-16_revision_fase2_brain.md            ✅
docs/bitacora/desarrollador/
  ├── 2026-06-15_fase1_context_builder.md          ✅
  ├── 2026-06-16_fase2_brain.md                    ✅
  ├── 2026-06-16_refactor_multi_provider.md        ✅
  ├── 2026-06-16_fase3_logger_harness.md           ✅
  └── 2026-06-20_telegram_notifier.md              ✅
```

### Configuración
```
.env.example    ✅
.env            ✅ (creado por el desarrollador en Fase 1 — NO commitear)
.gitignore      ✅
requirements.txt ✅
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
| multiplicador_riesgo | [0.0, 1.0] — 1.0 = riesgo base completo | docs/contrato_cerebro.md |
| Exchange | Binance | CLAUDE.md |
| Mercado inicial | Spot | CLAUDE.md |
| EMAs | 21 (rápida) / 50 (lenta) / 200 (solo 1D) | docs/indicadores.md |
| Timeframes | Top-down: 4H → 1D → 1H | docs/indicadores.md |
| Señal base | Cruce EMA21/EMA50 en 1H + RSI | docs/indicadores.md |
| SIGNAL_CLOSE vs TIMEOUT | Dos exit_reason distintos; TIMEOUT se evalúa primero | docs/paper_trader.md |
| fallback_reason valores | CONTEXTO_INVALIDO, API_ERROR, JSON_MALFORMADO, SCHEMA_INVALIDO, TOOL_NO_LLAMADO | docs/log_schema.md |
| Modelo LLM | Variable ANTHROPIC_MODEL (default: claude-sonnet-4-6) | .env.example |
| Cash mínimo paper | 5% de PAPER_INITIAL_BALANCE (calculado, no fijo) | docs/paper_trader.md |
| Velas 1D para EMA200 | 250 descargadas / 200 válidas post-warmup | docs/indicadores.md |

---

## Huecos de spec pendientes de documentar

_(ninguno pendiente)_

---

## Próximos pasos

1. **Inmediato:** configurar el bot de Telegram correctamente — enviar `/start` al bot y verificar el `TELEGRAM_CHAT_ID` con `@userinfobot`. Luego arrancar el scheduler con `docker compose run --rm brain python scripts/run_scheduler.py`.
2. **Desarrollador Fase 5:** análisis del log, persistencia del estado del paper trader en SQLite, mejora de la vela OHLCV (descarga directa de la vela cerrada).
3. **Analista:** revisar los registros acumulados en `brain_calls` y `paper_trades`, auditar la coherencia de las decisiones vs señales y evaluar si el prompt necesita ajustes.

---

## Contexto para retomar en una sesión nueva

- El proyecto está en `C:\Users\rodri\Workspace\GitHub\trading_brain`
- El usuario opera en Windows con PowerShell / Git Bash
- Estilo de trading del usuario: análisis top-down 4H → 1D → 1H, EMAs 21 y 50 principalmente
- Los agentes se invocan con `/agent:analista` o `/agent:desarrollador`
- El flujo es: analista valida docs → desarrollador implementa → desarrollador escribe log → analista documenta huecos de spec
