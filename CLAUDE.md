# Trading Brain — CLAUDE.md

## Qué es este proyecto

Un componente basado en LLM (Claude) que actúa como analista/filtro sobre señales de trading de criptomonedas. Evalúa contexto de mercado multi-timeframe y devuelve una decisión estructurada: régimen, confirmación/veto, multiplicador de riesgo y justificación.

**No predice precios. No toma decisiones de ejecución. Solo razona sobre el contexto que le pasa el código determinístico.**

---

## Documentación de referencia

Antes de tocar cualquier módulo, leer el doc correspondiente:

| Documento | Qué define |
|---|---|
| [`docs/arquitectura.md`](docs/arquitectura.md) | Diagrama de flujo completo del sistema |
| [`docs/contrato_cerebro.md`](docs/contrato_cerebro.md) | Schema de entrada/salida del cerebro, validaciones, fallback y casos borde |
| [`docs/indicadores.md`](docs/indicadores.md) | Períodos exactos de RSI, EMAs, ATR; lógica MTF; señal base |
| [`docs/system_prompt.md`](docs/system_prompt.md) | Diseño del prompt, tool definition, decisiones de temperatura y modelo |
| [`docs/log_schema.md`](docs/log_schema.md) | Tablas SQLite, columnas, índices y consultas de referencia |
| [`docs/paper_trader.md`](docs/paper_trader.md) | Reglas del simulador: sizing, stops, comisiones, slippage |
| [`docs/pares.md`](docs/pares.md) | Tabla de tickers activos y en prueba |

---

## Principios de arquitectura (respetar siempre)

1. **Separá lo determinístico del LLM.** El código maneja datos, indicadores, señales, ejecución y riesgo. El LLM solo razona sobre el contexto que recibe.
2. **El cerebro aconseja, no decide.** Puede vetar o reducir riesgo, nunca agrandarlo ni saltarse stops. Los límites duros los hace cumplir el código.
3. **Construir y validar en paper primero.** El cerebro se valida aislado antes de enchufarlo a cualquier flujo en vivo.

---

## Guardrails innegociables

- **CERO trading con plata real.** Solo paper / simulación en todo el proyecto.
- **Nunca hardcodear API keys.** Siempre desde variables de entorno (`.env` + `python-dotenv`).
- **El LLM solo opera sobre datos provistos.** Si el contexto es insuficiente, devuelve `neutral`.
- **Validar siempre el JSON del LLM** contra el schema antes de usar. Ante cualquier falla (malformado, fuera de rango, error de API) → default seguro (`neutral` / no operar). Nunca actuar sobre salida sin validar.
- **Temperatura baja** en todas las llamadas al LLM.
- **Loguear cada llamada** del cerebro en SQLite: contexto de entrada, salida cruda, decisión parseada.
- **Módulos separados** para lógica determinística y lógica LLM.

---

## Docker

El proyecto corre en Docker. Todos los comandos de ejecución van por `docker compose`.

```bash
# Construir la imagen
docker compose build

# Correr el comando activo (definido en docker-compose.yml)
docker compose run --rm brain

# Correr un script específico sin cambiar docker-compose.yml
docker compose run --rm brain python scripts/fase1_checkpoint.py
```

La base SQLite se persiste en `./data/` (volumen montado en `/app/data` del contenedor). Configurar `DB_PATH=/app/data/trading_brain.db` en `.env` al correr en Docker.

**Nunca** copiar `.env` dentro de la imagen — se pasa en runtime via `env_file` en `docker-compose.yml`.

---

## Stack

| Componente | Librería |
|---|---|
| Datos de mercado | `ccxt` |
| Indicadores | `pandas` + `pandas-ta` |
| LLM | SDK `anthropic` (Claude), **tool use** para JSON estructurado |
| Persistencia | `SQLite` |
| Config | `python-dotenv` |
| Notificaciones (fase 4+) | Telegram |
| Dependencias | `requirements.txt` |

---

## Decisiones clave de diseño

| Decisión | Valor |
|---|---|
| EMAs | 21 (rápida) / 50 (lenta) / 200 (solo 1D, referencia macro) |
| Análisis multi-timeframe | Top-down: **4H** (sesgo) → **1D** (estructura) → **1H** (entrada) |
| Señal base operativa | Cruza EMA(21)/EMA(50) en 1H + RSI > 50 / < 50 |
| Formato de salida del LLM | Tool use (schema forzado, no JSON mode) |
| Stop loss | 2× ATR desde el precio de entrada |
| Riesgo por trade | 1% del equity × `multiplicador_riesgo` |
| Exchange default | Binance spot (testnet) |

---

## Contrato del cerebro — resumen

> Spec completa en [`docs/contrato_cerebro.md`](docs/contrato_cerebro.md)

