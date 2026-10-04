import json, re, concurrent.futures as cf, urllib.request, urllib.error, ssl, sys

UA = "PresupuestoObra/0.1 (relevamiento tecnico; contacto en repo)"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

DOMAINS = [
 "www.easy.com.ar","www.sodimac.com.ar","materialesmoreno.com.ar","laeconomica.com.ar",
 "latejamateriales.com","www.corralonlasquintas.com.ar","www.corralon-fernandes.com",
 "www.corralonfer.com","centralmaterialesya.com","elalbanil.com.ar","www.trazarshop.com",
 "germatsrl.com","www.aconmateriales.com.ar","grupocanarias.com.ar","www.rodomateriales.com.ar",
 "corralonelmolino.com.ar","www.barugelazulay.com","www.colorshop.com.ar",
 "www.pinturerias-rex.com.ar","www.hierrosmoreno.com.ar","www.construyaonline.com.ar",
 "www.blancotejerina.com.ar","www.corralonsanjose.com.ar","servidos.ar",
]

PROBES = [
 ("VTEX",    "/api/catalog_system/pub/products/search?ft=cemento&_from=0&_to=1"),
 ("WOO",     "/wp-json/wc/store/v1/products?search=cemento&per_page=2"),
 ("WOO_v0",  "/wp-json/wc/store/products?search=cemento&per_page=2"),
 ("SHOPIFY", "/products.json?limit=2"),
 ("ROOT",    "/"),
]

def fetch(url, limit=120000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return r.status, r.headers.get("content-type",""), r.read(limit)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type","") if e.headers else "", b""
    except Exception as e:
        return None, type(e).__name__, b""

def classify_root(body):
    t = body.decode("utf-8","ignore").lower()
    hits = []
    for name, pat in [
        ("tiendanube", r"tiendanube|nuvemshop|d2r9epyceweg5n\.cloudfront"),
        ("woocommerce", r"woocommerce|wp-content/plugins/woo"),
        ("wordpress", r"wp-content|wp-includes"),
        ("vtex", r"vtex"),
        ("shopify", r"cdn\.shopify|shopify"),
        ("magento", r"mage-init|static/version"),
        ("prestashop", r"prestashop"),
        ("mercadoshops", r"mercadoshops"),
        ("nextjs", r"__next_data__|/_next/"),
    ]:
        if re.search(pat, t): hits.append(name)
    return hits

def probe(dom):
    out = {"dominio": dom, "api": None, "plataforma": [], "detalle": ""}
    for name, path in PROBES:
        st, ct, body = fetch(f"https://{dom}{path}")
        if name == "ROOT":
            if st and 200 <= st < 400:
                out["plataforma"] = classify_root(body)
            else:
                out["detalle"] = f"root {st}/{ct}"
            continue
        if st and 200 <= st < 300 and "json" in (ct or "").lower() and body.strip()[:1] in (b"[", b"{"):
            try:
                d = json.loads(body.decode("utf-8","ignore"))
            except Exception:
                continue
            n = len(d) if isinstance(d, list) else len(d.get("products", []) or [])
            if n:
                out["api"] = f"{name} ({n} res)"
                break
    return out

with cf.ThreadPoolExecutor(max_workers=8) as ex:
    rows = list(ex.map(probe, DOMAINS))

print(f"{'DOMINIO':34} {'API PUBLICA':22} PLATAFORMA DETECTADA")
print("-"*100)
for r in sorted(rows, key=lambda x: (x["api"] is None, x["dominio"])):
    print(f"{r['dominio']:34} {str(r['api'] or '-'):22} {','.join(r['plataforma']) or r['detalle']}")
