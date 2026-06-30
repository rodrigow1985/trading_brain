# Arquitectura — Trading Brain

```mermaid
flowchart TD
    subgraph EXTERNO["Externo"]
        EX[("Binance / ccxt")]
        CLAUDE_API[["Claude API / anthropic SDK"]]
        TG["Telegram (fase 4+)"]
    end

    subgraph DET["Capa Determinística"]
        CB["context_builder.py<br/>Descarga velas<br/>Calcula RSI, EMAs, ATR, volumen<br/>Arma dict de contexto"]
        ST["strategy.py<br/>Señal base: LONG / SHORT / NONE"]
        PT["paper_trader.py<br/>Simula trade<br/>Aplica multiplicador_riesgo<br/>Actualiza portfolio"]
    end

    subgraph LLM["Capa LLM — brain.py"]
        PR["System prompt de analista"]
        TU["Tool use → JSON forzado"]
        VAL{"Validar schema"}
        DEF["Default seguro<br/>neutral / no operar"]
    end

    subgraph INFRA["Infraestructura"]
        SCH["scheduler.py<br/>Loop por vela"]
        LOG[("SQLite / logger.py<br/>contexto in · raw output · decisión")]
    end

    EX -->|"velas OHLCV"| CB
    CB -->|"contexto dict"| ST
    ST -->|"señal base"| SIG{{"¿Hay señal?"}}
    SIG -->|"NO"| LOG
    SIG -->|"SÍ"| PR
    PR --> TU
    TU -->|"llamada API"| CLAUDE_API
    CLAUDE_API -->|"JSON raw"| VAL
    VAL -->|"válido"| EVAL{{"evaluacion_senal"}}
    VAL -->|"falla / error"| DEF
    DEF --> LOG
    EVAL -->|"vetar / neutral"| LOG
    EVAL -->|"confirmar"| PT
    PT --> LOG
    LOG --> TG
    SCH -->|"tick por vela"| CB

    style LLM fill:#1a1a2e,color:#e0e0ff,stroke:#7070ff
    style DET fill:#0d2137,color:#e0f0ff,stroke:#4090c0
    style INFRA fill:#1a2a1a,color:#e0ffe0,stroke:#409040
    style EXTERNO fill:#2a1a1a,color:#ffe0e0,stroke:#c04040
```

> **Simplificación del diagrama:** el flujo `SIG → NO → LOG` omite el caso en que haya una posición abierta y la señal desaparezca (`senal_base = "NONE"`). En ese caso el paper trader evalúa el cierre por `SIGNAL_CLOSE` o `TIMEOUT` antes de ir al log. Esta lógica vive en `paper_trader.py` y está documentada en `paper_trader.md`.
