import json, re, ssl, statistics as st, concurrent.futures as cf
import urllib.request, urllib.error, urllib.parse

UA="PresupuestoObra/0.1 (relevamiento tecnico)"
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE

# Zona AMBA / nacional
VTEX=["www.easy.com.ar","www.colorshop.com.ar",
      # Zona Cordoba
      "www.merlinosrl.com.ar"]
WOO=["laeconomica.com.ar","latejamateriales.com","centralmaterialesya.com",
     "germatsrl.com","grupocanarias.com.ar"]

def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=25,context=CTX) as r: return json.loads(r.read().decode("utf-8","ignore"))
    except Exception: return None

def from_vtex(dom,q):
    d=get(f"https://{dom}/api/catalog_system/pub/products/search?ft={urllib.parse.quote(q)}&_from=0&_to=19")
    out=[]
    for p in (d or []):
        try:
            o=p["items"][0]["sellers"][0]["commertialOffer"]
            if not o.get("IsAvailable"): continue
            wo=p.get("price_wo_taxes"); wo=float(wo[0]) if isinstance(wo,list) and wo else None
            out.append(dict(fuente=dom,nombre=p["productName"],precio=float(o["Price"]),sin_iva=wo,url=p.get("link","")))
        except Exception: pass
    return out

def from_woo(dom,q):
    d=get(f"https://{dom}/wp-json/wc/store/v1/products?search={urllib.parse.quote(q)}&per_page=20")
    out=[]
    for p in (d or []):
        try:
            pr=p["prices"]; mu=int(pr.get("currency_minor_unit",2))
            val=float(pr["price"])/(10**mu)
            if val<=0: continue
            out.append(dict(fuente=dom,nombre=p["name"],precio=val,sin_iva=None,url=p.get("permalink","")))
        except Exception: pass
    return out

def buscar(q):
    jobs=[(from_vtex,d) for d in VTEX]+[(from_woo,d) for d in WOO]
    res=[]
    with cf.ThreadPoolExecutor(max_workers=7) as ex:
        futs={ex.submit(f,d,q):d for f,d in jobs}
        for fu in cf.as_completed(futs):
            try: res+=fu.result() or []
            except Exception: pass
    return res

KG=re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kg|kilos?)\b",re.I)
def kg_de(n):
    m=KG.search(n)
    if m:
        v=float(m.group(1).replace(",","."))
        if 1<=v<=1500: return v
    return None

def tabla(titulo,q,normaliza_kg=False,filtro=None):
    rows=buscar(q)
    if filtro: rows=[r for r in rows if filtro(r["nombre"].lower())]
    for r in rows:
        r["kg"]=kg_de(r["nombre"])
        r["unit"]=(r["precio"]/r["kg"]) if (normaliza_kg and r["kg"]) else None
    print(f"\n{'='*104}\n{titulo}   (busqueda: \"{q}\")\n{'='*104}")
    if not rows: print("  sin resultados"); return []
    key="unit" if normaliza_kg else "precio"
    comp=[r for r in rows if r.get(key)]
    comp.sort(key=lambda r:r[key])
    hdr=f"{'FUENTE':26} {'PRODUCTO':46} {'PRECIO':>11}"
    if normaliza_kg: hdr+=f" {'$/kg':>9}"
    print(hdr); print("-"*104)
    for r in comp:
        line=f"{r['fuente'][:26]:26} {r['nombre'][:46]:46} {r['precio']:>11,.0f}"
        if normaliza_kg: line+=f" {r['unit']:>9,.1f}"
        print(line)
    vals=[r[key] for r in comp]
    if len(vals)>=3:
        med=st.median(vals)
        print("-"*104)
        print(f"  n={len(vals)}  min={min(vals):,.1f}  mediana={med:,.1f}  max={max(vals):,.1f}  "
              f"max/min={max(vals)/min(vals):.2f}x")
        out=[r for r in comp if r[key]<med*0.5 or r[key]>med*2]
        if out:
            print(f"  ATIPICOS (fuera de 0,5x-2x la mediana):")
            for r in out: print(f"    - {r['fuente'][:20]:20} {r['nombre'][:44]:44} {r[key]:,.1f}")
    return comp

tabla("CEMENTO - normalizado a $/kg","cemento",normaliza_kg=True,
      filtro=lambda n:"cemento" in n and not any(w in n for w in ["maceta","mesa","banco","adhesiv","pastina","revestim","piso","porcelan","silicona","cola"]))
tabla("LADRILLO HUECO - precio por unidad","ladrillo hueco",
      filtro=lambda n:"ladrillo" in n or "hueco" in n)
tabla("CAL - normalizado a $/kg","cal hidratada",normaliza_kg=True,
      filtro=lambda n:"cal " in n or n.startswith("cal"))
tabla("HIERRO ALETADO 8mm - por barra","hierro aletado 8",
      filtro=lambda n:("hierro" in n or "varilla" in n or "aletado" in n))
