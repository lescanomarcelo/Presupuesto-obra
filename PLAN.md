# Presupuesto de Obra — Plan de desarrollo

Aplicación **de escritorio local** que abre un plano (DXF / DWG / IFC), permite
**medir de forma asistida** sobre él y produce un **cómputo métrico y presupuesto
de materiales** exportable a Excel y PDF.

---

## 1. Decisiones ya tomadas

| Decisión | Elección | Consecuencia |
|---|---|---|
| Plataforma | App de escritorio instalable | Abre archivos del disco directo, sin internet, datos locales |
| Entrada | DXF + DWG (AutoCAD) e IFC (Revit) | Tres pipelines de lectura, con prioridades distintas (ver §3) |
| Automatización v1 | **Medición asistida** | La app mide y calcula; vos confirmás qué es cada cosa |

La medición asistida es la decisión más importante del plan: evita el pozo sin
fondo de "adivinar" qué representa cada línea de un plano ajeno, y aun así
automatiza la parte tediosa (medir, multiplicar, acumular por rubro).

---

## 2. Stack y por qué

**Python 3.12 + Qt (PySide6).**

La razón es concreta y no es preferencia personal: las dos librerías que resuelven
el 80% del problema son Python-first y no tienen equivalente maduro en otro
lenguaje.

| Pieza | Librería | Qué aporta |
|---|---|---|
| Lectura DXF | `ezdxf` 1.4.x | Entidades, capas, bloques, textos, unidades del header |
| **Visor del plano** | `ezdxf.addons.drawing` (`PyQtBackend`, `qtviewer.py`) | **Visor CAD con pan/zoom ya implementado** — se usa como base, no se escribe de cero |
| Lectura IFC | `ifcopenshell` 0.9 | Objetos BIM reales con áreas y volúmenes ya calculados |
| Geometría | `shapely` | Áreas de polígonos, cierre de contornos, validación |
| Base de datos | SQLite + SQLAlchemy | Local, un archivo, cero instalación de servidor |
| Export | `openpyxl` (Excel), `PyMuPDF` (PDF) | Planillas y carátulas |
| Empaquetado | PyInstaller | `.exe` instalable en Windows |

**Hallazgo clave:** el add-on `drawing` de ezdxf incluye `qtviewer.py`, descrito en
la documentación oficial como "the core of a simple DXF viewer", más un ejemplo
`cad_viewer.py` listo para lanzar. El visor —que parecía la parte más cara— sale de
ahí: derivamos el esqueleto y le agregamos encima la capa de selección y medición.

**Por qué no web/Electron:** habría que rehacer el parsing con `dxf-parser` +
`three.js` y perder `ifcopenshell`. Más trabajo y peor resultado.

---

## 3. El problema de los tres formatos (y cómo lo resolvemos)

Los tres formatos elegidos **no son igual de difíciles**. Conviene atacarlos en
este orden:

### DXF — prioridad 1, es el camino real
Formato abierto y de texto. `ezdxf` lo lee nativamente (R12 hasta R2018) y tiene
`recover.readfile()` para archivos corruptos, que en la práctica son muchos.
Todo el desarrollo del motor de medición se hace contra DXF.

### IFC — prioridad 2, es el caso *ideal*
Un IFC de Revit no tiene líneas: tiene **muros, losas y pisos como objetos**, con
sus `BaseQuantities` (área, volumen, longitud) ya calculadas por Revit. Acá el
cómputo no se mide, **se lee**. Es el escenario de mayor precisión y el que
requiere menos intervención del usuario. Vale la pena llegar a esto.

### DWG — prioridad 3, y tiene un problema de licencia
DWG es formato cerrado; `ezdxf` **no lo lee**. Las opciones:

1. **ODA File Converter** — `ezdxf.addons.odafc` lo envuelve
   (`odafc.readfile('my.dwg')`). **Atención:** la página de descarga de Open Design
   Alliance hoy dice *"ODA software free for 60 days"*. Históricamente era descarga
   libre; **hay que verificar los términos actuales antes de apoyar el producto en
   esto.** Es un riesgo de licencia, no técnico.
2. **LibreDWG** (`dwg2dxf`) — libre, pero GPL (contagia la licencia) y soporte
   incompleto en DWG recientes.
3. **Exportar a DXF desde AutoCAD** — un `SAVEAS` manual. Cero costo, cero riesgo.

**Recomendación:** v1 soporta DWG mostrando un diálogo *"convertí este archivo a
DXF"* con instrucciones, y la conversión automática vía ODA queda como mejora
opcional una vez aclarada la licencia. No bloquear el proyecto por esto.

---

## 4. Arquitectura

