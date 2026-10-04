# tools/ — relevamiento de fuentes de precios

Dos scripts de reconocimiento, previos a la app. No dependen de nada del
proyecto: solo la stdlib de Python 3. Sirven para repetir y verificar el
relevamiento documentado en `PLAN.md` §6 y §7.

```bash
python3 tools/relevar_fuentes.py                      # plataforma de cada sitio de una lista
python3 tools/comparar_precios.py                     # canasta comparada, con atipicos
python3 tools/verificar_fuente.py merlinosrl.com.ar   # nivel de UNA fuente
python3 tools/prueba_cadena.py                        # computo -> APU -> desperdicio -> precio
python3 tools/prueba_ifc.py                           # IFC con y sin BaseQuantities
python3 tools/analizar_ifc.py modelo.ifc --geom       # analiza un IFC REAL
```

`analizar_ifc.py` es para el archivo de verdad: lee esquema, unidades, niveles,
cuenta elementos por clase IFC, dice cuales traen BaseQuantities y cuales no, y
con `--geom` **compara las BaseQuantities contra la geometria** para ver si
coinciden. Tambien avisa de los IfcBuildingElementProxy, que son elementos sin
clasificar.

Lee las unidades de IfcUnitAssignment en vez de asumir metros: si el IFC viene
en milimetros, un volumen esta en mm3 y hay que escalar por 1e-9.

`prueba_ifc.py` necesita `pip install ifcopenshell numpy`. Construye modelos IFC
de prueba y verifica los dos caminos de lectura: las BaseQuantities exportadas y
el calculo desde la geometria. Confirma que sin BaseQuantities el volumen sale
igual y exacto, con los huecos de ventanas descontados.

`verificar_fuente.py` es el prototipo del boton "Verificar" del panel de fuentes
(PLAN.md §8). Toma un dominio, prueba con y sin `www.`, prueba los adapters en
orden (VTEX, WooCommerce, Shopify), y si ninguno responde busca un buscador HTML
legible. Devuelve el nivel de la fuente -- AUTOMATICA, HTML o LINK -- y una
muestra de los precios que leyo, para que se pueda confirmar a ojo.

`relevar_fuentes.py` prueba, para cada dominio, las huellas de las plataformas de
e-commerce con API publica conocida (VTEX, WooCommerce Store API, Shopify) y, si
no hay ninguna, clasifica la plataforma leyendo el HTML de la home.

`comparar_precios.py` consulta las fuentes que si tienen API, normaliza a $/kg
cuando puede extraer el peso del nombre, y marca los valores fuera de banda.

Ambos usan un `User-Agent` identificable, hacen pocas consultas y son de solo
lectura. Si vas a correrlos seguido, agregales cache: los sitios no tienen por
que subsidiar nuestras pruebas.

Dos cosas que estos scripts dejaron a la vista y que estan en el plan como
requisitos:

- **VTEX responde `HTTP 206`**, no 200, cuando se pagina con `_from`/`_to`.
  Exigir 200 descartaba a Merlino, que funciona perfecto.
- **"Detecte la plataforma" no es "puedo leer precios".** Edificor es VTEX con la
  API de catalogo en 404, y Casa Manrique es WooCommerce con la REST API apagada.
  El nivel se decide por una busqueda real, no por la huella.

**Nota:** `comparar_precios.py` deja a la vista el problema que justifica el
diseno asistido. Buscando "hierro aletado 8" aparece una "Prensa para
Hamburguesas Hierro 8 Cm"; buscando "cemento", una maceta. El filtrado por texto
no alcanza nunca.
