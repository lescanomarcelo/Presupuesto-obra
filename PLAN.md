# Presupuesto de Obra — Plan de desarrollo

Aplicación **de escritorio para Windows** que abre un plano (DXF / DWG / IFC),
permite **medir de forma asistida** sobre él, **busca precios de materiales en
internet**, y produce un **presupuesto completo** exportable a **CSV** para
importar en Excel o Google Sheets.

> Revisión 2 — incorpora: IFC vía exportación, búsqueda de precios online,
> alcance de presupuesto completo, instalable Windows y salida CSV.

---

## 1. Decisiones tomadas

| Decisión | Elección | Consecuencia |
|---|---|---|
| Plataforma | **App de escritorio, solo Windows** | Un `.exe` con instalador. Es donde vive AutoCAD/Revit |
| Entrada | DXF + DWG (AutoCAD) e **IFC exportado** de Revit | Tres pipelines, prioridades distintas (§3) |
| Revit | **IFC exportado**, no `.rvt` nativo | Evita plugin C# y licencia de Revit. `ifcopenshell` es libre |
| Medición v1 | **Medición asistida** | La app mide y calcula; vos confirmás qué es cada cosa |
| **Precios** | **Scraping / API de retail online** | Módulo nuevo, es la parte más delicada del proyecto (§6) |
| **Alcance** | **Materiales + mano de obra + equipos + gastos generales** | Presupuesto formal con coeficiente de impacto (§7) |
| **Salida** | **CSV** (+ PDF opcional más adelante) | Importable en Excel y Google Sheets (§8) |

---

## 2. Stack

**Python 3.12 + Qt (PySide6).** Las dos librerías que resuelven el 80% del
problema son Python-first y no tienen equivalente maduro en otro lenguaje.

| Pieza | Librería | Qué aporta |
|---|---|---|
| Lectura DXF | `ezdxf` 1.4.x | Entidades, capas, bloques, textos, unidades |
| **Visor del plano** | `ezdxf.addons.drawing` (`PyQtBackend`, `qtviewer.py`) | **Visor CAD con pan/zoom ya implementado** |
| Lectura IFC | `ifcopenshell` 0.9 | Objetos BIM con áreas y volúmenes ya calculados |
| Geometría | `shapely` | Áreas, cierre de contornos, validación |
| Base de datos | SQLite + SQLAlchemy | Local, un archivo, cero servidor |
| **HTTP precios** | `httpx` | Async, timeouts y reintentos decentes |
| **Scraping HTML** | `selectolax` o `beautifulsoup4` | Solo para fuentes sin API (§6) |
| Export | `csv` (stdlib) | Es todo lo que hace falta para el informe |
| Empaquetado | **PyInstaller + Inno Setup** | `.exe` + instalador Windows con accesos y desinstalador |

**Verificado:** el add-on `drawing` de ezdxf incluye `qtviewer.py`, descrito en la
documentación oficial como *"the core of a simple DXF viewer"*, más un ejemplo
`cad_viewer.py` ejecutable. El visor —que parecía la parte más cara— se deriva de
ahí; encima le agregamos selección y medición.

---

## 3. Los tres formatos de plano

### DXF — prioridad 1, es el camino real
Formato abierto. `ezdxf` lo lee nativamente (R12 a R2018) y tiene
`recover.readfile()` para archivos corruptos, que en la práctica son muchos. Todo
el motor de medición se desarrolla contra DXF.

### IFC — prioridad 2, es el caso *ideal*
Un IFC de Revit no tiene líneas: tiene **muros, losas y pisos como objetos**, con
sus `BaseQuantities` (área, volumen, longitud) **ya calculadas por Revit**. Acá el
cómputo no se mide, **se lee**. Máxima precisión, mínima intervención.

### DWG — prioridad 3, con un problema de licencia
DWG es cerrado; `ezdxf` **no lo lee**. Opciones:

1. **ODA File Converter** — `ezdxf.addons.odafc` lo envuelve. **Atención: la
   página de descarga de Open Design Alliance hoy dice "ODA software free for 60
   days".** Históricamente era libre. **Verificar los términos antes de apoyar el
   producto en esto.**
2. **LibreDWG** (`dwg2dxf`) — libre pero GPL (contagia la licencia) y soporte
   incompleto en DWG recientes.
3. **Exportar a DXF desde AutoCAD** — un `SAVEAS`. Cero costo, cero riesgo.

