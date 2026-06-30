"""
Consulta manual al cerebro — Fase 4+.

Baja el contexto MTF actual y pregunta al cerebro si una señal dada es buena idea.
Útil para consultas ad-hoc sin esperar el cierre de vela del scheduler.

Uso:
    docker compose run --rm brain python scripts/consultar_cerebro.py --senal LONG
    docker compose run --rm brain python scripts/consultar_cerebro.py --senal SHORT --par ETH/USDT
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src import notifier
from src.brain import analizar
from src.context_builder import construir_contexto

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def _imprimir_decision(par: str, senal: str, contexto: dict, decision: dict) -> None:
    tf1h = contexto["timeframes"]["1h"]
    precio = float(tf1h["estructura"]["precio_actual"])
    rsi    = float(tf1h["indicadores"]["rsi"])

    regimenes = {
        "tendencia_alcista": "Tendencia alcista",
        "tendencia_bajista": "Tendencia bajista",
        "rango":             "Lateral (rango)",
        "volatil":           "Volátil",
    }
    evaluaciones = {
        "confirmar": "CONFIRMA",
        "vetar":     "VETA",
        "neutral":   "NEUTRAL",
    }

    eval_str  = evaluaciones.get(decision["evaluacion_senal"], decision["evaluacion_senal"])
    reg_str   = regimenes.get(decision["regimen"], decision["regimen"])
    mult      = decision["multiplicador_riesgo"]
    conviccion = decision["conviccion"]
    racional  = decision["racional"]
    alertas   = decision["alertas"]

    print()
    print("=" * 60)
    print(f"  Consulta manual — {par}  |  señal: {senal}")
    print("=" * 60)
    print(f"  Precio actual : {precio:,.2f} USDT")
    print(f"  RSI 1H        : {rsi:.1f}")
    print(f"  Régimen       : {reg_str}")
    print(f"  Cerebro       : {eval_str}")
    print(f"  Convicción    : {conviccion:.0%}")
    print(f"  Riesgo autor. : {mult * 100:.0f}%")
    print()
    print(f"  Racional:")
    print(f"    {racional}")
    if alertas:
        print()
        print("  Alertas:")
        for a in alertas:
            print(f"    · {a}")
    print("=" * 60)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consulta manual al cerebro — pregunta si una señal dada es buena ahora mismo."
    )
    parser.add_argument(
        "--senal",
        required=True,
        choices=["LONG", "SHORT"],
        help="Señal a evaluar: LONG o SHORT",
    )
    parser.add_argument(
        "--par",
        default=os.environ.get("TRADING_PAR", "BTC/USDT"),
        help="Par a consultar (default: BTC/USDT o TRADING_PAR del entorno)",
    )
    parser.add_argument(
        "--mercado",
        default=os.environ.get("CCXT_MARKET_TYPE", "spot"),
        choices=["spot", "future", "futuro"],
        help="Tipo de mercado (default: spot)",
    )
    args = parser.parse_args()

    senal    = args.senal
    par      = args.par
    mercado  = "futuro" if args.mercado == "future" else args.mercado

    log.info("Descargando contexto MTF para %s (%s)...", par, mercado)
    try:
        contexto = construir_contexto(
            par=par,
            mercado_tipo=mercado,
            posicion_actual="NONE",
            riesgo_disponible_pct=1.0,
        )
    except Exception as exc:
        log.error("Error construyendo contexto: %s", exc)
        sys.exit(1)

    # Inyectar la señal manual en el contexto
    contexto["senal_base"] = senal
    log.info("Contexto listo. Consultando al cerebro con señal=%s...", senal)

    t0 = time.monotonic()
    decision = analizar(contexto)
    latency_ms = int((time.monotonic() - t0) * 1000)

    log.info("Respuesta del cerebro en %d ms", latency_ms)

    _imprimir_decision(par, senal, contexto, decision)

    # Notificar a Telegram si está configurado
    try:
        precio = float(contexto["timeframes"]["1h"]["estructura"]["precio_actual"])
        rsi    = float(contexto["timeframes"]["1h"]["indicadores"]["rsi"])
        notifier.notificar_senal(
            par=par,
            senal=senal,
            precio=precio,
            rsi=rsi,
            regimen=decision["regimen"],
        )
        notifier.notificar_decision(
            par=par,
            senal=senal,
            evaluacion=decision["evaluacion_senal"],
            multiplicador=decision["multiplicador_riesgo"],
            conviccion=decision["conviccion"],
            racional=decision["racional"],
            alertas=decision["alertas"],
        )
    except Exception as exc:
        log.warning("Error enviando notificación Telegram: %s", exc)


if __name__ == "__main__":
    main()
