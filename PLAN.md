# Presupuesto de Obra — Plan de desarrollo

Aplicación **de escritorio para Windows** que abre un plano (DXF / DWG / IFC),
permite **medir de forma asistida** sobre él, **busca precios de materiales en
internet** —con fuentes propias de **Córdoba** más fuentes nacionales de
referencia—, y produce un **presupuesto completo** exportable a **CSV** para
importar en Excel o Google Sheets.

> Revisión 5 — zona confirmada: **Córdoba**. Incorpora el relevamiento de
> fuentes (§6), la comparativa multi-fuente y los valores raros (§7), y el panel
> de fuentes con los tres niveles, incluido el motor HTML, que pasa de prioridad
> 4 a parte de la etapa 10 (§8). Los scripts que produjeron los datos están en
> `tools/`.

---

## 1. Decisiones tomadas

| Decisión | Elección | Consecuencia |
|---|---|---|
| Plataforma | **App de escritorio, solo Windows** | Un `.exe` con instalador. Es donde vive AutoCAD/Revit |
| Entrada | DXF + DWG (AutoCAD) e **IFC exportado** de Revit | Tres pipelines, prioridades distintas (§3) |
| Revit | **IFC exportado**, no `.rvt` nativo | Evita plugin C# y licencia de Revit. `ifcopenshell` es libre |
| Medición v1 | **Medición asistida** | La app mide y calcula; vos confirmás qué es cada cosa |
| **Precios** | **Scraping / API de retail online** | Módulo nuevo, es la parte más delicada del proyecto (§6) |
| **Alcance** | **Materiales + mano de obra + equipos + gastos generales** | Presupuesto formal con coeficiente de impacto (§10) |
| **Salida** | **CSV** (+ PDF opcional más adelante) | Importable en Excel y Google Sheets (§11) |
| **Organización** | **Una carpeta por obra, visible en el explorador** | La app es el explorador del proyecto; los archivos también se abren a mano (§5) |
| **Moneda** | **Pesos, con total convertido a USD al oficial** | Tipo de dólar cambiable, oficial por defecto (§5) |
| **Alícuotas** | **Editables por obra, carga manual** | IIBB e IVA se ingresan a mano en cada proyecto; sin tabla automática (§10) |
| **Desperdicio** | **Por insumo, editable, con valores sugeridos** | Cargado en el catálogo base de `seed/` (§9) |
| **Catálogo** | **Catálogo base armado, para que lo corrijas** | 14 rubros, 15 ítems, 34 insumos, 67 líneas de APU en `seed/` |

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
| **Scraping HTML** | `selectolax` | Rápido y liviano; `html.unescape()` de stdlib para las entidades (§6) |
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
    verificador.py         detecta plataforma y decide nivel de una fuente (§8)
    salud.py               canario por fuente, fallos consecutivos, degradacion
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

## 5. Organización en disco y modelo de datos

### Una carpeta por obra

Elegiste que subir un plano cree un proyecto con su carpeta, y que la app sea un
**explorador de ese proyecto**, pudiendo además entrar a la carpeta a mano. Es
mejor que las dos opciones que te había ofrecido, y se parece a cómo funciona
AutoCAD: el proyecto es una carpeta en tu disco, no una fila escondida en una
base de datos.

```
Presupuestos/
  2026-04 Casa Pérez/
    proyecto.db              mediciones, asignaciones, presupuesto, precios usados,
                             alícuotas y coeficientes de impacto de ESTA obra
    plano/
      casa-perez.dxf         COPIA del plano original
      casa-perez.dxf.sha256  para avisar si el original cambió
    informes/
      computo.csv
      memoria-calculo.csv
      materiales.csv
      presupuesto.csv
      precios.csv
    ordenes/
      orden-merlino.csv
      orden-ferrocons.csv
```

Tres decisiones que vienen con esto:

**El plano se copia, no se referencia.** Si la app guardara solo la ruta, mover o
renombrar el archivo original rompería el proyecto meses después. Se copia a la
carpeta y se guarda el hash del original, así puede avisarte *"el plano original
cambió desde que computaste"* sin depender de que siga estando donde estaba.

**Los informes son contenido del proyecto, no exportaciones.** Viven en la
carpeta y se regeneran cuando el cómputo cambia. Eso hace que la carpeta sea
útil incluso sin abrir la app: mandás la carpeta y el otro tiene todo.

**El catálogo y los precios son globales, no del proyecto.** Van aparte, en la
carpeta de datos de la app, porque los insumos, las fuentes y el histórico de
precios se reusan entre obras:

```
%APPDATA%/PresupuestoObra/
  catalogo.db     rubros, ítems, insumos, APU, desperdicio
  precios.db      fuentes, SKU, vínculos insumo-SKU, histórico de precios
  cotizaciones.db dólar por fecha y tipo
```

**Pero el presupuesto congela los precios que usó.** Esto es importante y es
fácil equivocarse: si el presupuesto leyera `precios.db` al abrirse, un
presupuesto de marzo mostraría precios de octubre y el total cambiaría solo. Así
que `proyecto.db` guarda **copia del precio, la fuente, el link y la fecha/hora**
de cada línea. `precios.db` sigue creciendo aparte, y re-valorizar es una acción
explícita que crea una **versión nueva** del presupuesto.

### Pesos con total en dólares

Elegiste ver el total convertido, al **dólar oficial**. Eso es una tabla
`cotizacion` con fecha, tipo (oficial / MEP / blue / CCL) y valor, con **oficial
como tipo por defecto** y posibilidad de cambiarlo.

**Verificado:** `dolarapi.com/v1/dolares` responde sin autenticación y devuelve
los cuatro tipos con su fecha de actualización. Lo probé y funciona.

Dos reglas para que el número no engañe:

- **El cálculo siempre es en pesos.** El dólar es presentación, no unidad de
  cuenta. Convertir cada insumo y después sumar da distinto que sumar y después
  convertir, y lo segundo es lo correcto.
- **Todo total en USD lleva al lado la cotización y la fecha usadas.** Un
  presupuesto en dólares sin decir a qué dólar no dice nada.

### Modelo de datos (SQLite)