**Recomendación:** v1 detecta DWG y muestra un diálogo con instrucciones para
exportar a DXF. La conversión automática queda como mejora opcional. No bloquear
el proyecto por una licencia.

---

## 4. Arquitectura

Separación estricta entre **leer el plano**, **medir**, **cotizar** y
**presupuestar**. El módulo de precios es el que más va a cambiar con el tiempo,
así que está lo más aislado posible.

```
app/
  ui/                    Qt: ventana, visor, paneles, diálogos
    viewer.py              visor derivado de ezdxf qtviewer + selección
    panel_capas.py         capas on/off, asignación capa -> ítem
    panel_computo.py       tabla de mediciones acumuladas
    panel_cotizacion.py    candidatos de precio, confirmación manual
    panel_presupuesto.py   planilla por rubros + coeficiente de impacto
  readers/               -> devuelven un "Documento" normalizado
    dxf_reader.py
    ifc_reader.py
    dwg_reader.py          (convierte y delega en dxf_reader)
  measure/               motor de medición, SIN Qt ni SQL
    units.py               $INSUNITS + calibración manual de escala
    rules.py               reglas capa -> tipo de medición -> ítem
    engine.py              longitud / área / conteo / volumen
  pricing/               **módulo de precios, aislado**
    sources/
      base.py              interfaz FuenteDePrecios
      vtex.py              adapter VTEX (sirve para VARIOS retailers)
      mercadolibre.py      adapter API con OAuth
      html_generico.py     adapter con selectores CSS por sitio
    matcher.py             insumo -> candidatos de SKU
    cache.py               histórico de precios, nunca pisa datos
  budget/                cómputo -> presupuesto, SIN Qt
    apu.py                 análisis de precio unitario
    impacto.py             gastos generales, beneficio, impuestos
    rollup.py              agregación por rubro, incidencias
  db/                    SQLAlchemy, migraciones
  export/                CSV
tests/
```

Regla de oro: `measure/`, `pricing/` y `budget/` son Python puro y testeable. Si
para probar un cómputo o una cotización hace falta abrir una ventana, el diseño
está mal.

---

## 5. Modelo de datos (SQLite)

**Lado plano/medición**
- `proyecto` — nombre, comitente, ubicación, fecha
- `plano` — archivo, hash SHA-256, formato, unidades, factor de escala
- `perfil_capas` — conjunto de reglas **reutilizable entre planos**
- `regla` — capa o patrón → tipo de medición → ítem → factor
- `medicion` — plano, handle de la entidad, tipo, valor crudo, valor final, ítem

Guardar el **handle** permite re-abrir el plano y que las mediciones sigan
apuntando a las líneas correctas. Guardar el **hash** permite avisar "este plano
cambió desde el último cómputo".

**Lado catálogo**
- `rubro` — Movimiento de suelo, Mampostería, Instalación sanitaria…
- `item` — unidad de medida + su APU (ej. "Mampostería 0,15 m, m²")
- `insumo` — material, **mano de obra** o **equipo**
- `apu_detalle` — ítem → insumo → **coeficiente de rendimiento**
- `coef_impacto` — gastos generales, beneficio, impuestos (§7)

**Lado precios (nuevo)**
- `fuente` — Easy, Sodimac, MercadoLibre…: tipo de adapter, URL base, credenciales
- `sku` — fuente, id del producto, nombre, marca, EAN, URL, unidad de venta
- **`insumo_sku`** — **vínculo confirmado** insumo ↔ SKU + **factor de conversión**
- `precio` — sku, valor, moneda, fecha/hora, `precio_sin_iva`, disponible, fuente

**El `insumo_sku` es la pieza central del módulo de precios.** La búsqueda por
texto se hace **una sola vez**; una vez que confirmás que *"Cemento CPC40 25 kg"*
es el SKU `1483133` de Easy, se guarda el vínculo y de ahí en adelante se
re-consulta **por SKU directo**: exacto, barato y sin ambigüedad. Buscar por texto
en cada actualización es lo que hace frágiles a los scrapers caseros.

**El coeficiente de rendimiento** es lo que convierte geometría en materiales. Un
m² de mampostería de 0,15 no consume "ladrillos": consume ~57 ladrillos + 0,03 m³
de mortero + X horas de oficial. Se carga una vez y se reutiliza siempre.

