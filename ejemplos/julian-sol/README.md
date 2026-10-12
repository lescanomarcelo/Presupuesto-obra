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

Pero la semántica existe en otros canales: nombres de bloque (`puerta 2` ×12,
`BID_ bathroom_ wc03` ×5, y muebles a excluir), patrones de hatch (`GRASS` 36,46
m² es terreno, no piso) y firma geométrica (4 cerradas de 0,160 m² = pilares de
0,40×0,40).

## Nota

Es un plano real. Si el repositorio se hace público, conviene sacarlo.
