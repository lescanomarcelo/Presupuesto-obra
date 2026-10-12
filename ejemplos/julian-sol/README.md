# julian_sol.dxf — plano real de verificación

AutoCAD 2018 (`AC1032`), 345 entidades en modelspace, 2 layouts de papel.
Vivienda con lote.

```
python3 tools/analizar_dxf.py ejemplos/julian-sol/julian_sol.dxf
```

## Valores de referencia

| | |
|---|---|
| `$INSUNITS` | `4` = **milímetros — ES INCORRECTO**, el dibujo está en metros |
| Extensión | 15,90 × 25,81 m |
| Capas con contenido | **1** (la capa `0`) |
| Entidades | `LINE` 255, `INSERT` 27, `HATCH` 24, `DIMENSION` 19, polilíneas 9 |
| Polilíneas cerradas | 7, área total 8,04 m² |
| Polilíneas abiertas | 2 (ninguna "casi cerrada") |
| Bloques distintos | 12, con 27 inserciones |
| Suma de longitudes | 481,99 m |

Cotas leídas: 1,80 / 0,80 / 1,00 / 3,10 / 2,90 / 5,16 m. Son metros redondos y
una puerta de 0,80 lo confirma.

## Por qué este plano vale como caso de prueba

Es el **peor caso** del plan y apareció en el primer archivo real:

1. **El header miente**: declara milímetros, está en metros. Las cotas lo
   resuelven, lo que permite detección automática de unidades.
2. **Todo en la capa `0`**: la asignación capa→ítem no sirve.
3. **Los muros son `LINE` sueltas**, no polilíneas: medir longitud exige
   emparejar las dos caras.

Y lo que la detección encuentra es casi todo mobiliario. **El autor del plano
identificó los 7 elementos detectados** y solo uno es presupuestable:

| Marca | Detectado | Es |
|---|---|---|
| A | hatch `GRASS` 36,46 m² | Jardín |
| **B** | **hatch `SOLID` 13,14 m²** | **Piso** ← el único presupuestable |
| C1–C4 | 4 cerradas de 0,40 × 0,40 | Accesorios (mesas de luz), **no pilares** |
| E1, E2 | cerradas de 4,00 y 2,80 m² | Camas |
| E3 | cerrada de 0,60 m² | Bacha |
| ○ | 12 bloques `puerta 2` | **fuera del plano**, el autor no los ve |

4. **`$EXTMIN`/`$EXTMAX` está desactualizado**: declara 15,9 × 25,8 pero hay
   entidades a 2.500 unidades. La arquitectura real son las 255 `LINE`, que miden
   **14,46 × 25,81 m**. Hay **17 `INSERT` lejos del cúmulo principal** (las 12
   puertas y 5 muebles) que se habrían presupuestado como obra.
5. **La firma geométrica no sirve como clasificador**: un cuadrado de 0,40 puede
   ser un pilar o un velador.

## Nota

Es un plano real. Si el repositorio se hace público, conviene sacarlo.

## Detección de muros, calibrada contra el autor

```
python3 tools/detectar_muros.py ejemplos/julian-sol/julian_sol.dxf --svg muros.svg
```

| | Primera versión | Actual |
|---|---|---|
| Muros | 48 | **61** |
| Largo total | 142,75 m | **157,94 m** |
| Espesor 0,20 m | 17 muros, 91,49 m | 18 muros, 93,27 m |
| Espesor 0,10 m | 16 muros, 23,15 m | 17 muros, 23,75 m |
| Líneas duplicadas | no se veían | **9 descartadas** |
| Sospechosos marcados | 9 | 7 |

El autor verificó la primera corrida: **los 9 sospechosos eran falsos positivos**
(un placard, el borde de una pileta), y **el muro de 25,61 m es perimetral real**.