**Lado plano/medición**
- `proyecto` — nombre, comitente, ubicación, fecha
- `plano` — archivo, hash SHA-256, formato, unidades, factor de escala
- `perfil_capas` — conjunto de reglas **reutilizable entre planos**
- `regla` — capa o patrón → tipo de medición → ítem → factor
- `medicion` — plano, **layout**, handle de la entidad, tipo, valor crudo, valor
  final, ítem. El **layout** es obligatorio: sin él se mide dos veces el mismo
  muro en la planta y en el corte (§9)

Guardar el **handle** permite re-abrir el plano y que las mediciones sigan
apuntando a las líneas correctas. Guardar el **hash** permite avisar "este plano
cambió desde el último cómputo".

**Lado catálogo**
- `rubro` — Movimiento de suelo, Mampostería, Instalación sanitaria…
- `item` — unidad de medida + su APU (ej. "Mampostería 0,15 m, m²")
- `insumo` — material, **mano de obra** o **equipo**
- `apu_detalle` — ítem → insumo → **coeficiente de rendimiento** + **`desperdicio`**
  (% por insumo, no global: el del cerámico no es el del ladrillo — §9)
- (el `coef_impacto` dejó de estar acá: es por obra, vive en `proyecto.db` — §10)

**Lado precios (nuevo)**
- `fuente` — dominio, **tipo de adapter** (vtex / woocommerce / ml / html),
  **`tipo`** (referencia / propia), **`zona`**, **`nivel`** (automatica / html /
  link), `selectores` (solo nivel html, editables), y salud: `ultimo_ok`,
  `ultimo_error`, `fallos_consecutivos`, `estado` (§8)
- `sku` — fuente, id del producto, nombre, marca, EAN, URL, **unidad de venta**,
  **`multiplo_compra`** (pallet de 80, tira de 6 m: sirve para redondear — §9)
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

Probé 24 dominios argentinos de materiales, y después los 5 corralones
cordobeses que me pasaste (§8). Resultado del primer barrido:

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
WooCommerce— cubren 7 fuentes de este barrido, 8 contando Merlino**, que apareció
después (§8). Y cada nuevo corralón WooCommerce que aparezca
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
| **HTML por sitio** | Casa Manrique, Ferrocons, Terralon, Sodimac — selectores CSS **por sitio** | Baja, se rompe | **2 — ver §8** |

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

Corrí una canasta real contra las 7 fuentes con API del primer barrido
(`tools/comparar_precios.py`). Merlino todavía no estaba en la lista, así que
**esta banda es de AMBA**, que es justo lo que después permitió detectar que
Córdoba cotiza más caro (§8).

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

Y después aparecieron los "atípicos". El set completo tiene un `max/min` de
**94x**, y el pallet está a **72x la mediana**:

| Producto | $/kg | ¿Es un error? |
|---|---|---|
| Cemento Blanco x 25 kg | 1.638 | **No.** Es otro producto, vale ~5x |
| Cemento Rápido gris 1 kg | 2.700 | **No.** Otro producto, y envase chico |
| Cemento Blanco 1 kg | 5.600 | **No.** Otro producto + envase chico |
| **Pallet Cemento Avellaneda 25 kg (80 bolsas)** | **22.720** | **No. Es el MÁS BARATO** |

### El hallazgo que define el diseño

Ese pallet de $568.000 se marcó como atípico, a 72x la mediana. Pero:

```
$568.000 / 80 bolsas = $7.100 por bolsa  ->  $284/kg
mediana del mercado:                         $315/kg
=> el pallet esta ~10% MAS BARATO que la mediana
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
cemento hay ~10% de diferencia comprando por pallet, eso se ve. La decisión de
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

## 8. Fuentes de referencia y el panel de fuentes

Tu propuesta —**que la app muestre la lista con el link y que vos puedas ir a
verificarlo**— cambia el encuadre del módulo para mejor, así que la adopto como
principio y no como pantalla suelta.

### El cambio de encuadre: la app no es un oráculo, es un asistente

Un presupuesto lo firmás vos. Si la app presenta un número sin decir de dónde
salió, te obliga a confiar a ciegas en un scraper. Si muestra **el precio, la
fuente, la fecha y el link**, te deja hacer en dos clics lo único que da certeza:
mirar.

Por eso **el link es obligatorio en todas las fuentes, siempre**, incluso en las
automáticas. La diferencia entre niveles de fuente no es si hay link: es si el
número viene prellenado.

### Tres niveles de fuente

| Nivel | Qué significa | Qué hace la app | Esfuerzo tuyo |
|---|---|---|---|
| **AUTOMÁTICA** | API pública que devuelve JSON | Trae precio, stock y link sola | Confirmar el vínculo una vez |
| **HTML** | Hay buscador web legible, sin API | Trae precio con selectores + link. **Se rompe cuando el sitio cambie** | Revisar cada tanto |
| **LINK** | No se puede leer el precio | Guarda el link de búsqueda, te lo abre en el navegador | Cargás el precio a mano |

**El nivel LINK no es un fracaso, es un nivel legítimo.** Un corralón en nivel
LINK sigue aportando lo que más importa: queda registrado de dónde salió ese
precio y con qué fecha. Eso es trazabilidad, y es más de lo que tenés hoy en una
planilla.

### Tus cinco corralones: los verifiqué

Escribí `tools/verificar_fuente.py`, que es el prototipo del botón "Verificar"
del panel. Esto dio con los que nombraste:

| Corralón | Dominio real | Plataforma | Nivel |
|---|---|---|---|
| **Merlino** | `www.merlinosrl.com.ar` | VTEX | **AUTOMÁTICA** ✅ |
| **Casa Manrique** | `casamanrique.com.ar` | WooCommerce | **HTML** |
| **Ferrocons** | `ferrocons.com.ar` | PrestaShop | **HTML** |
| **Terralon** | `www.terralon.com.ar` | Magento | **HTML** |
| **Edificor** | `edificor.com` | VTEX (API apagada) | **LINK** |

Tres observaciones que salieron del relevamiento y valen más que la tabla:

**Merlino funciona y es tu mejor fuente nueva.** Devuelve `Cemento Normal
Avellaneda 25kg` a **$8.882**, o sea **$355/kg**. La banda de consenso de AMBA
(§7) estaba en $315/kg de mediana: **Merlino está 13% arriba**. Eso no es un error
de Merlino, es el precio real de Córdoba, y es exactamente la razón por la que
**necesitás tus fuentes locales y no las de referencia**. Si presupuestás una obra
en Córdoba con precios de Easy AMBA, te quedás 13% corto en el rubro más pesado.

**Ferrocons y Terralon son de Córdoba.** Lo que confirma lo anterior y sugiere que
tu catálogo de fuentes debería estar **agrupado por zona**, porque mezclar precios
de Córdoba y de AMBA en una misma banda de consenso la hace inservible.

**"Detecté la plataforma" no significa "puedo leer precios".** Edificor es VTEX y
devuelve 404 en la API de catálogo; Casa Manrique es WooCommerce con la REST API
apagada (`/wp-json/` da 404). Las dos huellas eran correctas y las dos fuentes son
inutilizables por API.

> De ahí la regla de verificación del panel: **el nivel de una fuente se decide
> por una búsqueda real que devuelva un precio parseable, nunca por la plataforma
> detectada.** La huella sirve para elegir qué adapter probar primero; no es
> prueba de nada.

### Una lección de un bug real

La primera corrida del verificador marcó a Merlino como LINK, cuando yo ya había
comprobado a mano que su API andaba. No era un problema de Merlino: **VTEX
responde `HTTP 206 Partial Content`** cuando se pagina con `_from`/`_to`, y mi
código exigía exactamente `200`. Una fuente perfectamente buena quedaba
descartada en silencio.

Queda como requisito explícito: **aceptar cualquier 2xx**, y que cuando una
verificación falle el panel diga *qué* falló (código HTTP, timeout, JSON
inválido), no solo "no funciona". Un falso negativo que no explica su motivo es
peor que un error.

### El panel de fuentes

Una pantalla de configuración, con la lista completa y estado visible:

```
┌─ Fuentes de precios ─────────────────────────────────────────────────────┐
│  Zona: [ Córdoba ▾ ]                      [+ Agregar fuente]  [Verificar │
│                                                                   todas] │
│  FUENTE            ZONA      NIVEL        ESTADO            ÚLTIMO OK    │
│  ───────────────────────────────────────────────────────────────────────  │
│  ● Merlino         Córdoba   AUTOMÁTICA   OK                hace 2 h  ⚙  │
│  ● Easy            Nacional  AUTOMÁTICA   OK                hace 2 h  ⚙  │
│  ▲ Casa Manrique   Córdoba   HTML         Degradada (2/5)   ayer     ⚙  │
│  ● Ferrocons       Córdoba   HTML         OK                hace 2 h  ⚙  │
│  ○ Edificor        Córdoba   LINK         manual                 —   ⚙  │
│  ✕ Terralon        Córdoba   HTML         Caída: HTTP 503    hace 6 d  ⚙  │
│                                                                          │
│  Terralon falló 5 veces seguidas y quedó pausada. Sus precios anteriores │
│  siguen guardados.                 [Reintentar]  [Pasar a LINK]  [Quitar]│
└──────────────────────────────────────────────────────────────────────────┘
```

**Agregar una fuente nueva** — pegás la dirección y la app hace el resto:

1. Normaliza el dominio y prueba también con y sin `www.` (Merlino solo responde
   con `www.`; Terralon solo como `www.terralon.com.ar`).
2. Prueba los adapters en orden: VTEX → WooCommerce → Shopify.
3. Si ninguno responde, busca un buscador HTML legible probando las rutas típicas
   de cada plataforma (`/?s=`, `/buscar?controller=search`, `/search?q=`,
   `/catalogsearch/result/?q=`).
4. **Te muestra lo que encontró**: los primeros 5 productos con su precio, para
   que veas con tus ojos que leyó bien antes de confirmar.
5. Vos le ponés nombre y zona, y queda guardada con su nivel.

Si no logró leer nada, **no la rechaza**: la ofrece como fuente LINK. Siempre hay
un camino para agregar el corralón que querés.

**Cuando una fuente se rompe** —que es el otro caso que planteaste— el criterio es
que la app lo note antes que vos:

- **Chequeo con canario.** Verificar no es pedir la home: es re-consultar **un SKU
  que ya tenés vinculado** y comprobar que el precio se parsea. Si además cambió
  más de un X% configurable, lo marca para que lo mires; puede ser aumento real o
  puede ser que el parser ahora lee otro número.
- **Nunca por un solo fallo.** Un timeout no es una fuente muerta: hace falta
  reintento con *backoff* y un contador de fallos consecutivos. El estado pasa a
  *Degradada* y solo después de N fallos a *Caída*.
- **Pausar, nunca borrar.** Una fuente caída se pausa y deja de consultarse, pero
  **su histórico de precios queda intacto** y los presupuestos que la usaron
  siguen siendo auditables. Quitar una fuente es una acción explícita tuya, con
  confirmación, y tampoco borra el histórico.
- **Degradación a LINK con un clic.** Si el scraping de Casa Manrique se rompe,
  el camino corto es pasarla a LINK: perdés el automatismo, conservás la fuente y
  el link. Mejor que perder el corralón.
- **Al abrir un presupuesto**, si alguna fuente que usa está caída o tiene precios
  viejos, lo dice arriba, no en un log.

### Fuentes de referencia vs. fuentes propias

Tu idea de separar los dos tipos es correcta y conviene que esté en el modelo:

- **Referencia** (Easy, Sodimac, Colorshop, MercadoLibre): nacionales, catálogo
  amplio, buenas para **descubrir** insumos y para tener banda de consenso. Vienen
  precargadas con la app.
- **Propias** (tus corralones): son las que **le compras**. Son las que mandan en
  el precio del presupuesto, y por eso la `fuente_preferida` de §7 normalmente va
  a apuntar acá.

En el modelo de datos, `fuente` gana tres campos: `tipo` (referencia / propia),
`zona`, y `nivel` (automatica / html / link), más los de salud: `ultimo_ok`,
`ultimo_error`, `fallos_consecutivos`, `estado`.

**El `precios.csv` de §11 pasa a ser el informe más interesante de los cuatro**,
porque ahí va la comparativa completa con una columna de link por fila. Lo abrís
en Sheets, los links son clickeables, y verificás el presupuesto entero sin abrir
la app.

### El nivel HTML sí vale la pena, y va junto con el panel

En la revisión anterior dejé el adapter HTML como prioridad 4 y pregunté si
Edificor y Terralon eran "marginales". **Esa pregunta estaba mal planteada**, y
los datos lo confirman: no son dos sitios, son ejemplos de una categoría —el
corralón local con catálogo web—, y en Córdoba esa categoría es la mayoría.

Tres números deciden:

- **3 de 5 de tus corralones quedan en HTML.** Las fuentes con API pública que
  encontré son casi todas de AMBA o cadenas grandes.
- **Merlino cotiza 13% arriba de la banda nacional.** Las fuentes locales son las
  que mandan en el número que firmás; las de referencia sirven para descubrir.
- **Si el nivel HTML no existe, 3 de 5 de tus corralones quedan en LINK**, o sea
  carga manual. El panel sin soporte HTML resuelve la mitad del problema.

Conclusión: **se construye, y va dentro de la misma etapa que el panel** (§13,
etapa 10), no en una etapa futura indefinida.

### Pero no es "un adapter genérico": eso no existe

Fui a mirar el HTML real de los tres, y la idea de un adapter con *presets por
plataforma* no sobrevive al contacto con los datos.

**La buena noticia: el precio está en el HTML del servidor.** Ninguno de los tres
lo pinta con JavaScript. Eso significa `httpx` + `selectolax` y **no** un
navegador headless tipo Playwright: muchísimo más simple, rápido y liviano para
empaquetar en el `.exe`.

**La mala: no hay marcado estándar que reusar.** Busqué datos estructurados en los
tres y no hay nada aprovechable:

| Sitio | Plataforma | JSON-LD `Product` | Marcado real del precio |
|---|---|---|---|
| Ferrocons | PrestaShop | ❌ (solo `Organization`, `WebSite`) | `<span class="product-price" content="38525.5">` |
| Casa Manrique | WooCommerce | ❌ (solo `BreadcrumbList`) | `<div class="jet-listing-dynamic-field__content">` |
| Terralon | Magento | ❌ (ningún bloque) | precios en un JSON embebido |

Esperaba encontrar JSON-LD `Product` —el marcado que los sitios mantienen por
SEO, y que por eso es estable— y **no está en ninguno**. Si estuviera, un solo
extractor habría servido para todos. No es el caso.

Peor: **Casa Manrique es WooCommerce pero su HTML no tiene marcado de
WooCommerce.** El tema está hecho con Elementor + JetEngine, así que el precio
vive en un `jet-listing-dynamic-field__content`, que es la misma clase genérica
que usan el nombre, la descripción y cualquier otro campo. No se puede distinguir
el precio por clase: hay que apoyarse en el patrón `$` o en la posición.

O sea: **un selector set por sitio, no por plataforma.** Lo que cambia es la
unidad de trabajo.

### La trampa del "x m²", que encontré de casualidad y es cara

En Ferrocons, un mismo elemento trae dos precios distintos:

```html
<span class="product-price" content="38525.5"> $ 15.985,69&nbsp;x m²
```

El atributo `content` dice **38525.5** (precio de la caja) y el texto visible dice
**$15.985,69 por m²**. Son el mismo producto: un cerámico que se vende por caja y
se publica por metro cuadrado.

**Un scraper que lea el atributo y otro que lea el texto difieren 2,4x.** Casa
Manrique tiene lo mismo (`$26.239,57 por m²`). Esto no es un detalle de
implementación: es el error de unidad de §7 reapareciendo en el nivel HTML, y es
del tipo que no se nota hasta que el presupuesto está mandado.

Requisitos que salen de esto:

- Toda fuente HTML obliga a **confirmar la unidad de venta** al vincular, no la
  adivina. El diálogo muestra el número del atributo y el del texto, y vos elegís.
- El **canario compara contra la banda de consenso de §7**, no solo contra el
  valor anterior. Un salto de 2,4x en un refresco es casi seguro un cambio de
  unidad, no un aumento, y tiene que frenar.

### Cómo se reparte el trabajo, entonces

Esto es lo que hace que la inversión valga: **separar infraestructura de carga de
datos.**

| | Qué es | Cuándo | Cuánto |
|---|---|---|---|
| **Infraestructura** | Motor de scraping, editor de selectores con botón de prueba, canario, degradación a LINK | **Etapa 10, una sola vez** | ~1-1,5 sem |
| **Cada corralón nuevo** | Pegar la URL, elegir 4 selectores con el editor, confirmar la unidad | Cuando lo necesites | **15-30 min, sin programar** |

**El adapter HTML no es una función que se termina: es infraestructura más carga
de datos.** Pagás el motor una vez; después cada corralón de la lista larga cuesta
minutos y lo podés hacer vos sin tocar código. Por eso conviene hacerlo bien y
temprano, y por eso **no** conviene escribir un adapter a medida por sitio.

Y la red de seguridad sigue siendo LINK: el día que un sitio se rediseñe y los
selectores dejen de andar en medio de un presupuesto, un clic lo pasa a LINK y
seguís trabajando.

---

## 9. Lo que hacen las apps del rubro y falta en este plan

Revisé qué saben hacer las herramientas establecidas —PlanSwift, STACK, Bluebeam
Revu, On-Screen Takeoff, y del lado hispano CostMiner, PresconIA, OneEstimate— y
encontré **dos omisiones que son errores de diseño, no mejoras opcionales.** Las
dos son baratas y las dos cambian el número final.

### Omisión 1: desperdicio — el plan calculaba de menos

Ninguna versión anterior de este plan tenía **desperdicio**, y en las apps del
rubro es un campo de primera clase: PlanSwift describe sus *assemblies* como
"material, labor, and **waste** assemblies", y en flooring menciona
"waste factors built in".

No es un detalle: **sin desperdicio el presupuesto sale corto, siempre.** Los
órdenes de magnitud habituales:

| Insumo | Desperdicio típico |
|---|---|
| Ladrillo cerámico | 5 % |
| Cerámico / porcelanato | 10 % (más si hay diagonales o recortes) |
| Hierro | 7 % (despuntes) |
| Mortero y hormigón | 5 % |
| Pintura | 5-10 % |

Dónde va: **un `desperdicio` en `apu_detalle`**, por insumo dentro del ítem, no
global. El porcentaje de un cerámico no es el de un ladrillo, y el del mismo
cerámico cambia si el local es irregular. El informe muestra cantidad neta y
cantidad con desperdicio en columnas separadas, para que se vea cuánto es cada
cosa.

### Omisión 2: redondeo a unidad de compra

Ninguna versión anterior lo tenía tampoco, y es el otro lugar donde el número
que la app calcula no es el número que vas a pagar. **No se compran 37,4 bolsas
de cemento: se compran 38.** Y si el proveedor vende por pallet cerrado de 80,
comprar 100 bolsas significa pagar 160.

Esto se conecta directamente con el hallazgo del pallet de §7. La `unidad de
venta` que ya está en `sku` y el `factor de conversión` de `insumo_sku` son
exactamente los datos que hacen falta; lo que faltaba era **usarlos al revés**:
no solo para normalizar el precio hacia abajo, también para redondear la cantidad
hacia arriba.

El `materiales.csv` pasa a tener tres cantidades, y las tres importan:

| Columna | Ejemplo | Para qué |
|---|---|---|
| Cantidad neta | 37,4 bolsas | Lo que dice el cómputo |
| Con desperdicio | 39,3 bolsas | Lo que hace falta en obra |
| **A comprar** | **40 bolsas** (o 1 pallet de 80) | **Lo que se pide al corralón** |

Y la diferencia entre la segunda y la tercera columna es información útil: si
redondear al pallet te hace comprar 80 cuando necesitás 40, quizás convenga el
precio unitario aunque sea 10 % más caro. Esa comparación la puede mostrar la app.

### Capacidades que vale la pena agregar, en orden de rendimiento

**Orden de compra por proveedor.** Como cada insumo ya tiene `fuente_preferida`,
agrupar el `materiales.csv` por fuente sale casi gratis y produce lo que de
verdad se usa: una lista por corralón, lista para mandar por WhatsApp. CostMiner
lo tiene como módulo de "órdenes". **Costo: bajo. Valor: alto.**

**Memoria de cálculo por ítem.** OneEstimate lo lista como característica
central ("cada ítem tiene su memoria de cálculo") y en la práctica argentina es lo
que te piden cuando alguien discute una cantidad. Los datos ya están en la tabla
`medicion`: es un informe que agrupa por ítem y lista las entidades, sus medidas y
la suma. **Costo: bajo, es otro CSV. Valor: alto.**

**Plantillas de presupuesto.** Igual que `perfil_capas` del lado del plano, un
conjunto de rubros e ítems precargado para "vivienda unifamiliar" o "refacción de
baño". STACK y PlanSwift venden sus librerías de *assemblies* como el principal
ahorro de tiempo. **Costo: bajo. Valor: alto si repetís tipologías.**

**Comparación de versiones del plano.** Acá es donde las apps grandes se separan:
STACK tiene *Plan Overlay* para comparar el plano revisado contra el original y
actualizar **solo** las cantidades que cambiaron, con *audit trail*. El plan
actual solo detecta por hash que el archivo cambió, y eso obliga a re-medir todo.
Para DXF se puede hacer algo mejor: comparar por `handle` de entidad y reportar
agregadas, borradas y modificadas. **Costo: medio-alto. Valor: alto, y sube con
cuántas revisiones recibas.** Va a una etapa propia, después de la v1.

**Cronograma valorado y curva de inversión.** Estándar en presupuesto formal
argentino, y presente en PresconIA y NexoSmart. Requiere plazos por rubro, que
hoy el modelo no tiene. **Fuera de v1**, pero el modelo de datos no lo impide.

**Certificación de avance.** Medir qué porcentaje de cada ítem está ejecutado
para facturar. Es un módulo distinto (seguimiento de obra, no presupuesto).
**Fuera de alcance**, anotado para no cerrarle la puerta.

### Un riesgo que encontré revisando esto: el doble conteo entre carátulas

Las apps de takeoff manejan *plan sets* de muchas hojas con *bookmarking*, y hay
una razón: **medir dos veces lo mismo en dos hojas distintas.** Un DXF suele
tener varios *layouts* (planta, cortes, vistas, detalles), y el mismo muro aparece
en la planta y en el corte.

El plan hasta ahora hablaba de `doc.modelspace()` como si hubiera un solo lugar
donde medir. No lo mencioné en ningún momento y es un agujero real. Requisitos:

- La `medicion` guarda **de qué layout** salió, además del handle.
- La app muestra qué layout estás midiendo y avisa si asignás la misma capa en
  dos layouts al mismo ítem.
- Por defecto se mide **solo en modelspace**, y pasar a otro layout es explícito.

---

## 10. Presupuesto completo

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

### Las alícuotas son datos de la obra, y se cargan a mano

Definido: **los coeficientes de impacto se ingresan manualmente y se editan por
obra**, no hay tabla de alícuotas automática ni consulta a ningún padrón. La app
trae valores por defecto y vos los ajustás en cada proyecto.

Esto tiene una consecuencia de diseño que conviene no pasar por alto: **viven en
`proyecto.db`, no en la base global.** Dos razones:

- **Cambian por obra.** No es lo mismo una refacción particular que una obra para
  un consorcio, ni la misma alícuota si el comitente es responsable inscripto o
  consumidor final.
- **Quedan congeladas con el presupuesto**, igual que los precios (§5). Un
  presupuesto de marzo tiene que seguir mostrando el IVA que se le aplicó en
  marzo, aunque la alícuota haya cambiado o vos hayas cambiado tu beneficio.

En la práctica: una pantalla de "Datos del presupuesto" con los cinco campos de
la tabla de arriba, editables, prellenados con lo último que usaste. El informe
muestra cada coeficiente aplicado con su porcentaje, para que el comitente vea de
dónde sale el total.

Queda **pendiente** y no bloquea nada: si en algún momento querés que la app
sepa las alícuotas de ingresos brutos por jurisdicción, es una tabla de datos
que se agrega después sin tocar el cálculo.

Otro detalle que importa:
**El IVA y el precio scrapeado.** El retail publica precio **con** IVA, pero la
API de VTEX también da `price_wo_taxes`. Para no contar el IVA dos veces, el
costo directo se arma **sin IVA** y el IVA se aplica una sola vez al final. Es
un error de doble conteo fácil de cometer y caro de explicar.

**Ojo con las fuentes que no dan el precio sin IVA.** Lo verifiqué fuente por
fuente y no son todas iguales:

| Fuente | ¿Trae el neto? |
|---|---|
| Easy (VTEX) | **Sí**, `price_wo_taxes` |
| **Merlino (VTEX)** | **No.** El campo no existe en su catálogo |
| WooCommerce (las 5) | **No.** La Store API no tiene ningún campo de impuesto |

Donde sí está, la semántica se confirma: Easy da `Price` 8.490 y
`price_wo_taxes` 7.016,53, y el cociente es exactamente **1,21**.

Para las que no lo traen, el neto se obtiene dividiendo por `1 + IVA`. Y el
`precio` tiene que guardar **cuál de los dos caminos se usó**: si mañana cambia
la alícuota, los netos derivados por división hay que recalcularlos y los que
vinieron de la fuente no.

**Y una trampa concreta:** VTEX tiene además un campo `Tax`, y en Merlino
devuelve **`0.0`** —también en los cementos de Easy— aunque el precio **sí**
incluye el 21 %. Un implementador que lea `Tax: 0.0` y concluya "este producto no
tiene IVA" se come un error del 21 % en el rubro más pesado. **`Tax` no sirve
para decidir nada**; el único campo confiable es `price_wo_taxes`, y cuando falta
hay que dividir.

---

## 11. El informe: CSV

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

## 12. El flujo de uso completo

1. **Abrir** el plano. La app **crea el proyecto y su carpeta**, copia el plano
   adentro, lee `$INSUNITS` y propone las unidades.
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
10. **Los informes se escriben en la carpeta del proyecto** (y se regeneran
    cuando el cómputo cambia). Si querés, ves el total en dólares con la
    cotización del día.
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

## 13. Roadmap

Cada etapa termina en algo que **se puede abrir y probar**. Estimaciones asumiendo
trabajo de a ratos, no full-time.

| # | Etapa | Entregable verificable | Est. |
|---|---|---|---|
| 0 | Esqueleto | Repo, venv, Qt abre ventana, SQLite se crea, pytest corre | 2-3 d |
| 0b | **Proyecto = carpeta** | **Abrir un DXF crea la carpeta con el plano copiado y su hash; la app lista y reabre proyectos** | **2-3 d** |
| 1 | **Visor DXF** | **Abre un DXF real, pan/zoom, capas on/off, clic en entidad muestra capa/tipo/handle** | 1-1,5 sem |
| 2 | Unidades y escala | Lee `$INSUNITS`, calibración por 2 puntos, mide una distancia correcta en metros | 3-4 d |
| 3 | Motor de medición | Longitud, área, **volumen**, conteo, **por layout**; tests con DXF sintéticos de área conocida | 1-1,5 sem |
| 4 | Catálogo y APU | **Importa `seed/` (ya hecho)** + ABM de rubros/ítems/insumos, rendimientos y desperdicio | 4-5 d |
| 5 | Cómputo → ítems | Asignación capa→ítem, perfiles guardables, explosión a insumos | 1-1,5 sem |
| 5b | **Desperdicio y redondeo** | **Cantidad neta / con desperdicio / a comprar, con múltiplo de compra** | **2-3 d** |
| 6 | **Export CSV** | **Los cinco CSV (incluida memoria de cálculo), presets Excel es-AR y Google Sheets** | 4-5 d |
| 7 | **Precios: adapters VTEX + WooCommerce** | **Busca "cemento" en las 7 fuentes, muestra candidatos, vinculás, guarda precio con fecha** | **1-1,5 sem** |
| 8 | Normalización y conversión | Factor de conversión por vínculo, extracción de peso/bulto del nombre, $/kg correcto | 4-5 d |
| 9 | **Comparativa y atípicos** | **Banda de mediana+IQR por insumo, clasificación de fuera-de-banda, "dividir por pallet", fuente preferida** | **1 sem** |
| 10 | **Panel de fuentes + niveles HTML y LINK** | **Lista con estado y link, alta por URL con autodetección, verificar, pausar, degradar. Motor de scraping con editor de selectores y botón de prueba. Carga manual con link y fecha** | **2-2,5 sem** |
| 11 | Precios: actualización y salud | Refresco por SKU, canario, caché con TTL, rate limit, histórico, re-vinculación | 1 sem |
| 12 | Coeficiente de impacto y USD | GG, beneficio, impuestos con fecha de vigencia; total en dólares vía `dolarapi` | 5-6 d |
| 13 | IFC | Abre un IFC de Revit y lee `BaseQuantities` directo, sin medir | 1-1,5 sem |
| 14 | MercadoLibre | OAuth, manejo de token y 429 | 4-5 d |
| 15 | DWG | Diálogo de conversión; ODA automático **si la licencia lo permite** | 2-4 d |
| 16 | **Instalable** | **`.exe` + instalador Inno Setup que corre en una PC sin Python** | 4-6 d |
| 17 | Orden de compra por proveedor | Agrupa `materiales.csv` por `fuente_preferida`; lista por corralón | 2-3 d |
| 18 | Plantillas de presupuesto | Rubros e ítems precargados por tipología de obra | 3-4 d |
| 19 | Comparar versiones del plano | Diff por handle entre dos DXF: agregadas, borradas, modificadas | 1-1,5 sem |

**Total aproximado hasta la etapa 16 (producto completo e instalable): 18-24
semanas de trabajo de a ratos.** Las etapas 0-6 son ~5-6 semanas y ya dejan una
herramienta usable: cómputo con desperdicio y redondeo, exportado a CSV, con
precios cargados a mano. Todo el módulo de precios (7-11) son otras ~6-7 semanas
y es la mitad del proyecto en esfuerzo y la mayor parte del riesgo.

**Por qué el CSV (etapa 6) va antes que los precios (etapa 7):** apenas tengas
cómputo y catálogo, un CSV de cantidades ya es útil por sí solo —lo abrís en
Sheets y le ponés precios a mano. Te deja una herramienta usable **seis etapas
antes** de que el módulo de precios esté listo, y el módulo de precios es el que
más riesgo tiene de estirarse.

**La etapa 1 sigue siendo el hito que vale.** Un visor que abre tu plano y te deja
apagar capas te dice si todo el enfoque funciona con tus archivos reales, antes de
invertir en el resto.

---

## 14. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Planos sin convención de capas** | **Alto** | Es la razón de elegir medición asistida |
| **Olvidar el desperdicio** | **Alto** | Sin él el presupuesto sale corto siempre. `desperdicio` por insumo en `apu_detalle`, y columnas separadas en el informe (§9) |
| **No redondear a unidad de compra** | **Alto** | No se compran 37,4 bolsas. `multiplo_compra` en `sku` y columna "a comprar" (§9) |
| **Alícuota global en vez de por obra** | Medio | Cambian por obra y tienen que quedar congeladas con el presupuesto. Viven en `proyecto.db` (§10) |
| **Derivar el precio sin IVA por división sin registrarlo** | Medio | Merlino y las fuentes Woo no dan `price_wo_taxes`. Guardar si el neto vino de la fuente o de dividir por `1+IVA` (§10) |
| **Confiar en el campo `Tax` de VTEX** | **Alto** | Devuelve `0.0` en Merlino y en los cementos de Easy aunque el precio incluye 21 %. Leerlo como "sin IVA" es un error del 21 % (§10) |
| **Presupuesto que cambia solo** | **Alto** | Si leyera el histórico vivo, un presupuesto viejo mostraría precios de hoy. `proyecto.db` **congela** precio, fuente, link y fecha; re-valorizar crea una versión nueva (§5) |
| **Convertir a USD insumo por insumo** | Medio | Da distinto que sumar en pesos y convertir el total. El cálculo es en pesos; el dólar es presentación (§5) |
| **Perder el plano original** | Medio | Se copia a la carpeta del proyecto, no se referencia; se guarda el hash del original para avisar si cambió (§5) |
| **Doble conteo entre layouts** | **Alto** | El mismo muro está en la planta y en el corte. `medicion` guarda el layout; por defecto solo modelspace (§9) |
| **Polilíneas no cerradas** | **Alto** | Problema #1 al medir áreas: tolerancia de cierre configurable + herramienta de cerrar contorno + lista de revisión |
| **Doble conteo de IVA** | **Alto** | Costo directo siempre sin IVA, usando `price_wo_taxes`; IVA una sola vez al final |
| **Vínculo insumo↔SKU equivocado** | **Alto** | La "maceta cemento" del ejemplo real: confirmación manual una vez, vínculo persistente, nunca auto-elegir |
| **Doble conteo de cantidades** | **Alto** | La UI muestra de dónde sale cada cantidad y resalta en el plano las entidades que la componen |
| **Comparar sin normalizar** | **Alto** | Es el error que convierte al pallet más barato en "atípico 72x". Normalizar a la unidad del insumo **antes** de comparar (§7) |
| **Descartar atípicos automáticamente** | **Alto** | Tiraría la mejor oferta. Los fuera-de-banda se **clasifican**, nunca se descartan |
| **Precio en unidades mínimas (Woo)** | **Alto** | `729979` con `minor_unit: 2` es $7.299,79. Dividir por `10**minor_unit`; test unitario obligatorio |
| **Comparar insumos distintos** | Medio | Cemento blanco vs portland no son el mismo insumo. La banda se calcula **debajo** del vínculo confirmado |
| **Mezclar zonas en una banda** | **Alto** | Merlino (Córdoba) está 13% arriba de la banda AMBA. La banda de consenso se calcula **por zona**, o no sirve |
| **Decidir el nivel por la huella de plataforma** | **Alto** | Edificor es VTEX sin API; Casa Manrique es Woo con la REST apagada. El nivel se decide por **una búsqueda real que devuelva precio** |
| **Falso negativo al verificar** | Medio | VTEX responde **206**, no 200: exigir 200 descartaba a Merlino. Aceptar cualquier 2xx y **mostrar siempre el motivo** del fallo |
| **Marcar una fuente muerta por un timeout** | Medio | Reintento con backoff y contador de fallos consecutivos; *Degradada* antes de *Caída*; pausar, nunca borrar |
| **Scraping HTML en 3 de 5 corralones propios** | **Alto** | Selectores como datos editables **por sitio** (no por plataforma: Casa Manrique es Woo con HTML de Elementor), canario, y degradación a LINK con un clic |
| **Leer el precio "x m²" como precio de venta** | **Alto** | Ferrocons trae `content="38525.5"` y texto `$15.985,69 x m²` en el mismo tag: 2,4x de diferencia. Confirmar la unidad al vincular y que el canario compare contra la banda de §7 |
| **Scraping de Sodimac se rompe** | Bajo | Es prioridad 4; con las fuentes de API pública ya no es necesaria |
| Entidades HTML en nombres | Bajo | `&#8211;` en WooCommerce: `html.unescape()` al ingestar |
| **Bloqueo por IP o reCAPTCHA** | Medio | Caché, rate limit, UA honesto, actualización manual y no automática. Easy ya tiene reCAPTCHA en el sitio público, aunque no en `/api/` |
| **MercadoLibre cambia el OAuth** | Medio | Adapter aislado; si se cae, el resto de las fuentes sigue |
| **Licencia de ODA** para DWG | Medio | v1 pide DXF; conversión automática es opcional |
| **CSV mal interpretado por Excel** | Medio | Separador `;` + UTF-8 con BOM, presets por destino |
| Entidades ACIS / 3D | Bajo | `ezdxf` no las renderiza (limitación documentada); no son cómputo 2D |
| Bloques anidados y XREFs | Medio | Resolver recursivo con tope; avisar cuando falta el XREF externo |
| Precios desactualizados | Medio | Fecha y hora obligatorias, aviso de antigüedad en el informe |

