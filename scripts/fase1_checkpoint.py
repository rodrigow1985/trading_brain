"""
Checkpoint de Fase 1 — Armador de contexto.

Verifica que construir_contexto() devuelve un contexto válido y completo
para BTC/USDT con todos los campos requeridos por docs/contrato_cerebro.md.
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Configurar logging antes de importar el módulo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

# Asegurar que src/ esté en el path cuando se corre desde la raíz del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.context_builder import construir_contexto  # noqa: E402


# ---------------------------------------------------------------------------
# Verificaciones de campos requeridos
# ---------------------------------------------------------------------------

CAMPOS_RAIZ = ["par", "timestamp", "mercado_tipo", "senal_base", "portfolio", "timeframes"]
CAMPOS_PORTFOLIO = ["posicion_actual", "riesgo_disponible_pct"]
TIMEFRAMES_REQUERIDOS = ["4h", "1d", "1h"]
CAMPOS_INDICADORES_BASE = ["rsi", "ema_rapida", "ema_lenta", "atr", "volumen", "volumen_promedio"]
CAMPOS_INDICADORES_1D = CAMPOS_INDICADORES_BASE + ["ema_largo"]
CAMPOS_ESTRUCTURA = ["precio_actual", "maximos_recientes", "minimos_recientes", "tendencia"]


def verificar_contexto(ctx: dict) -> list[str]:
    """
    Verifica que el contexto tenga todos los campos requeridos y no sean None.
    Devuelve lista de errores (vacía si todo está bien).
    """
    errores: list[str] = []

    # Campos raíz
    for campo in CAMPOS_RAIZ:
        if campo not in ctx:
            errores.append(f"Campo raíz ausente: {campo!r}")
        elif ctx[campo] is None:
            errores.append(f"Campo raíz es None: {campo!r}")

    # Portfolio
    portfolio = ctx.get("portfolio", {})
    for campo in CAMPOS_PORTFOLIO:
        if campo not in portfolio:
            errores.append(f"portfolio.{campo} ausente")
        elif portfolio[campo] is None:
            errores.append(f"portfolio.{campo} es None")

    # Timeframes
    timeframes = ctx.get("timeframes", {})
    for tf in TIMEFRAMES_REQUERIDOS:
        if tf not in timeframes:
            errores.append(f"Timeframe ausente: {tf!r}")
            continue

        ctx_tf = timeframes[tf]

        # Indicadores
        campos_ind = CAMPOS_INDICADORES_1D if tf == "1d" else CAMPOS_INDICADORES_BASE
        indicadores = ctx_tf.get("indicadores", {})
        for campo in campos_ind:
            if campo not in indicadores:
                errores.append(f"timeframes[{tf!r}].indicadores.{campo} ausente")
            elif indicadores[campo] is None:
                errores.append(f"timeframes[{tf!r}].indicadores.{campo} es None")

        # Estructura
        estructura = ctx_tf.get("estructura", {})
        for campo in CAMPOS_ESTRUCTURA:
            if campo not in estructura:
                errores.append(f"timeframes[{tf!r}].estructura.{campo} ausente")
            elif estructura[campo] is None:
                errores.append(f"timeframes[{tf!r}].estructura.{campo} es None")

        # Longitud de listas de estructura
        for lista_campo in ["maximos_recientes", "minimos_recientes"]:
            lista = estructura.get(lista_campo, [])
            if len(lista) != 5:
                errores.append(
                    f"timeframes[{tf!r}].estructura.{lista_campo} debe tener 5 elementos"
                    f", tiene {len(lista)}"
                )

        # Tendencia válida
        tendencia = estructura.get("tendencia")
        if tendencia not in ("alcista", "bajista", "lateral"):
            errores.append(
                f"timeframes[{tf!r}].estructura.tendencia valor inválido: {tendencia!r}"
            )

        # RSI en rango
        rsi = indicadores.get("rsi")
        if rsi is not None and not (0.0 <= rsi <= 100.0):
            errores.append(f"timeframes[{tf!r}].indicadores.rsi fuera de rango: {rsi}")

    # senal_base válida
    senal = ctx.get("senal_base")
    if senal not in ("LONG", "SHORT", "NONE"):
        errores.append(f"senal_base valor inválido: {senal!r}")

    # mercado_tipo válido
    mercado = ctx.get("mercado_tipo")
    if mercado not in ("spot", "futuro"):
        errores.append(f"mercado_tipo valor inválido: {mercado!r}")

    return errores


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("CHECKPOINT FASE 1 — Armador de contexto")
    print("=" * 70)
    print()

    print("Llamando a construir_contexto('BTC/USDT', 'spot', 'NONE', 1.0) ...")
    print()

    ctx = construir_contexto("BTC/USDT", "spot", "NONE", 1.0)

    print()
    print("=" * 70)
    print("CONTEXTO COMPLETO")
    print("=" * 70)
    print(json.dumps(ctx, indent=2, ensure_ascii=False))
    print()

    print("=" * 70)
    print("VERIFICACIÓN DE CAMPOS")
    print("=" * 70)

    errores = verificar_contexto(ctx)

    if errores:
        print(f"\n❌ Se encontraron {len(errores)} error(es):\n")
        for err in errores:
            print(f"  • {err}")
        sys.exit(1)
    else:
        print("\nTodos los campos requeridos están presentes y no son None.")
        print("\nResumen del contexto:")
        print(f"  par:           {ctx['par']}")
        print(f"  timestamp:     {ctx['timestamp']}")
        print(f"  mercado_tipo:  {ctx['mercado_tipo']}")
        print(f"  senal_base:    {ctx['senal_base']}")
        print(f"  posicion:      {ctx['portfolio']['posicion_actual']}")
        print(f"  riesgo_disp:   {ctx['portfolio']['riesgo_disponible_pct']}")
        print()
        for tf in TIMEFRAMES_REQUERIDOS:
            ind = ctx["timeframes"][tf]["indicadores"]
            est = ctx["timeframes"][tf]["estructura"]
            print(f"  [{tf}]")
            print(f"    RSI:       {ind['rsi']:.2f}")
            print(f"    EMA21:     {ind['ema_rapida']:.2f}")
            print(f"    EMA50:     {ind['ema_lenta']:.2f}")
            if tf == "1d":
                print(f"    EMA200:    {ind['ema_largo']:.2f}")
            print(f"    ATR:       {ind['atr']:.4f}")
            print(f"    Volumen:   {ind['volumen']:.2f}")
            print(f"    Vol.Prom:  {ind['volumen_promedio']:.2f}")
            print(f"    Precio:    {est['precio_actual']:.2f}")
            print(f"    Tendencia: {est['tendencia']}")
            print()

        print("CHECKPOINT FASE 1: PASÓ")


if __name__ == "__main__":
    main()