Separación estricta entre **leer el plano**, **medir** y **presupuestar**. Esto
permite que el día que entre IFC, o que quieras cómputo sin plano, no se toque el
resto.

```
app/
  ui/                  Qt: ventana, visor, paneles, diálogos
    viewer.py            visor derivado de ezdxf qtviewer + selección
    panel_capas.py       capas on/off, asignación capa -> ítem
    panel_computo.py     tabla de mediciones acumuladas
    panel_presupuesto.py planilla por rubros
  readers/             -> devuelven un "Documento" normalizado
    dxf_reader.py
    ifc_reader.py
    dwg_reader.py        (convierte y delega en dxf_reader)
  measure/             motor de medición, SIN Qt ni SQL
    units.py             $INSUNITS + calibración manual de escala
    rules.py             reglas capa -> tipo de medición -> ítem
    engine.py            longitud / área / conteo / volumen
  budget/              cómputo -> presupuesto, SIN Qt
    apu.py               análisis de precio unitario
    pricing.py           precios con fecha y moneda
    rollup.py            agregación por rubro, incidencias
  db/                  SQLAlchemy, migraciones
  export/              Excel, PDF
tests/
```

Regla de oro: `measure/` y `budget/` son Python puro y testeable. Si para probar
un cómputo hace falta abrir una ventana, el diseño está mal.

---

## 5. Modelo de datos (SQLite)

Dos mitades que se tocan en un solo punto: la medición produce **cantidades**, el
catálogo las convierte en **plata**.

**Lado plano/medición**
- `proyecto` — nombre, comitente, ubicación, fecha
- `plano` — archivo, hash SHA-256, formato, unidades, factor de escala
- `perfil_capas` — conjunto de reglas **reutilizable entre planos**
- `regla` — capa o patrón → tipo de medición → ítem → factor
- `medicion` — plano, handle de la entidad, tipo, valor crudo, valor final, ítem

Guardar el **handle** de cada entidad es lo que permite re-abrir el plano y que las
mediciones sigan apuntando a las líneas correctas. Guardar el **hash** permite
avisar "este plano cambió desde el último cómputo".

**Lado catálogo/precios**
- `rubro` — Movimiento de suelo, Mampostería, Instalación sanitaria…
- `item` — unidad de medida + su APU (ej. "Mampostería 0,15 m, m²")
- `insumo` — material, mano de obra o equipo
- `apu_detalle` — ítem → insumo → **coeficiente de rendimiento**
- `precio` — insumo, valor, moneda, **fecha**, fuente
- `presupuesto` / `presupuesto_linea` — cantidad, PU, total

**El coeficiente de rendimiento es el corazón del cálculo de materiales.** Un m² de
mampostería de 0,15 m no consume "ladrillos": consume ~57 ladrillos + 0,03 m³ de
mortero + X horas de oficial. Ese coeficiente es lo que convierte geometría en
lista de materiales, y es un dato que vos cargás una vez y reutilizás siempre.

**Precios con fecha obligatoria.** Con la inflación argentina, un presupuesto sin
fecha de precios no sirve. Cada precio lleva fecha y fuente, y la app avisa cuando
un presupuesto usa precios con más de N días.

---

## 6. El flujo de medición asistida (la pantalla central)

1. **Abrir** el plano. La app lee `$INSUNITS` del header y propone las unidades.
2. **Calibrar escala** si hace falta: clic en dos puntos de una cota conocida,
   escribir la medida real. Resuelve de una vez los planos mal escalados, que son
   la mitad de los planos.
3. **Ver las capas** en un panel, con contar de entidades por capa. Apagar las que
   son ruido (cotas, ejes, amoblamiento, carátula).
4. **Asignar**: por cada capa relevante, elegir tipo de medición e ítem.
   - `MUROS` → longitud → *Mampostería 0,15 m* (× altura 2,60 → m²)
   - `PISOS` → área → *Contrapiso + carpeta*
   - `ABERTURAS` → conteo de bloques → *Carpintería* (desglosado por nombre de bloque)
   - `SANITARIOS` → conteo → *Artefactos*
5. **Computar**. La app recorre las entidades y acumula. Las mediciones dudosas
   —polilínea no cerrada, área absurda, capa sin asignar— van a una **lista de
   revisión**, no se descartan en silencio.
6. **Revisar y corregir** a mano cualquier línea; toda medición es editable y queda
   marcada como ajustada manualmente.
7. **Presupuestar**: cantidades × APU × precios → planilla por rubros con
   incidencia %.
8. **Guardar el perfil de capas**. La próxima vez que abras un plano del mismo
   estudio, los pasos 3-4 ya están resueltos. **Acá está el puente hacia la
   extracción automática**: cuando tengas 5 o 6 perfiles buenos, la opción
   "automático por capas" es aplicar un perfil y revisar.