---

## 15. Lo que queda por definir

1. **Revisar el catálogo base de `seed/`.** Ya está armado: 14 rubros, 15 ítems,
   34 insumos y 67 líneas de APU, con desperdicio y múltiplo de compra. **Lo que
   falta es que lo corrijas**, sobre todo los coeficientes de rendimiento de mano
   de obra, que son los que más varían. Y los rubros **09 sanitaria, 10 eléctrica,
   11 gas, 12 carpinterías** están creados sin ítems a propósito: son los que más
   dependen de tu forma de trabajar.
2. **Dólar oficial** — definido. Es el tipo por defecto, cambiable.
3. **Alícuotas: carga manual, editables por obra** — definido. Sin tabla
   automática. Queda pendiente, para más adelante y sin bloquear nada, una tabla
   de ingresos brutos por jurisdicción.
4. **Zona: Córdoba** — confirmado. Es la zona por defecto. Las fuentes
   nacionales quedan como referencia para descubrir insumos, no para el precio.
5. **¿Hay más corralones cordobeses que uses?** Pasame los sitios y los corro por
   `tools/verificar_fuente.py`. Con el motor HTML de la etapa 10 ya construido,
   cada uno cuesta 15-30 min de configuración, no desarrollo.
6. **¿Comprás por pallet o por unidad?** Define si la app tiene que priorizar la
   venta por volumen (~10% más barata en cemento) o el precio unitario.
