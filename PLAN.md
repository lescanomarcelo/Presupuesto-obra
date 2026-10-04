# Presupuesto de Obra — Plan de desarrollo

Aplicación **de escritorio para Windows** que abre un plano (DXF / DWG / IFC),
permite **medir de forma asistida** sobre él, **busca precios de materiales en
internet**, y produce un **presupuesto completo** exportable a **CSV** para
importar en Excel o Google Sheets.

> Revisión 3 — incorpora el relevamiento de 24 fuentes de precios (§6), la
> comparativa multi-fuente y la detección de valores raros (§7). Los scripts que
> produjeron esos datos están en `tools/` y se pueden volver a correr.

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
      vtex.py              adapter VTEX      -> Easy, Colorshop, +
      woocommerce.py       adapter WC Store  -> 5 corralones, + los que vengan
      mercadolibre.py      adapter API con OAuth
      html_generico.py     adapter con selectores CSS por sitio
      dominios.py          tabla dominio -> adapter (agregar fuente = 1 linea)
    normalizar.py          precio -> unidad del insumo (kg, un, m2, m3)
    comparador.py          banda de consenso (mediana + IQR) y clasificacion
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
- `fuente` — dominio, **tipo de adapter** (vtex / woocommerce / ml / html), activa
- `sku` — fuente, id del producto, nombre, marca, EAN, URL, unidad de venta
- **`insumo_sku`** — **vínculo confirmado** insumo ↔ SKU + **factor de conversión**
- `precio` — sku, valor, moneda, fecha/hora, `precio_sin_iva`, disponible, fuente
- **`insumo.fuente_preferida`** — de qué fuente sale el precio que va al
  presupuesto. Las demás se guardan igual, para construir la banda (§7)

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

Esta es la parte nueva y la más delicada. **Relevé las fuentes reales antes de
diseñarla**, con los scripts que están en `tools/` y se pueden volver a correr.

### El método: detectar la plataforma, no escribir un scraper por sitio

Casi ningún corralón programó su tienda: usa una plataforma de e-commerce. Y las
plataformas más comunes **exponen API pública sin autenticación**. Así que en vez
de escribir 20 scrapers, se detecta la plataforma y se escribe **un adapter por
plataforma**.

Probé 24 dominios argentinos de materiales. Resultado:

| Fuente | Plataforma | API pública | Estado |
|---|---|---|---|
| **easy.com.ar** | VTEX | `/api/catalog_system/pub/products/search?ft=` | **✅ funciona** |
| **colorshop.com.ar** | VTEX | ídem | **✅ funciona** |
| **laeconomica.com.ar** | WooCommerce | `/wp-json/wc/store/v1/products?search=` | **✅ funciona** |
| **latejamateriales.com** | WooCommerce | ídem | **✅ funciona** |
| **centralmaterialesya.com** | WooCommerce | ídem | **✅ funciona** |
| **germatsrl.com** | WooCommerce | ídem | **✅ funciona** |
| **grupocanarias.com.ar** | WooCommerce | ídem | **✅ funciona** |
| sodimac.com.ar | Next.js propio | — (404 en VTEX) | ❌ scraping HTML |
| aconmateriales.com.ar | Tiendanube | — (requiere API key) | ❌ scraping HTML |
| corralon-fernandes.com | PrestaShop | — | ❌ scraping HTML |
| servidos.ar | Next.js | — | ⚠️ índice de referencia (§7) |
| materialesmoreno.com.ar, rodomateriales.com.ar, trazarshop.com, elalbanil.com.ar, corralonfer.com, corralonlasquintas.com.ar | varias | — | ❌ |
| barugelazulay, blancotejerina, hierrosmoreno, construyaonline, pinturerias-rex, corralonsanjose | no resolvieron | — | ❌ |

**El hallazgo que más vale: la API Store de WooCommerce funciona en 5 corralones.**
Es pública, sin autenticación, y devuelve JSON estructurado. **Dos adapters —VTEX y
WooCommerce— cubren 7 fuentes.** Y cada nuevo corralón WooCommerce que aparezca
entra con costo cero: solo hay que agregar el dominio a una lista.

Eso cambia la economía del módulo por completo. No es "escribir scrapers para
siempre": son dos adapters y una tabla de dominios.

### Lo que devuelve cada plataforma

**VTEX** (`easy.com.ar`) — probado, devuelve:

| Campo | Ejemplo |
|---|---|
| `productName` / `brand` | `Cemento 25 Kg Avellaneda` / `Cementos Avellaneda` |
| `ean` | `7798042431434` |
| `Price` / `ListPrice` | `8490.0` |
| **`price_wo_taxes`** | **`7016.53`** ← precio sin IVA |
| `Peso` | `25 kg` ← alimenta el factor de conversión |
| `IsAvailable` / `AvailableQuantity` | `true` / `99999` |
| `categories` | `/Construcción y Maderas/Obra Gruesa/Cementos y complementos/` |

**WooCommerce Store API** (`laeconomica.com.ar`) — probado, devuelve
`name`, `sku`, `permalink`, `is_in_stock`, `weight`, `dimensions`, `categories`,
`brands` y `prices`.

Dos trampas de implementación, ambas verificadas en datos reales:

- **WooCommerce da el precio en unidades mínimas.** `"price": "729979"` con
  `"currency_minor_unit": 2` es **$7.299,79**, no $729.979. Hay que dividir por
  `10**minor_unit`. Equivocarse acá multiplica todo por cien.
- **Los nombres vienen con entidades HTML sin decodificar.** Aparece
  `Varilla de Hierro Aletado 8mm &#8211; Acindar`. Hay que pasar
  `html.unescape()` antes de guardar o de mostrar.

En VTEX la trampa es otra: los campos de especificaciones como `price_wo_taxes`
**vienen como lista de strings** (`["7016.53"]`), no como número, y `brand` llega
como `"-"` en varios productos.

`robots.txt` de Easy **no bloquea `/api/`** (solo `/admin/`, `/account`,
`/p?idsku=` y filtros de categoría). El de Sodimac bloquea
`/sodimac-ar/search/`, que es justamente la ruta de búsqueda: otra razón para
dejarlo en última prioridad.

### Cómo queda diseñado

| Adapter | Cubre | Estabilidad | Prioridad |
|---|---|---|---|
| **VTEX** | Easy, Colorshop, + cualquier VTEX futuro | **Alta** | **1** |
| **WooCommerce** | La Económica, La Teja, Central Materiales Ya, Germat, Grupo Canarias | **Alta** | **1** |
| MercadoLibre | API oficial, exige **OAuth** (ya no es abierta) + rate limit 429 | Media | 3 |
| HTML genérico | Sodimac, Tiendanube, PrestaShop — selectores CSS por sitio | **Baja, se rompe** | 4 |

**La cotización es asistida, igual que la medición.** Mismo principio: la app trae
candidatos, vos confirmás el vínculo **una vez**, y queda guardado en
`insumo_sku`. Después se refresca por SKU directo.

Que esto no es paranoia lo demuestran los datos reales. Buscando `cemento` en
Easy, aparece **"maceta cemento textura b"** a $49.990. Buscando
`hierro aletado 8`, aparece una **"Prensa para Hamburguesas Hierro 8 Cm"** a
$27.990. Un scraper que tome el primer resultado o el más barato te mete una
prensa de hamburguesas en el presupuesto de estructura.

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
  cotización formal. El informe lo dice, con fuente, fecha y hora.

### Sobre haber elegido solo scraping

Lo implemento así, y el relevamiento lo volvió bastante más sólido de lo que
esperaba: 7 fuentes con API pública es mucho más de lo que anticipaba. Dos cosas
siguen en pie:

**La carga manual de precios no es una alternativa: es el sustrato.** La tabla
`precio` tiene que aceptar un valor escrito a mano, porque es lo que queda cuando
una fuente se cae y lo que necesitás cuando conseguís un precio mejor por
teléfono.

**Mano de obra y equipos no se cotizan en retail.** En Easy no hay "hora de
oficial albañil". Elegiste presupuesto completo, así que esos insumos van a precio
manual o por índice sí o sí. El scraping cubre materiales.

---

## 7. Comparativa multi-fuente y detección de valores raros

Corrí una canasta real contra las 7 fuentes con API (`tools/comparar_precios.py`).
Los resultados cambian el diseño, así que vale la pena mirarlos.

### Qué pasó con el cemento

Normalizando a **$/kg**, el cemento gris común en bolsa de 25 kg dio esto en 5
fuentes independientes:

```
n=22   min 292   Q1 302   mediana 315   Q3 351   max 384   ($/kg)
max/min = 1,31x
```

**Una banda de 31% punta a punta es consenso real.** Cuando 5 corralones
independientes coinciden en una franja así, el valor central es confiable y
cualquier cosa muy afuera merece explicación.

Y después aparecieron los "atípicos", a 94x la mediana:

| Producto | $/kg | ¿Es un error? |
|---|---|---|
| Cemento Blanco x 25 kg | 1.638 | **No.** Es otro producto, vale ~5x |
| Cemento Rápido gris 1 kg | 2.700 | **No.** Otro producto, y envase chico |
| Cemento Blanco 1 kg | 5.600 | **No.** Otro producto + envase chico |
| **Pallet Cemento Avellaneda 25 kg (80 bolsas)** | **22.720** | **No. Es el MÁS BARATO** |

### El hallazgo que define el diseño

Ese pallet de $568.000 se marcó como atípico 94x. Pero:

```
$568.000 / 80 bolsas = $7.100 por bolsa  ->  $284/kg
mediana del mercado: $315/kg
=> el pallet está 13% MÁS BARATO que la mediana
```

**El "valor rarísimo" era la mejor oferta de la tabla.** Un sistema que descarta
atípicos habría tirado justamente el precio que más conviene.

De ahí sale la regla central del módulo:

> **Un valor raro casi nunca es un precio equivocado. Es otro producto, otro
> envase o otra unidad de venta.** La dispersión no es ruido para filtrar: es la
> señal de que falta normalizar.

Lo mismo pasó con los ladrillos (unidad a $1.413 vs pallet a $99.000) y con la cal
(bolsa de 25 kg a $240/kg vs envase de 5 kg a $1.618/kg). En los tres casos el
"atípico" era una unidad de venta distinta, no un error.

### Cómo se detectan entonces los valores raros

El orden importa, y es al revés de lo intuitivo:

1. **Normalizar primero.** Todo precio se lleva a la unidad del insumo del APU
   ($/kg, $/unidad, $/m², $/m³) usando el factor de conversión de `insumo_sku`.
   Comparar precios sin normalizar no sirve para nada.
2. **Comparar solo dentro del mismo insumo.** "Cemento" no es un insumo:
   *Cemento portland CPC40* y *cemento de albañilería* son dos insumos distintos
   y tienen precios legítimamente distintos. La comparación vive **debajo** del
   vínculo confirmado, nunca arriba.
3. **Banda de consenso con cuartiles, no con promedio.** Mediana + rango
   intercuartílico, criterio de Tukey (`Q1 − 1,5·IQR`, `Q3 + 1,5·IQR`). Con los
   datos del cemento esa banda da **[230, 423] $/kg**: contiene a todas las
   ofertas legítimas y excluye al cemento blanco. El promedio y el desvío estándar
   no sirven acá porque un solo pallet los arrastra.
4. **Clasificar, no descartar.** Cada precio fuera de banda recibe una etiqueta y
   un trato distinto:

| Clasificación | Señal | Qué hace la app |
|---|---|---|
| **Unidad de venta distinta** | Dice "pallet", "x80", "bulto", "tira", "m³" | **Ofrece dividir** y lo recalcula como candidato válido. Es donde está el ahorro |
| **Envase chico** | Peso del envase muy menor a la mediana | Lo marca; es precio legítimo pero caro por kg |
| **Producto distinto** | Palabra discriminante (blanco, rápido, refractario) | Sugiere que es **otro insumo** y ofrece crearlo |
| **Sospechoso de verdad** | Fuera de banda, misma unidad, mismo producto | **Lo pide confirmar.** Puede ser precio viejo, error de carga o liquidación |
| Sin stock | `IsAvailable: false` | No entra en la banda, pero **no se borra** el histórico |

El único caso que realmente merece desconfianza es el último. En el relevamiento
apareció uno: *"Cal Aérea 25 Kg El Milagro"* a **$123/kg**, con la mediana de la
cal en $355/kg. Mismo envase, mismo tipo de producto, y aun así tres veces más
barato. Eso es lo que la app tiene que poner adelante para que lo mires: puede ser
una liquidación real o un precio mal cargado, y la diferencia la decidís vos.

### Un proveedor o varios: varios, pero no para todo

Es la pregunta que hiciste, y los datos la contestan con un matiz.

**Varias fuentes para validar.** El valor de tener 7 fuentes no es elegir siempre
la más barata: es tener **banda de consenso**. Con una sola fuente, un precio mal
cargado entra al presupuesto sin que nadie se entere. Con cinco, salta solo. Esto
es gratis una vez que los adapters existen.

**Una fuente preferida por insumo para el número que firmás.** El presupuesto
tiene que ser *comprable*. Si cada ítem toma el mínimo de una fuente distinta,
armás un presupuesto que no existe en la realidad: seis proveedores, seis fletes,
seis mínimos de compra, y los áridos y el hierro pesado tienen flete que se come
la diferencia. Así que cada insumo tiene su **fuente preferida**, y el presupuesto
se arma con esa.