Qué extrae `ezdxf` para cada tipo:
- **Longitud** — `LWPOLYLINE`/`POLYLINE`/`LINE`/`ARC` → recorrer vértices
- **Área** — `HATCH` tiene sus *boundary paths* (lo más confiable); polilínea
  cerrada → `shapely.Polygon.area`
- **Conteo** — entidades `INSERT` agrupadas por nombre de bloque
- **Volumen** — área o longitud × un espesor/altura paramétrico del ítem

---

## 7. Roadmap por etapas

Cada etapa termina en algo que **se puede abrir y probar**, no en código a medio
camino. Las estimaciones asumen trabajo de a ratos, no full-time.

| # | Etapa | Entregable verificable | Est. |
|---|---|---|---|
| 0 | Esqueleto | Repo, venv, Qt abre una ventana vacía, SQLite se crea, pytest corre | 2-3 d |
| 1 | **Visor DXF** | **Abre un DXF real, pan/zoom, panel de capas on/off, clic en una entidad muestra capa/tipo/handle** | 1-1,5 sem |
| 2 | Unidades y escala | Lee `$INSUNITS`, herramienta de calibración por 2 puntos, mide una distancia correcta en metros | 3-4 d |
| 3 | Motor de medición | Longitud, área, conteo sobre capas elegidas; tests con DXF sintéticos de área conocida | 1-1,5 sem |
| 4 | Catálogo y APU | Cargar rubros/ítems/insumos/precios y coeficientes; ABM completo | 1 sem |
| 5 | Cómputo → presupuesto | Asignación capa→ítem, perfiles guardables, planilla por rubros con incidencias | 1-1,5 sem |
| 6 | Export | Excel por rubros y PDF con carátula | 3-4 d |
| 7 | **IFC** | Abre un IFC de Revit y lee `BaseQuantities` directo, sin medir | 1-1,5 sem |
| 8 | DWG | Diálogo de conversión; ODA automático **si la licencia lo permite** | 2-4 d |
| 9 | Empaquetado | `.exe` instalable que corre en una PC sin Python | 3-5 d |

**La etapa 1 es el hito que vale.** Un visor que abre tu plano y te deja apagar
capas ya te dice si todo el enfoque funciona con tus archivos reales, antes de
invertir en el resto. Si en la etapa 1 descubrimos que tus planos vienen sin
convención de capas, replanificamos ahí y no en la etapa 6.

---

## 8. Riesgos reales

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Licencia de ODA** para DWG | Medio | v1 pide DXF; conversión automática es opcional |
| **Planos sin convención de capas** | **Alto** | Es exactamente la razón de elegir medición asistida |
| **Polilíneas no cerradas** | **Alto** | Es el problema #1 al medir áreas: tolerancia de cierre configurable + herramienta manual de cerrar contorno + lista de revisión |
| Entidades ACIS / 3D | Bajo | `ezdxf` no las renderiza (limitación documentada). No son cómputo 2D |
| Bloques anidados y XREFs | Medio | Resolver recursivo con tope de profundidad; los XREF externos avisar que falta el archivo |
| Precios desactualizados | Medio | Fecha obligatoria, aviso de antigüedad, actualización por índice |
| Doble conteo | **Alto** | Que la UI muestre *de dónde* sale cada cantidad y permita ver las entidades que la componen resaltadas en el plano |

---

## 9. A definir antes de arrancar

1. **Revit: ¿IFC o nativo?** El plan asume IFC exportado. Leer `.rvt` nativo
   requiere la API de Revit (plugin C#, licencia) y cambiaría el enfoque.
2. **¿Unidades de los planos?** Metros, centímetros o milímetros cambia los
   defaults, aunque la calibración lo resuelve igual.
3. **¿Qué rubros usás realmente?** Arrancar con tu lista de rubros y 15-20 ítems
   típicos vale más que un catálogo genérico.
4. **¿Un solo usuario?** Si en algún momento son varios, SQLite sigue sirviendo
   pero conviene saberlo ahora.
5. **¿Mano de obra dentro del presupuesto o solo materiales?** Dijiste "presupuesto
   de materiales", pero el modelo de APU ya soporta mano de obra y equipo. Decidir
   si la v1 los muestra.

---

## 10. Próximo paso concreto

Conseguir **un DXF real tuyo** y correr contra él:

```bash
pip install ezdxf[draw]
ezdxf view tu_plano.dxf     # visor incluido
ezdxf info tu_plano.dxf     # versión, unidades, estadísticas
```

Eso contesta en diez minutos las preguntas que más condicionan el plan: qué
convención de capas tienen tus planos, si vienen escalados, y si los contornos
están cerrados. Con esa información arrancamos la etapa 0 sin suposiciones.
