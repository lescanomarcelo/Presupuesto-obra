# tools/ — relevamiento de fuentes de precios

Dos scripts de reconocimiento, previos a la app. No dependen de nada del
proyecto: solo la stdlib de Python 3. Sirven para repetir y verificar el
relevamiento documentado en `PLAN.md` §6 y §7.

```bash
python3 tools/relevar_fuentes.py     # que plataforma usa cada sitio y si tiene API publica
python3 tools/comparar_precios.py    # canasta comparada entre fuentes, con atipicos
```

`relevar_fuentes.py` prueba, para cada dominio, las huellas de las plataformas de
e-commerce con API publica conocida (VTEX, WooCommerce Store API, Shopify) y, si
no hay ninguna, clasifica la plataforma leyendo el HTML de la home.

`comparar_precios.py` consulta las fuentes que si tienen API, normaliza a $/kg
cuando puede extraer el peso del nombre, y marca los valores fuera de banda.

Ambos usan un `User-Agent` identificable, hacen pocas consultas y son de solo
lectura. Si vas a correrlos seguido, agregales cache: los sitios no tienen por
que subsidiar nuestras pruebas.

**Nota:** `comparar_precios.py` deja a la vista el problema que justifica el
diseno asistido. Buscando "hierro aletado 8" aparece una "Prensa para
Hamburguesas Hierro 8 Cm"; buscando "cemento", una maceta. El filtrado por texto
no alcanza nunca.