**Y la app te muestra lo que dejás sobre la mesa.** Al lado de cada ítem: precio
elegido, mediana del mercado y mejor precio disponible con su fuente. Si en
cemento hay 13% de diferencia comprando por pallet, eso se ve. La decisión de
cambiar de proveedor o comprar por volumen es tuya, pero informada.

Concretamente, en el modelo de datos:

- `insumo.fuente_preferida` → de dónde sale el precio del presupuesto
- `insumo_sku` por cada fuente donde ese insumo esté vinculado
- `precio` acumula todas las fuentes, siempre, para construir la banda
- El informe `precios.csv` exporta la comparativa completa, no solo el elegido

### Qué cobertura esperar de cada fuente

No todas sirven para lo mismo, y conviene saberlo antes:

- **Easy** tiene el catálogo más amplio por lejos: aparece en todas las búsquedas y
  con muchas variantes. Es la mejor fuente para **descubrir** y vincular insumos.
  Pero es retail: en los commodities pesados suele estar en la mitad alta de la
  banda.
- **Los corralones WooCommerce** tienen catálogo chico pero precios competitivos, y
  son los únicos que ofrecen **pallet y venta por volumen**, que es donde está el
  ahorro real. Grupo Canarias y La Teja aparecieron en el extremo barato.
- **Colorshop** sirve para pinturas y terminaciones, no para obra gruesa.
- **Ninguna** cotiza mano de obra, equipos ni hormigón elaborado.

### Un índice de referencia como red de seguridad

Encontré además `servidos.ar/precio-materiales-construccion`, que publica
**rangos** de precios de materiales en Argentina en vez de un valor único, con el
criterio explícito de que el mismo material cambia según el canal (mayorista,
corralón de barrio, retail, plataforma online). No tiene API, pero como
**contraste de cordura** es útil: si tu banda de consenso se va muy lejos de ese
rango publicado, algo pasa.

Queda anotado como fuente de referencia de prioridad baja, no como fuente de
precios para el presupuesto.

---

## 8. Presupuesto completo

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

## 9. El informe: CSV

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

## 10. El flujo de uso completo

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

## 11. Roadmap

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
| 7 | **Precios: adapters VTEX + WooCommerce** | **Busca "cemento" en las 7 fuentes, muestra candidatos, vinculás, guarda precio con fecha** | **1-1,5 sem** |
| 8 | Normalización y conversión | Factor de conversión por vínculo, extracción de peso/bulto del nombre, $/kg correcto | 4-5 d |
| 9 | **Comparativa y atípicos** | **Banda de mediana+IQR por insumo, clasificación de fuera-de-banda, "dividir por pallet", fuente preferida** | **1 sem** |
| 10 | Precios: actualización | Refresco por SKU, caché con TTL, rate limit, histórico, re-vinculación | 1 sem |
| 11 | Coeficiente de impacto | GG, beneficio, impuestos con fecha de vigencia; presupuesto final | 4-5 d |
| 12 | IFC | Abre un IFC de Revit y lee `BaseQuantities` directo, sin medir | 1-1,5 sem |
| 13 | MercadoLibre | OAuth, manejo de token y 429 | 4-5 d |
| 14 | DWG | Diálogo de conversión; ODA automático **si la licencia lo permite** | 2-4 d |
| 15 | **Instalable** | **`.exe` + instalador Inno Setup que corre en una PC sin Python** | 4-6 d |

**Por qué el CSV (etapa 6) va antes que los precios (etapa 7):** apenas tengas
cómputo y catálogo, un CSV de cantidades ya es útil por sí solo —lo abrís en
Sheets y le ponés precios a mano. Te deja una herramienta usable **seis etapas
antes** de que el módulo de precios esté listo, y el módulo de precios es el que
más riesgo tiene de estirarse.

**La etapa 1 sigue siendo el hito que vale.** Un visor que abre tu plano y te deja
apagar capas te dice si todo el enfoque funciona con tus archivos reales, antes de
invertir en el resto.

---