**El factor de conversión** resuelve el otro desajuste: el APU pide kg de cemento,
el retail vende bolsas de 25 kg. El factor vive en `insumo_sku`.

**Precios con fecha y hora obligatorias**, siempre. La tabla `precio` es un
histórico: nunca se sobreescribe una fila, se agrega otra. Así podés ver cómo se
movió un material y re-valorizar un presupuesto viejo.

---

## 6. Búsqueda de precios en internet

Esta es la parte nueva y la más delicada. **Investigué las fuentes reales antes de
diseñarla**, y el resultado cambia bastante el enfoque.

### Lo que encontré

**Easy — API JSON pública, funciona hoy.** Easy corre sobre **VTEX**, y la API de
catálogo de VTEX responde sin autenticación:

```
GET https://www.easy.com.ar/api/catalog_system/pub/products/search?ft=cemento&_from=0&_to=4
```

Lo probé y devuelve JSON limpio con exactamente lo que hace falta:

| Campo | Valor de ejemplo |
|---|---|
| `productName` | `Cemento 25 Kg Avellaneda` |
| `brand` | `Cementos Avellaneda` |
| `ean` | `7798042431434` |
| `Price` / `ListPrice` | `8490.0` |
| **`price_wo_taxes`** | **`7016.53`** ← precio sin IVA, oro puro para presupuestar |
| `Peso` | `25 kg` ← alimenta el factor de conversión |
| `measurementUnit` | `un` |
| `AvailableQuantity` / `IsAvailable` | `99999` / `true` |
| `categories` | `/Construcción y Maderas/Obra Gruesa/Cementos y complementos/` |

Un detalle de implementación: en la respuesta, los campos de especificaciones
como `price_wo_taxes` **vienen como lista de strings** (`["7016.53"]`), no como
número. El adapter tiene que normalizarlos, y los tests tienen que cubrir el caso
de que vengan vacíos: `brand` por ejemplo llega como `"-"` en varios productos.

**Esto no es scraping de HTML: es una API JSON estructurada.** Es mucho más
estable que parsear páginas, y además `robots.txt` de Easy **no bloquea `/api/`**
(solo `/admin/`, `/account`, `/p?idsku=` y filtros de categoría).

**El adapter VTEX es reutilizable.** VTEX es la plataforma de e-commerce de
muchísimos retailers argentinos. Un solo adapter, bien hecho, sirve para varias
fuentes cambiando la URL base. **Esta es la mejor noticia técnica del módulo.**

**Sodimac — no sirve el mismo camino.** Probé el endpoint VTEX y devuelve **404**:
Sodimac Argentina no está en VTEX. Requiere scraping HTML o encontrar su API
propia. Más frágil y de menor prioridad. Además su `robots.txt` bloquea
`/sodimac-ar/search/`, así que **la búsqueda hay que resolverla sin pasar por esa
ruta**.

**MercadoLibre — tiene API, pero ya no es abierta.** El endpoint
`/sites/MLA/search` **hoy exige OAuth**: registrar una aplicación en el portal de
desarrolladores y manejar access token + refresh. Es gratis y es la fuente con más
cobertura de corralones chicos, pero implica un flujo de autenticación y manejo de
rate limit (HTTP 429).

### Cómo queda diseñado

**Un adapter por fuente, detrás de una interfaz común.** Cada fuente declara su
dificultad y su estabilidad esperada:

| Fuente | Vía | Estabilidad | Prioridad |
|---|---|---|---|
| **Easy** | **API VTEX pública** | **Alta** | **1 — arrancar acá** |
| Otros retailers VTEX | mismo adapter, otra URL base | Alta | 2 — costo casi cero |
| MercadoLibre | API oficial + OAuth | Media (tokens, 429) | 3 |
| Sodimac | scraping HTML | **Baja, se va a romper** | 4 |

**La cotización es asistida, igual que la medición.** No es casualidad: es el mismo
principio. La app trae candidatos, vos confirmás el vínculo una vez.

Que esto no es paranoia lo muestra la prueba real: buscando `cemento` en Easy, el
cuarto resultado fue **"maceta cemento textura b"**, una maceta de jardín a
$49.990. Un scraper que tome "el primer resultado" o "el más barato" te mete una
maceta en el presupuesto de hormigón. **Por eso el vínculo lo confirmás vos, una
vez, y queda guardado.**

El flujo:

