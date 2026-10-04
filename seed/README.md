# seed/ — catálogo base

Catálogo inicial de rubros, ítems, insumos y APU para vivienda, en CSV con
separador `;`. Es el punto de partida de la etapa 4: la app lo importa y de ahí
en adelante lo editás desde la interfaz.

| Archivo | Qué tiene |
|---|---|
| `rubros.csv` | 14 rubros, numerados al estilo de planilla de obra |
| `items.csv` | 15 ítems con su rubro y unidad de medida |
| `insumos.csv` | 34 insumos: material, mano de obra y equipo, con **desperdicio sugerido** y **múltiplo de compra** |
| `apu.csv` | 67 líneas de análisis de precio unitario: ítem → insumo → coeficiente |

Validación de integridad (se corre en CI más adelante):

```bash
python3 tools/prueba_cadena.py   # computo -> APU -> desperdicio -> redondeo -> precio real
```

## Hasta dónde llega y hasta dónde no

**Estos coeficientes son valores de manual, no tu práctica.** Están para que la
app arranque con algo real y para poder probar la cadena completa, no para que se
usen tal cual en un presupuesto que se firma. Lo primero que conviene hacer es
sentarse a corregirlos.

Los rubros **09 (sanitaria), 10 (eléctrica), 11 (gas), 12 (carpinterías) y
14 (limpieza)** están creados pero **sin ítems**: son los que más varían entre
profesionales y conviene cargarlos con tu criterio en vez de heredar los de un
manual. Por eso hay 10 insumos definidos y todavía sin usar.

## Decisiones que están incorporadas

- **El desperdicio va por insumo, no global.** El cerámico lleva 10 % y la
  membrana 15 % por los solapes; la mano de obra lleva 0.
- **El múltiplo de compra está en el insumo.** Cemento y cal en bolsas de 25 kg,
  pegamento de 30 kg, látex en baldes de 20 l. Eso es lo que permite pasar de
  "necesito 1.386 kg" a "comprá 56 bolsas".
- **La mano de obra se mide en horas**, no en jornales, para que el coeficiente
  de rendimiento sea comparable entre ítems.