7. **¿Unidades de tus planos?** Metros, centímetros o milímetros cambia los
   defaults, aunque la calibración lo resuelve igual.

---

## 16. Próximo paso concreto

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
python3 tools/relevar_fuentes.py                      # plataforma de cada sitio
python3 tools/comparar_precios.py                     # canasta comparada, con atipicos
python3 tools/verificar_fuente.py merlinosrl.com.ar   # nivel de UNA fuente
```

Estas dos URLs devuelven JSON directo en el navegador:

```
https://www.easy.com.ar/api/catalog_system/pub/products/search?ft=ladrillo%20hueco&_from=0&_to=9
https://laeconomica.com.ar/wp-json/wc/store/v1/products?search=cemento&per_page=5
```

**Lo más útil que podés hacer ahora**, además del DXF, es pasar tus corralones
por el verificador:

```bash
python3 tools/verificar_fuente.py casamanrique.com.ar
python3 tools/verificar_fuente.py <otro-corralon-tuyo>
```

Te dice en qué nivel queda cada uno y te muestra los precios que leyó, así ves si
leyó bien. Es exactamente lo que va a hacer el botón "Verificar" del panel, y
confirma hoy si la lista de fuentes que vas a usar alcanza.

---

## 17. Errata: errores cometidos y corregidos

Registro de lo que estuvo mal en revisiones anteriores de este plan, para que no
vuelva y para saber qué está verificado y qué era suposición.

| # | Error | Dónde salió | Estado |
|---|---|---|---|
| 1 | **"El pallet está 13% más barato"** — el 13% se calculó contra la mediana del set sin filtrar ($326/kg) mientras el texto citaba la mediana filtrada ($315/kg). El valor correcto es **~10%** | Auditoría numérica de esta revisión | ✅ corregido |
| 2 | **"Atípico a 94x la mediana"** — 94,67x es el `max/min` del set completo, no la relación con la mediana. El pallet está a **72x** | Ídem | ✅ corregido |
| 3 | **Referencias cruzadas rotas** — §1 y §5 apuntaban a §7 y §8 para alcance y salida, después de dos renumeraciones de secciones | Ídem | ✅ corregido, con chequeo automático |
| 4 | **Lista de pendientes numerada 1,2,3,4,6,7** — faltaba el 5 | Ídem | ✅ corregido |
| 5 | **Contradicción de prioridad** — §6 dejaba el adapter HTML en "prioridad 4" cuando §8 ya lo había movido a la etapa 10 | Ídem | ✅ corregido |
| 6 | **Conteo de fuentes inconsistente** — "7 fuentes" en §6 y §7 sin aclarar que Merlino apareció después y hace 8 | Ídem | ✅ corregido |
| 7 | **`verificar_fuente.py` exigía HTTP 200** — VTEX responde **206** al paginar, así que marcaba a Merlino como LINK cuando su API funciona | Verificación de los 5 corralones | ✅ corregido en el código |
| 8 | **Conclusión apresurada: "Terralon no tiene web"** — probé `terralon.com.ar` y `www.terralon.com` (este último está en venta) pero **no** `www.terralon.com.ar`, que es el sitio real, en Magento | Ídem | ✅ corregido; el verificador ahora prueba con y sin `www.` |
| 9 | **Faltaba el desperdicio** — ninguna versión anterior lo tenía. El presupuesto salía corto siempre | Revisión de apps del rubro (§9) | ✅ agregado al modelo y al roadmap |
| 10 | **Faltaba el redondeo a unidad de compra** — se calculaban 37,4 bolsas de cemento | Ídem | ✅ agregado |
| 11 | **Faltaba el layout en `medicion`** — el plan trataba el DXF como si hubiera un solo lugar donde medir, habilitando doble conteo entre planta y corte | Ídem | ✅ agregado |

### Qué está verificado y qué no

Conviene tener claro el límite, porque todo el módulo de precios se apoya en esto.

**Verificado con datos reales, reproducible con `tools/`:**
- Las 8 fuentes con API pública, con muestras de precio leídas
- La banda de consenso del cemento (22 observaciones, 5 fuentes)
- Las dos trampas de WooCommerce (unidades mínimas, entidades HTML)
- La trampa del `content` vs `x m²` de Ferrocons
- Que los 3 sitios HTML sirven el precio desde el servidor, sin JavaScript
- Que ninguno de los 3 tiene JSON-LD `Product`
- Que `ezdxf` incluye `qtviewer.py` y el add-on `drawing` (documentación oficial)

**No verificado, es suposición razonable:**
- Que `ifcopenshell` lee las `BaseQuantities` de un IFC exportado de Revit **sin
  retoques**. No probé un IFC real. Es el supuesto más grande que queda en pie
- Los porcentajes de desperdicio de la tabla de §9: son valores de manual, hay
  que ajustarlos a tu práctica
- Que la licencia del ODA File Converter permita redistribuir el flujo DWG
- Los tiempos del roadmap

---
