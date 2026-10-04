#!/usr/bin/env python3
"""Verifica si un sitio de corralon puede usarse como fuente de precios.

    python3 tools/verificar_fuente.py merlinosrl.com.ar
    python3 tools/verificar_fuente.py https://casamanrique.com.ar otro-termino

Es el prototipo de lo que hace el boton "Verificar" del panel de fuentes
(PLAN.md §8). Clasifica la fuente en uno de tres niveles:

  AUTOMATICA  hay API publica: la app trae el precio sola
  HTML        hay buscador web pero no API: scraping con selectores, fragil
  LINK        no se puede leer: la app guarda el link y vos verificas a mano

La regla importante: el nivel NO se decide por la plataforma detectada, sino
por una busqueda real que devuelva un precio parseable. Detectar "WooCommerce"
no prueba nada: Casa Manrique es WooCommerce con la REST API apagada.
"""
import html, json, re, ssl, sys, urllib.error, urllib.parse, urllib.request

UA = "PresupuestoObra/0.1 (verificacion de fuente; uso personal)"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def pedir(url, limite=400_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return r.status, r.headers.get("content-type", ""), r.read(limite)
    except urllib.error.HTTPError as e:
        return e.code, "", b""
    except Exception as e:
        return None, type(e).__name__, b""


def probar_vtex(host, q):
    url = f"https://{host}/api/catalog_system/pub/products/search?ft={urllib.parse.quote(q)}&_from=0&_to=4"
    st, ct, body = pedir(url)
    # OJO: VTEX responde 206 Partial Content cuando se pagina con _from/_to.
    # Exigir exactamente 200 descarta en silencio una fuente que funciona.
    if not (st and 200 <= st < 300) or "json" not in ct.lower():
        return None, f"HTTP {st}"
    try:
        datos = json.loads(body.decode("utf-8", "ignore"))
    except Exception:
        return None, "JSON invalido"
    items = []
    for p in datos:
        try:
            of = p["items"][0]["sellers"][0]["commertialOffer"]
            sin_iva = p.get("price_wo_taxes")
            items.append({
                "nombre": html.unescape(p["productName"]),
                "precio": float(of["Price"]),
                "sin_iva": float(sin_iva[0]) if isinstance(sin_iva, list) and sin_iva else None,
                "stock": bool(of.get("IsAvailable")),
                "url": p.get("link", ""),
            })
        except Exception:
            continue
    return (items, url) if items else (None, "respondio pero sin productos")


def probar_woo(host, q):
    for ruta in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
        url = f"https://{host}{ruta}?search={urllib.parse.quote(q)}&per_page=5"
        st, ct, body = pedir(url)
        if not (st and 200 <= st < 300) or "json" not in ct.lower():
            continue
        try:
            datos = json.loads(body.decode("utf-8", "ignore"))
        except Exception:
            continue
        items = []
        for p in datos:
            try:
                pr = p["prices"]
                # OJO: WooCommerce devuelve el precio en unidades minimas.
                minimas = int(pr.get("currency_minor_unit", 2))
                valor = float(pr["price"]) / (10 ** minimas)
                if valor <= 0:
                    continue
                items.append({
                    "nombre": html.unescape(p["name"]),
                    "precio": valor,
                    "sin_iva": None,
                    "stock": bool(p.get("is_in_stock")),
                    "url": p.get("permalink", ""),
                })
            except Exception:
                continue
        if items:
            return items, url
    return None, "sin respuesta util"


def probar_shopify(host, q):
    url = f"https://{host}/products.json?limit=5"
    st, ct, body = pedir(url)
    if not (st and 200 <= st < 300) or "json" not in ct.lower():
        return None, f"HTTP {st}"
    try:
        datos = json.loads(body.decode("utf-8", "ignore")).get("products", [])
    except Exception:
        return None, "JSON invalido"
    items = []
    for p in datos:
        try:
            v = p["variants"][0]
            items.append({"nombre": html.unescape(p["title"]), "precio": float(v["price"]),
                          "sin_iva": None, "stock": v.get("available", True),
                          "url": f"https://{host}/products/{p.get('handle','')}"})
        except Exception:
            continue
    return (items, url) if items else (None, "sin productos")


BUSCADORES_HTML = [
    "/?s={q}&post_type=product",          # WordPress / WooCommerce
    "/buscar?controller=search&s={q}",    # PrestaShop
    "/search?q={q}",                      # Tiendanube y varios
    "/catalogsearch/result/?q={q}",       # Magento
]

HUELLAS = [
    ("woocommerce", r"woocommerce"), ("wordpress", r"wp-content|wp-includes"),
    ("vtex", r"vtex"), ("tiendanube", r"tiendanube|nuvemshop"),
    ("prestashop", r"prestashop"), ("shopify", r"cdn\.shopify"),
    ("magento", r"mage-init"), ("mercadoshops", r"mercadoshops"),
    ("wix", r"wixstatic|wix\.com"), ("nextjs", r"__next_data__|/_next/"),
]
PRECIO = re.compile(r"\$\s?\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\$\s?\d+(?:,\d{2})?")


def huellas_y_buscador(host, q):
    st, ct, body = pedir(f"https://{host}/")
    plataformas = []
    if st and 200 <= st < 400:
        texto = body.decode("utf-8", "ignore").lower()
        plataformas = [n for n, p in HUELLAS if re.search(p, texto)]
    buscador = None
    for patron in BUSCADORES_HTML:
        url = f"https://{host}" + patron.format(q=urllib.parse.quote(q))
        st2, ct2, body2 = pedir(url)
        if st2 == 200 and "html" in (ct2 or "").lower():
            texto2 = body2.decode("utf-8", "ignore")
            if len(PRECIO.findall(texto2)) >= 3 and q.split()[0].lower() in texto2.lower():
                buscador = url
                break
    return plataformas, buscador


def verificar(entrada, q="cemento"):
    host = urllib.parse.urlparse(entrada if "//" in entrada else "https://" + entrada).netloc or entrada
    candidatos = [host] if host.startswith("www.") else [host, "www." + host]

    for h in candidatos:
        for nombre, fn in (("VTEX", probar_vtex), ("WooCommerce", probar_woo), ("Shopify", probar_shopify)):
            items, info = fn(h, q)
            if items:
                return {"nivel": "AUTOMATICA", "host": h, "adapter": nombre,
                        "endpoint": info, "muestra": items[:5]}

    for h in candidatos:
        plataformas, buscador = huellas_y_buscador(h, q)
        if buscador:
            return {"nivel": "HTML", "host": h, "adapter": "html_generico",
                    "endpoint": buscador, "plataformas": plataformas, "muestra": []}
        if plataformas:
            return {"nivel": "LINK", "host": h, "adapter": None, "endpoint": f"https://{h}/",
                    "plataformas": plataformas, "muestra": [],
                    "motivo": "la plataforma se detecta pero no expone API ni buscador legible"}

    return {"nivel": "LINK", "host": host, "adapter": None, "endpoint": None,
            "plataformas": [], "muestra": [],
            "motivo": "el sitio no respondio: puede no existir, estar caido o no tener web"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    entrada = sys.argv[1]
    q = sys.argv[2] if len(sys.argv) > 2 else "cemento"
    r = verificar(entrada, q)

    print(f"\n{'='*74}\n  {entrada}   (busqueda de prueba: \"{q}\")\n{'='*74}")
    print(f"  Nivel     : {r['nivel']}")
    print(f"  Host      : {r['host']}")
    print(f"  Adapter   : {r['adapter'] or '-'}")
    print(f"  Endpoint  : {r['endpoint'] or '-'}")
    if r.get("plataformas"):
        print(f"  Plataforma: {', '.join(r['plataformas'])}")
    if r.get("motivo"):
        print(f"  Motivo    : {r['motivo']}")
    if r["muestra"]:
        print(f"\n  Muestra ({len(r['muestra'])} productos, prueba de que se puede leer el precio):")
        for it in r["muestra"]:
            iva = f"  sinIVA {it['sin_iva']:>9,.2f}" if it["sin_iva"] else ""
            print(f"    {it['nombre'][:46]:46} $ {it['precio']:>10,.2f}{iva}")
    print()
    if r["nivel"] == "AUTOMATICA":
        print("  => Se puede agregar como fuente automatica. La app trae el precio sola.")
    elif r["nivel"] == "HTML":
        print("  => Se puede agregar con scraping HTML. Funciona, pero se rompe cuando")
        print("     el sitio cambie el diseño. Conviene revisarla cada tanto.")
    else:
        print("  => Agregala como fuente de tipo LINK: la app guarda la direccion, te la")
        print("     abre en el navegador y vos cargas el precio a mano. Sigue siendo util:")
        print("     queda registrado de donde salio el precio, con fecha.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