**Entrada:** contexto multi-timeframe (4H + 1D + 1H) con indicadores, estructura de precio, señal base y estado del portfolio.

**Salida:**
```json
{
  "regimen": "tendencia_alcista | tendencia_bajista | rango | volatil",
  "confianza_regimen": 0.0,
  "evaluacion_senal": "confirmar | vetar | neutral",
  "conviccion": 0.0,
  "multiplicador_riesgo": 0.0,
  "factores_clave": ["..."],
  "racional": "texto legible para Telegram",
  "alertas": ["..."]
}
```

`multiplicador_riesgo` en `[0.0, 1.0]` — nunca puede superar 1.0. Ante cualquier falla → fallback seguro (neutral, no operar).

---

## Fases de construcción

Trabajar **fase por fase**. Frenar en cada checkpoint para revisión antes de avanzar.

### Fase 0 — Scaffolding
Estructura del proyecto, `requirements.txt`, `.env.example`, `.gitignore`, lectura de API key desde entorno.

**Checkpoint:** el proyecto corre un "hola mundo" y lee la key del entorno.

### Fase 1 — Armador de contexto (sin LLM)
Función que baja las últimas 200 velas por timeframe (4H, 1D, 1H) con `ccxt`, calcula RSI, EMA(21), EMA(50), ATR y volumen con `pandas-ta`, arma la estructura básica y devuelve el dict de contexto MTF.

**Checkpoint:** imprime el contexto completo de la última vela 1H y se entiende solo.

### Fase 2 — El cerebro
Función `analizar(contexto) -> dict`: system prompt de analista, contexto MTF formateado, salida estructurada forzada (tool use), validación contra schema, default seguro ante cualquier falla.

**Checkpoint:** devuelve JSON válido con razonamiento coherente sobre 3–4 contextos reales distintos.

### Fase 3 — Validación pasiva (forward-only)
Harness que corre el cerebro en vivo (paper, sin operar) y loguea contexto + decisión + resultado posterior en SQLite. Validar **hacia adelante**, no sobre datos que el modelo ya "conoce".

**Checkpoint:** el log empieza a acumular registros.

### Fase 4 — Loop mínimo en paper
Scheduler por vela 1H → contexto MTF → estrategia base → si hay señal → cerebro → si confirma → simula el trade → log → (luego) Telegram.

**Checkpoint:** corre end-to-end en paper.

### Fase 5 (futura) — Iteración del prompt y métricas
Análisis del log, calibración del system prompt, métricas de calidad de decisión.

---

## Estructura de archivos

```
trading_brain/
├── .env.example
├── .gitignore
├── CLAUDE.md
├── requirements.txt
├── docs/
│   ├── arquitectura.md
│   ├── contrato_cerebro.md
│   ├── indicadores.md
│   ├── log_schema.md
│   ├── paper_trader.md
│   ├── pares.md
│   └── system_prompt.md
├── src/
│   ├── context_builder.py   # Fase 1 — lógica determinística (ccxt + pandas-ta)
│   ├── brain.py             # Fase 2 — lógica LLM (solo importa anthropic)
│   ├── strategy.py          # Fase 4 — señal base
│   ├── paper_trader.py      # Fase 4 — simulador de trades
│   ├── logger.py            # Fase 3+ — log en SQLite
│   └── scheduler.py         # Fase 4 — loop por vela
└── scripts/
    ├── hello.py             # Fase 0 — checkpoint de entorno
    └── validate_brain.py    # Fase 3 — harness de validación pasiva
```

---

## Convenciones de código

- Python 3.11+
- Type hints en todas las funciones públicas
- Logging con el módulo estándar `logging`, no `print` (excepto scripts de desarrollo)
- No mockear el LLM en tests de integración — probar contra la API real con contextos fijos
- `brain.py` no importa `ccxt` ni `pandas-ta`; `context_builder.py` no importa `anthropic`

---

## Variables de entorno requeridas

```
ANTHROPIC_API_KEY=           # Claude API
ANTHROPIC_MODEL=claude-sonnet-4-6  # modelo a usar (leer desde entorno en brain.py)
CCXT_EXCHANGE=binance        # exchange a usar
CCXT_TESTNET=true            # true para testnet / paper
CCXT_MARKET_TYPE=spot        # "spot" | "future"
DB_PATH=trading_brain.db     # archivo SQLite
PAPER_INITIAL_BALANCE=10000  # balance virtual en USDT
PAPER_RISK_PCT=0.01          # riesgo por trade (1%)
PAPER_ATR_STOP_MULT=2.0      # multiplicador ATR para el stop
PAPER_MAX_HOLD_CANDLES=20    # velas máximas antes de cerrar por timeout
```