1. Para cada insumo sin vínculo, la app busca en las fuentes activas.
2. Muestra los candidatos con nombre, marca, precio, unidad y foto.
3. Elegís el correcto y cargás el **factor de conversión** (bolsa 25 kg → kg).
   Queda guardado en `insumo_sku`.
4. **Actualizaciones futuras: consulta directa por SKU.** Sin búsqueda de texto,
   sin ambigüedad, una request por insumo.
5. Si un SKU deja de existir o queda sin stock, la app lo marca y te pide
   re-vincular. **Nunca borra el último precio conocido.**

### Reglas de buena conducta (no opcionales)

Un scraper que se porta mal termina bloqueado, y entonces no tenés precios.

- **Caché con TTL.** Un precio de hace 6 horas sirve. No consultar dos veces lo
  mismo en el día.
- **Rate limit propio** y reintento con *backoff* exponencial ante 429/503.
- **`User-Agent` honesto e identificable.** No disfrazarse de navegador.
- **Respetar `robots.txt`** de cada fuente; ya está relevado arriba.
- **Un botón, no un demonio.** La actualización la disparás vos; no hay un proceso
  martillando los sitios de fondo.
- **Precios de lista, de referencia.** Un precio de retail online no es una
  cotización formal de proveedor. El informe lo dice explícitamente con fuente,
  fecha y hora.

### Una observación sobre haber elegido solo scraping

Elegiste scraping online como única fuente. Lo implemento así, y el hallazgo de la
API de VTEX lo vuelve bastante más sólido de lo que esperaba. Dos cosas a tener
presentes:

**La carga manual de precios no es realmente una alternativa: es el sustrato.** La
tabla `precio` tiene que poder recibir un valor escrito a mano, porque es lo que
queda cuando una fuente se cae, cuando un insumo no existe en retail (hormigón
elaborado, mano de obra, alquiler de equipos) o cuando conseguís un precio mejor
por teléfono. Está en el plan como capacidad base, no como fuente competidora.

**Mano de obra y equipos no se cotizan en retail.** Elegiste presupuesto completo,
y en Easy no hay "hora de oficial albañil". Esos insumos van a precio manual o por
índice sí o sí. El scraping cubre materiales; el resto es carga tuya.

Si en algún momento querés importar la lista de precios en Excel de tu corralón,
es un adapter más contra el mismo modelo de datos. La arquitectura ya lo permite.

---

## 7. Presupuesto completo

Elegiste el alcance formal, así que el cálculo tiene dos niveles:

**Costo directo** — por cada ítem: cantidad × APU, donde el APU suma sus insumos
de material, mano de obra y equipo con sus coeficientes de rendimiento.

**Coeficiente de impacto** — sobre el costo directo se aplican, en orden y
configurables:

| Concepto | Típico |
|---|---|
| Gastos generales e indirectos | 10-20 % |
| Beneficio | 10-15 % |
| Costo financiero | según plazo |
| Ingresos brutos | según jurisdicción |
| IVA | 21 % (o 10,5 % en obra de vivienda) |

Dos detalles que importan:

- **Las alícuotas son datos, no código.** Van en una tabla editable, con fecha de
  vigencia. Cambian, y cuando cambian no quiere decir recompilar la app.
- **El IVA y el precio scrapeado.** El retail publica precio **con** IVA, pero la
  API de VTEX también da `price_wo_taxes`. Para no contar el IVA dos veces, el
  costo directo se arma **sin IVA** y el IVA se aplica una sola vez al final. Es
  un error de doble conteo fácil de cometer y caro de explicar.

---

## 8. El informe: CSV

El informe principal es **CSV**, importable en Excel y Google Sheets. Vale la pena
no exportar un solo archivo sino **cuatro**, porque son cuatro cosas distintas:

| Archivo | Contenido | Para qué |
|---|---|---|
| `computo.csv` | Mediciones: capa, entidad, tipo, cantidad, ítem | Auditar de dónde salió cada cantidad |
| `materiales.csv` | **Lista de materiales**: insumo, unidad, cantidad total, precio, fuente, fecha | **Es la lista de compra** |
| `presupuesto.csv` | Por rubro e ítem: cantidad, PU, costo directo, incidencia % | Lo que ve el comitente |
| `precios.csv` | Histórico: insumo, SKU, fuente, precio, fecha/hora, URL | Trazabilidad y seguimiento |

### El detalle del CSV que más molesta en la práctica

