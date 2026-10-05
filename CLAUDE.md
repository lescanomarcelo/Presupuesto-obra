# Presupuesto de Obra — contexto del proyecto

App de **escritorio para Windows** que abre un plano (DXF / DWG / IFC), permite
**medir de forma asistida**, busca precios de materiales en internet y produce un
**presupuesto completo** exportable a CSV.

**Estado: planificación cerrada y verificada. La etapa 0 no empezó.** Todavía no
hay código de la aplicación: lo que hay es el plan, el catálogo base y cinco
herramientas de verificación que ya corrieron contra datos reales.

`PLAN.md` es el documento maestro (17 secciones). Este archivo es el resumen
operativo: leé esto antes de tocar nada.

---

## Reglas que NO se deben romper

Cada una costó encontrarla midiendo, y varias fallan **en silencio**. El número
entre paréntesis es el error medido si se ignora la regla.

### IFC

- **El cómputo usa la GEOMETRÍA, nunca `BaseQuantities`** (+730 %). Revit parte
  los elementos y reparte el Qto de forma inconsistente: en `IfcWall` lo repite
  en cada pedazo, en `IfcWallStandardCase` lo divide, y los dos casos se ven
  idénticos en el archivo. El Qto se muestra solo como control informativo.
- **No intentar "arreglar" el Qto deduplicando.** Agrupar por `Tag` arregla los
  muros (+5,7 %) y rompe los pilares (−76 %). No hay heurística válida.
- **Pedir la representación `Body` explícitamente.** `create_shape(s, elem)` sin
  representación falla en todos los muros de Revit, porque intenta procesar el
  `Axis` (un `Curve2D`). Y `geom.iterator` es peor: devuelve geometría **parcial
  sin lanzar excepción** (3,72 m³ contra 1,54 reales).
- **Aplicar `shape.transformation.matrix`.** `geometry.verts` viene en
  coordenadas **locales**. Sin la matriz todo se apila en el origen. **El bug no
  afecta los volúmenes** —son invariantes a la posición— así que el cómputo puede
  estar perfecto y la planta completamente mal.
- **Área de revoque = `2 × get_max_side_area`.** Nunca `get_side_area`, que
  depende de la orientación (11x de error en un muro girado 90°), ni `get_area`,
  que son las 6 caras (2,25x). `get_footprint_perimeter` no es confiable.
- **Retener el objeto `file` de ifcopenshell** mientras se usen sus entidades, o
  el kernel C++ lee memoria liberada y el proceso muere con **SIGSEGV**, sin
  excepción atrapable. Por eso la geometría IFC debe correr **en subproceso**.
- **No usar `ifcopenshell.draw`** (0.9.0): contra un modelo real muere sin traza
  o lanza `TypeError`/`AttributeError` según el filtro. La planta se construye
  con shapely en `tools/planta_ifc.py`.
- Al leer el Qto para el control, aceptar **`NetVolume` o `GrossVolume`**: faltan
  265 `NetVolume` de 1.383 pilares.

### Precios

- **Neto = `Price / (1 + IVA)`, siempre y para toda fuente.** NO usar
  `price_wo_taxes` de VTEX: se deriva de `ListPrice`, así que en un producto en
  oferta sobrevalúa el neto hasta **43 %**. Sirve solo para confirmar la alícuota.
- **El campo `Tax` de VTEX no sirve para nada**: devuelve `0.0` con el IVA
  incluido. Leerlo como "sin IVA" es un error del 21 %.
- **WooCommerce devuelve el precio en unidades mínimas**: `"price": "729979"` con
  `currency_minor_unit: 2` es $7.299,79. Dividir por `10**minor_unit`.
- **Normalizar ANTES de comparar**, y **nunca descartar atípicos**: un valor raro
  casi siempre es otra unidad de venta, y el "atípico de 72x" resultó ser el
  pallet, un 10 % más barato que la mediana.
- La banda de consenso se calcula **por zona**: Córdoba cotiza ~13 % arriba de
  AMBA. Y **debajo** del vínculo insumo↔SKU confirmado, nunca arriba.
- `html.unescape()` al ingestar nombres: WooCommerce manda `&#8211;`.

### Cómputo y presupuesto

- **Desperdicio por insumo**, no global, en `apu_detalle`. Sin él el presupuesto
  sale corto siempre.
- **Redondeo a unidad de compra**: no se compran 37,4 bolsas de cemento. El
  informe lleva tres cantidades: neta, con desperdicio, y a comprar.
