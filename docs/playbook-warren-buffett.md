# Playbook Warren Buffett (Value Investing) — versión destilada

Destilado de `Warren Buffett.pdf` ("De la Teoría al Accionamiento: Un Marco Práctico de Inversión según Warren Buffett") para uso como contexto fijo en prompts automatizados. Conserva las fórmulas y umbrales cuantitativos; descarta anécdotas y citas.

## Fase I — Círculo de competencia
¿Es un negocio simple, predecible, comprensible sin depender de pronósticos tecnológicos? Si la narrativa del negocio es ambigua o depende de tendencias/hype, queda fuera del círculo → descartar sin seguir analizando.

## Fase II — Moat (ventaja competitiva duradera)
Fuentes de moat: marca poderosa, ventaja de costos, redes/costos de cambio, barreras regulatorias.

Métricas para verificarla (deben ser consistentes en el tiempo, no solo en años buenos):

| Métrica | Señal de moat real |
|---|---|
| Margen bruto | Alto y estable → poder de fijación de precios |
| Margen operativo | Consistentemente superior al del sector |
| ROIC | Ampliamente superior al WACC (costo de capital) |
| ROE | Elevado y estable vs. sector |
| Crecimiento de EPS/ingresos | Sostenido a lo largo de varios años, incluso en recesiones |

Sin moat duradera → descartar, sin importar cuán barata esté la acción.

## Fase III — Calidad de gestión (Test del Dólar Retenido)
Regla central: cada dólar retenido por la empresa debe crear ≥ 1 dólar de valor de mercado para el accionista. Si no, debería salir como dividendo o recompra.

Evaluar 4 comportamientos del management:
1. **Reinvertir** solo en proyectos de alto retorno (red flag: "empire-building"/adquisiciones para crecer porque sí).
2. **Adquisiciones** disciplinadas, a precio justo, con moat propia.
3. **Recompras de acciones** solo cuando el precio de mercado está bien por debajo del valor intrínseco (no recomprar caro — caso negativo histórico: Bank of America 1995-2007).
4. **Dividendos** consistentes cuando no hay mejor uso del capital.

## Fase IV — Valoración y margen de seguridad

**Owner Earnings** (proxy del flujo de caja real para el dueño):
```
Owner Earnings = Net Income + Depreciación/Amortización − CapEx de mantenimiento
```

**Valor intrínseco** ≈ Owner Earnings normalizadas (promedio de varios años) × múltiplo, según calidad de la moat:

| Calidad de la empresa | Crecimiento esperado | Múltiplo sugerido |
|---|---|---|
| Moat ancha, negocio ligero en activos | 5%+ | 20x–25x |
| Moat sólida | Moderado (3-5%) | 15x–20x |
| Moat media | Bajo | 10x–15x |
| Moat estrecha / amenazas competitivas | Variable | 8x–12x |
| Negocio cíclico o en declive | N/A | <8x |

**Margen de seguridad** — descuento exigido sobre el valor intrínseco antes de comprar:
- Empresa excepcional y predecible (ej. tipo Coca-Cola): **20-30%** de descuento alcanza.
- Empresa con más incertidumbre: exigir **40-50%** de descuento.
- Si el valor intrínseco no se puede estimar con confianza razonable → **no invertir**.

## Fase V — Entrada escalonada en DCA

```
Precio Máximo de Adquisición = Valor Intrínseco × (1 − Margen de Seguridad)
```

Niveles de entrada sugeridos (sobre el Precio Máximo = Pmax):

| Nivel | Rango de precio | Función |
|---|---|---|
| 1 — Entrada principal | Pmax a Pmax×0.90 | Primera acumulación |
| 2 — Acumulación agresiva | Pmax×0.90 a Pmax×0.80 | Corrección moderada |
| 3 — Compra final | Pmax×0.80 a Pmax×0.70 | Corrección profunda |
| 4 — Oportunidad mayor (opcional) | < Pmax×0.70 | Caída drástica |

Asignar montos fijos por nivel (ej. capital total / 3 o /4 niveles), no todo de una vez.

## Veredicto final
Combinar las 5 fases en una conclusión: COMPRARÍA (con niveles DCA) / NO COMPRARÍA (sin moat o sin margen de seguridad) / ESPERAR CORRECCIÓN (buen negocio, precio caro).