Un CSV mal armado se abre todo en una columna, o convierte `1,50` en `150`. Para
Excel en español hay que hacer dos cosas:

- **Separador `;`** — Excel en configuración regional argentina espera punto y
  coma, no coma, porque la coma es el separador decimal.
- **UTF-8 con BOM** — sin el BOM, Excel muestra `Hormigón` como `HormigÃ³n`.

Google Sheets prefiere lo contrario: coma como separador y punto decimal. Así que
el export ofrece **dos presets** —*Excel (es-AR)* y *Google Sheets*— y se acuerda
del último que usaste. Es una pavada de implementar y evita el 90 % de los
"no me abre bien el archivo".

PDF con carátula queda como mejora posterior; no está en el camino crítico.

---

## 9. El flujo de uso completo

1. **Abrir** el plano. La app lee `$INSUNITS` y propone las unidades.
2. **Calibrar escala**: clic en dos puntos de una cota conocida, escribir la medida
   real. Resuelve los planos mal escalados, que son la mitad.
3. **Ver las capas**, con conteo de entidades. Apagar el ruido (cotas, ejes,
   amoblamiento, carátula).
4. **Asignar** capa → tipo de medición → ítem:
   - `MUROS` → longitud → *Mampostería 0,15 m* (× altura 2,60 → m²)
   - `PISOS` → área → *Contrapiso + carpeta*
   - `ABERTURAS` → conteo de bloques → *Carpintería* (desglosada por bloque)
5. **Computar.** Lo dudoso —polilínea abierta, área absurda, capa sin asignar— va a
   una **lista de revisión**, no se descarta en silencio.
6. **Revisar** y corregir a mano; toda medición es editable y queda marcada como
   ajustada.
7. **Explotar a insumos** vía APU: cantidades de ítems → cantidades de materiales,
   mano de obra y equipos.
8. **Cotizar**: la app busca precios, vos confirmás los vínculos nuevos. Los ya
   vinculados se actualizan solos por SKU.
9. **Aplicar coeficiente de impacto** y ver la planilla por rubros con incidencias.
10. **Exportar los cuatro CSV**.
11. **Guardar el perfil de capas.** La próxima vez que abras un plano del mismo
    estudio, los pasos 3-4 ya están resueltos. **Acá está el puente a la
    extracción automática**: con 5 o 6 perfiles buenos, "automático" es aplicar un
    perfil y revisar.

Qué extrae `ezdxf` por tipo de medición:
- **Longitud** — `LWPOLYLINE`/`POLYLINE`/`LINE`/`ARC` → recorrer vértices
- **Área** — `HATCH` y sus *boundary paths* (lo más confiable); polilínea cerrada →
  `shapely.Polygon.area`
- **Conteo** — entidades `INSERT` agrupadas por nombre de bloque
- **Volumen** — área o longitud × espesor/altura paramétrico del ítem

---

## 10. Roadmap

Cada etapa termina en algo que **se puede abrir y probar**. Estimaciones asumiendo
trabajo de a ratos, no full-time.

| # | Etapa | Entregable verificable | Est. |
|---|---|---|---|
| 0 | Esqueleto | Repo, venv, Qt abre ventana, SQLite se crea, pytest corre | 2-3 d |
| 1 | **Visor DXF** | **Abre un DXF real, pan/zoom, capas on/off, clic en entidad muestra capa/tipo/handle** | 1-1,5 sem |
| 2 | Unidades y escala | Lee `$INSUNITS`, calibración por 2 puntos, mide una distancia correcta en metros | 3-4 d |
| 3 | Motor de medición | Longitud, área, conteo; tests con DXF sintéticos de área conocida | 1-1,5 sem |
| 4 | Catálogo y APU | ABM de rubros/ítems/insumos y coeficientes de rendimiento | 1 sem |
| 5 | Cómputo → ítems | Asignación capa→ítem, perfiles guardables, explosión a insumos | 1-1,5 sem |
| 6 | **Export CSV** | **Los cuatro CSV, con presets Excel es-AR y Google Sheets** | 3-4 d |
| 7 | **Precios: adapter VTEX** | **Busca "cemento" en Easy, muestra candidatos, vinculás, guarda precio con fecha** | **1-1,5 sem** |
| 8 | Precios: actualización | Refresco por SKU, caché con TTL, rate limit, histórico, re-vinculación | 1 sem |
| 9 | Coeficiente de impacto | GG, beneficio, impuestos con fecha de vigencia; presupuesto final | 4-5 d |
| 10 | IFC | Abre un IFC de Revit y lee `BaseQuantities` directo, sin medir | 1-1,5 sem |
| 11 | MercadoLibre | OAuth, manejo de token y 429 | 4-5 d |
| 12 | DWG | Diálogo de conversión; ODA automático **si la licencia lo permite** | 2-4 d |
| 13 | **Instalable** | **`.exe` + instalador Inno Setup que corre en una PC sin Python** | 4-6 d |