## 12. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Planos sin convención de capas** | **Alto** | Es la razón de elegir medición asistida |
| **Polilíneas no cerradas** | **Alto** | Problema #1 al medir áreas: tolerancia de cierre configurable + herramienta de cerrar contorno + lista de revisión |
| **Doble conteo de IVA** | **Alto** | Costo directo siempre sin IVA, usando `price_wo_taxes`; IVA una sola vez al final |
| **Vínculo insumo↔SKU equivocado** | **Alto** | La "maceta cemento" del ejemplo real: confirmación manual una vez, vínculo persistente, nunca auto-elegir |
| **Doble conteo de cantidades** | **Alto** | La UI muestra de dónde sale cada cantidad y resalta en el plano las entidades que la componen |
| **Comparar sin normalizar** | **Alto** | Es el error que convierte al pallet más barato en "atípico 94x". Normalizar a la unidad del insumo **antes** de comparar (§7) |
| **Descartar atípicos automáticamente** | **Alto** | Tiraría la mejor oferta. Los fuera-de-banda se **clasifican**, nunca se descartan |
| **Precio en unidades mínimas (Woo)** | **Alto** | `729979` con `minor_unit: 2` es $7.299,79. Dividir por `10**minor_unit`; test unitario obligatorio |
| **Comparar insumos distintos** | Medio | Cemento blanco vs portland no son el mismo insumo. La banda se calcula **debajo** del vínculo confirmado |
| **Scraping de Sodimac se rompe** | Bajo | Es prioridad 4; con 7 fuentes de API pública ya no es necesaria |
| Entidades HTML en nombres | Bajo | `&#8211;` en WooCommerce: `html.unescape()` al ingestar |
| **Bloqueo por IP o reCAPTCHA** | Medio | Caché, rate limit, UA honesto, actualización manual y no automática. Easy ya tiene reCAPTCHA en el sitio público, aunque no en `/api/` |
| **MercadoLibre cambia el OAuth** | Medio | Adapter aislado; si se cae, el resto de las fuentes sigue |
| **Licencia de ODA** para DWG | Medio | v1 pide DXF; conversión automática es opcional |
| **CSV mal interpretado por Excel** | Medio | Separador `;` + UTF-8 con BOM, presets por destino |
| Entidades ACIS / 3D | Bajo | `ezdxf` no las renderiza (limitación documentada); no son cómputo 2D |
| Bloques anidados y XREFs | Medio | Resolver recursivo con tope; avisar cuando falta el XREF externo |
| Precios desactualizados | Medio | Fecha y hora obligatorias, aviso de antigüedad en el informe |

---

## 13. Lo que queda por definir

1. **¿Qué rubros usás realmente?** Arrancar con tu lista y 15-20 ítems típicos vale
   mucho más que un catálogo genérico. Es lo que más acelera las etapas 4-5.
2. **¿Qué jurisdicción?** Para la alícuota de ingresos brutos y si aplica IVA 10,5 %
   de obra de vivienda.
3. **¿Qué corralones usás vos, y de qué zona?** Es la pregunta de mayor
   rendimiento de toda la lista. Pasame los sitios y los corro por
   `tools/relevar_fuentes.py`: si alguno es VTEX o WooCommerce, entra como fuente
   con **costo cero** y es mucho mejor que Easy para tu caso, porque es el
   proveedor al que realmente le comprás. Las 7 fuentes que encontré son un punto
   de partida, no tu lista definitiva.
4. **¿Comprás por pallet o por unidad?** Define si la app tiene que priorizar la
   venta por volumen (13% más barata en cemento) o el precio unitario.
5. **¿Unidades de tus planos?** Metros, centímetros o milímetros cambia los
   defaults, aunque la calibración lo resuelve igual.

---

## 14. Próximo paso concreto

Conseguir **un DXF real tuyo** y correr:

```bash
pip install "ezdxf[draw]"
ezdxf view tu_plano.dxf     # visor incluido
ezdxf info tu_plano.dxf     # versión, unidades, estadísticas
```

Eso contesta en diez minutos las tres preguntas que más condicionan el plan: qué
convención de capas tienen tus planos, si vienen escalados, y si los contornos
están cerrados.

Y para ver las fuentes de precios con tus propios ojos, sin instalar nada:

```bash
python3 tools/relevar_fuentes.py      # que plataforma usa cada sitio
python3 tools/comparar_precios.py     # la canasta comparada, con atipicos
```

Estas dos URLs devuelven JSON directo en el navegador:

```
https://www.easy.com.ar/api/catalog_system/pub/products/search?ft=ladrillo%20hueco&_from=0&_to=9
https://laeconomica.com.ar/wp-json/wc/store/v1/products?search=cemento&per_page=5
```

**Lo más útil que podés hacer ahora** es mandarme los sitios de tus corralones
para pasarlos por `relevar_fuentes.py`. Si alguno corre WooCommerce —y muchos
corralones argentinos lo hacen— ya tenés una fuente de precios de tu proveedor
real, sin escribir una línea de scraping.
