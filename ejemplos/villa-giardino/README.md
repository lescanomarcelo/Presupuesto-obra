# Villa Giardino — modelo real de verificación

Export de **Revit 2023 (ESP)**, IFC2X3, 5,6 MB, 24.108 entidades, 2.274
elementos medibles. Vivienda de estructura de madera con bastidores.

Es el único modelo real que validó el camino IFC de punta a punta, y los números
de abajo son el **test de regresión**: si un cambio en `tools/` los altera, el
cambio está mal.

## Valores de referencia

```
python3 tools/analizar_ifc.py ejemplos/villa-giardino/Villa_Giardino_solo_en_PB.ifc --geom --limite 2000
```

| Clase | n | Geometría | Qto (control) | Dif |
|---|---|---|---|---|
| `IfcWall` | 48 | **1,542 m³** | 12,795 | **+729,8 %** |
| `IfcWallStandardCase` | 132 | 2,183 m³ | 2,183 | +0,0 % |
| `IfcSlab` | 28 | 2,614 m³ | 2,614 | +0,0 % |
| `IfcBeam` | 654 | 5,377 m³ | 5,377 | −0,0 % |
| `IfcColumn` | 1.383 | 3,266 m³ | 3,270 | +0,1 % (265 sin `NetVolume`) |
| `IfcBuildingElementProxy` | 29 | 0,664 m³ | — | sin Qto |
| **TOTAL** | **2.274** | **15,646 m³** | | |

Esquema `IFC2X3`, unidad `METRE`, **18 niveles**.

```
python3 tools/planta_ifc.py ejemplos/villa-giardino/Villa_Giardino_solo_en_PB.ifc "Nivel 0"
# planta_Nivel_0.svg: 416/416 elementos, 9.95 x 11.41 m
```

## Por qué este modelo vale como caso de prueba

Rompió cuatro suposiciones que los modelos sintéticos no podían romper:

1. **El `IfcWall` difiere +730 %.** Revit partió 7 muros en 48 pedazos y copió
   el `BaseQuantities` completo en cada pedazo. La prueba de que la geometría es
   la correcta: los 11 pedazos del muro `670545` suman exactamente el único valor
   de Qto que comparten (0,4127 m³).
2. **La inconsistencia no tiene regla.** `IfcWall` repite el Qto entre pedazos;
   `IfcWallStandardCase` lo reparte. Se ven idénticos en el archivo. Deduplicar
   por `Tag` arregla los muros (+5,7 %) y rompe los pilares (−76 %).
3. **`create_shape` falla en todos los muros** si no se le pide la
   representación `Body`: intenta procesar el `Axis`, que es un `Curve2D`. Y
   `geom.iterator` devuelve geometría parcial **sin lanzar excepción**: 3,72 m³
   contra 1,54 reales.
4. **`ifcopenshell.draw` 0.9.0 no sirve** contra este modelo: sin filtros el
   proceso muere sin traza; con `storey_filter` lanza `TypeError`; con
   `include_entities` lanza `AttributeError`. De ahí que la planta se construya
   con shapely en `tools/planta_ifc.py`.

## Pendiente de interfaz que dejó a la vista

Los 18 niveles son casi todos **auxiliares de armado** —*Pilotes inf*,
*Correas Piso (PARA LAMINA)*, *Corta fuegos inf*, *Dintel Bastidor este*—, y
solo *Nivel 0* es planta real. Agrupar el cómputo por nivel no sirve como viene:
la app tiene que dejar marcar cuáles son niveles reales.

| Nivel | Elementos |
|---|---|
| Nivel 0 | 416 |
| Corta fuegos inf | 368 |
| Corta fuego central | 333 |
| Dintel Bastidor este | 225 |
| Umblar de Bastidor este | 211 |
| … 13 niveles más | |
| Correas Techo | 0 |

## Nota

Es un proyecto real. Está versionado acá porque es el único caso de prueba con
datos de verdad; si el repositorio se hace público, conviene dejar el `.ifc`
afuera y conservar solo las salidas derivadas.