**Por qué el CSV (etapa 6) va antes que los precios (etapa 7):** apenas tengas
cómputo y catálogo, un CSV de cantidades ya es útil por sí solo —lo abrís en
Sheets y le ponés precios a mano. Te deja una herramienta usable **seis etapas
antes** de que el módulo de precios esté listo, y el módulo de precios es el que
más riesgo tiene de estirarse.

**La etapa 1 sigue siendo el hito que vale.** Un visor que abre tu plano y te deja
apagar capas te dice si todo el enfoque funciona con tus archivos reales, antes de
invertir en el resto.

---

## 11. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Planos sin convención de capas** | **Alto** | Es la razón de elegir medición asistida |
| **Polilíneas no cerradas** | **Alto** | Problema #1 al medir áreas: tolerancia de cierre configurable + herramienta de cerrar contorno + lista de revisión |
| **Doble conteo de IVA** | **Alto** | Costo directo siempre sin IVA, usando `price_wo_taxes`; IVA una sola vez al final |
| **Vínculo insumo↔SKU equivocado** | **Alto** | La "maceta cemento" del ejemplo real: confirmación manual una vez, vínculo persistente, nunca auto-elegir |
| **Doble conteo de cantidades** | **Alto** | La UI muestra de dónde sale cada cantidad y resalta en el plano las entidades que la componen |
| **Scraping de Sodimac se rompe** | Medio | Es la fuente de prioridad 4; Easy/VTEX es la base y no depende de ella |
| **Bloqueo por IP o reCAPTCHA** | Medio | Caché, rate limit, UA honesto, actualización manual y no automática. Easy ya tiene reCAPTCHA en el sitio público, aunque no en `/api/` |
| **MercadoLibre cambia el OAuth** | Medio | Adapter aislado; si se cae, el resto de las fuentes sigue |
| **Licencia de ODA** para DWG | Medio | v1 pide DXF; conversión automática es opcional |
| **CSV mal interpretado por Excel** | Medio | Separador `;` + UTF-8 con BOM, presets por destino |
| Entidades ACIS / 3D | Bajo | `ezdxf` no las renderiza (limitación documentada); no son cómputo 2D |
| Bloques anidados y XREFs | Medio | Resolver recursivo con tope; avisar cuando falta el XREF externo |
| Precios desactualizados | Medio | Fecha y hora obligatorias, aviso de antigüedad en el informe |

---

## 12. Lo que queda por definir

1. **¿Qué rubros usás realmente?** Arrancar con tu lista y 15-20 ítems típicos vale
   mucho más que un catálogo genérico. Es lo que más acelera las etapas 4-5.
2. **¿Qué jurisdicción?** Para la alícuota de ingresos brutos y si aplica IVA 10,5 %
   de obra de vivienda.
3. **¿Qué corralones usás?** Si alguno tiene tienda web, reviso si corre VTEX. Si
   corre, entra al adapter con costo casi cero y es mejor fuente que Easy para vos.
4. **¿Unidades de tus planos?** Metros, centímetros o milímetros cambia los
   defaults, aunque la calibración lo resuelve igual.

---

## 13. Próximo paso concreto

Conseguir **un DXF real tuyo** y correr:

```bash
pip install "ezdxf[draw]"
ezdxf view tu_plano.dxf     # visor incluido
ezdxf info tu_plano.dxf     # versión, unidades, estadísticas
```

Eso contesta en diez minutos las tres preguntas que más condicionan el plan: qué
convención de capas tienen tus planos, si vienen escalados, y si los contornos
están cerrados.

Y para ver la fuente de precios con tus propios ojos, esta URL devuelve JSON en el
navegador, sin instalar nada:

```
https://www.easy.com.ar/api/catalog_system/pub/products/search?ft=ladrillo%20hueco&_from=0&_to=9
```
