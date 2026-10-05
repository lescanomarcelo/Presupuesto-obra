# Presupuesto de Obra

Aplicación de escritorio para Windows que toma un plano —**DXF** de AutoCAD o
**IFC** exportado de Revit— mide de forma asistida sobre él, busca precios de
materiales en los corralones y produce un presupuesto completo, exportable a CSV
para abrir en Excel o Google Sheets.

> **Estado: planificación cerrada y verificada contra datos reales. La etapa 0
> todavía no empezó.** No hay código de la aplicación: hay un plan, un catálogo
> base y cinco herramientas de verificación que ya corrieron.

## Por dónde empezar

| Si querés… | Leé |
|---|---|
| entender el proyecto completo | `PLAN.md` — 17 secciones |
| saber qué NO romper | **`CLAUDE.md`** — las reglas medidas |
| ver qué se verificó y qué no | `PLAN.md` §17, la errata |
| correr algo ya mismo | `tools/README.md` |

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

## Probar que todo funciona

```bash
python tools/prueba_ifc.py          # debe decir TODO OK
python tools/prueba_cadena.py       # cómputo -> APU -> desperdicio -> precio real
python tools/analizar_ifc.py ejemplos/villa-giardino/Villa_Giardino_solo_en_PB.ifc --geom
```

El último tiene que reproducir los valores de
`ejemplos/villa-giardino/README.md`: 2.274 elementos, **15,646 m³** en total, y
el aviso de que `IfcWall` difiere +730 % entre el Qto de Revit y la geometría.

## Lo que ya está verificado con datos reales

- **8 fuentes de precios con API pública**, relevadas sobre 29 sitios argentinos:
  3 en VTEX y 5 en la Store API de WooCommerce. Dos adapters las cubren todas.
- **El camino IFC completo**, contra un export real de Revit 2023: lectura,
  cantidades, geometría con huecos descontados, posición y planta navegable.
- **La cadena de cálculo**: cómputo → APU → desperdicio → redondeo a bolsas →
  precio real de un corralón de Córdoba → conversión a dólares.

## Próximo paso

Etapas 0 y 0b (esqueleto y "proyecto = carpeta"), y después la etapa 1: el visor
DXF. **El DXF es el único camino que todavía no se probó con un archivo real**, y
concentra los dos riesgos más altos del plan.