- **La `medicion` guarda el contenedor** (layout en DXF, nivel en IFC), o se mide
  dos veces el mismo muro en la planta y en el corte.
- **El presupuesto congela los precios que usó.** Si leyera el histórico vivo, un
  presupuesto de marzo mostraría precios de octubre. Re-valorizar crea una
  versión nueva.
- **Las alícuotas viven en `proyecto.db`**, no en la base global: cambian por obra
  y quedan congeladas con el presupuesto.
- **CSV para Excel es-AR**: separador `;` y UTF-8 **con BOM**. Google Sheets
  quiere lo contrario, así que hay dos presets.

---

## Decisiones tomadas (no re-litigar)

| | |
|---|---|
| Plataforma | Escritorio, **solo Windows**. PyInstaller + Inno Setup |
| Stack | Python 3.12 + **PySide6**. `ezdxf` 1.4.x, `ifcopenshell` 0.9.0, `shapely`, SQLite |
| Entrada | DXF e **IFC son los dos de primera clase**. DWG pide exportar a DXF |
| Medición | **Asistida**: la app mide, el usuario confirma qué es cada cosa |
| Precios | Scraping/API, con **tres niveles de fuente**: AUTOMÁTICA, HTML, LINK |
| Organización | **Una carpeta por obra**, visible en el explorador |
| Moneda | Pesos, con total en USD al **oficial** (`dolarapi.com`) |
| Alcance | Materiales + mano de obra + equipos + gastos generales |
| Salida | **CSV** (PDF más adelante) |
| Zona | **Córdoba** por defecto |

Regla de oro de arquitectura: **`measure/`, `pricing/` y `budget/` son Python puro
y testeable.** Si para probar un cómputo hace falta abrir una ventana, el diseño
está mal. Solo `ui/` necesita Qt.

---

## Dónde está cada cosa

```
PLAN.md                 documento maestro, 17 secciones. §17 es la errata
CLAUDE.md               este archivo
seed/                   catálogo base: 14 rubros, 15 ítems, 34 insumos, 67 APU
tools/                  5 herramientas de verificación, solo stdlib + libs del stack
ejemplos/villa-giardino/ modelo real de Revit + sus salidas = test de regresión
```

## Cómo correr las herramientas

```bash
python tools/relevar_fuentes.py                        # plataforma de cada corralón
python tools/comparar_precios.py                       # canasta comparada, con atípicos
python tools/verificar_fuente.py merlinosrl.com.ar     # nivel de UNA fuente
python tools/prueba_cadena.py                          # cómputo -> APU -> desperdicio -> precio
python tools/prueba_ifc.py                             # 4 casos de IFC, debe decir TODO OK
python tools/analizar_ifc.py <archivo.ifc> --geom      # analiza un IFC real
python tools/planta_ifc.py <archivo.ifc> "Nivel 0"     # planta en SVG
```

Los valores esperados están en `ejemplos/villa-giardino/README.md`.

## Qué NO commitear

- **`Presupuestos/`** — las carpetas de obra que genera la app, con datos de
  clientes reales. Está en `.gitignore`.
- Cualquier `.ifc` o `.dxf` de un comitente que no sea caso de prueba acordado.

## Fuentes de precios verificadas

**Con API pública (nivel AUTOMÁTICA):** `easy.com.ar` y `colorshop.com.ar` (VTEX),
`merlinosrl.com.ar` (VTEX, Córdoba), y cinco en WooCommerce Store API:
`laeconomica.com.ar`, `latejamateriales.com`, `centralmaterialesya.com`,
`germatsrl.com`, `grupocanarias.com.ar`.

**Nivel HTML (selectores por sitio, no por plataforma):** `casamanrique.com.ar`,
`ferrocons.com.ar`, `terralon.com.ar` — los tres de Córdoba.

**Nivel LINK:** `edificor.com` (es VTEX pero con la API de catálogo en 404).

Un endpoint VTEX responde **HTTP 206** al paginar, no 200: exigir 200 descarta
fuentes que funcionan.

## Próximo paso

**Etapa 0 y 0b**: esqueleto del proyecto y "proyecto = carpeta". Después la
etapa 1, el visor DXF, que es el hito que valida el enfoque con planos reales.
De los dos lectores, **el DXF es el que todavía no se probó con nada real** y es
el que concentra los dos riesgos más altos del plan: planos sin convención de
capas y polilíneas no cerradas.
