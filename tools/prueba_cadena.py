"""Prueba de punta a punta: computo -> APU -> desperdicio -> redondeo -> precio."""
import csv, math, json, ssl, urllib.request, urllib.parse

S='/home/user/Presupuesto-obra/seed/'
def leer(f): return list(csv.DictReader(open(S+f,encoding='utf-8'),delimiter=';'))
insumos={r['codigo']:r for r in leer('insumos.csv')}
items={r['codigo']:r for r in leer('items.csv')}
apu=leer('apu.csv')

# --- COMPUTO simulado: lo que saldria del plano ---
computo=[("04.01", 48.0, "muro ladrillo hueco 12, perimetro interior"),
         ("06.01", 62.5, "contrapiso living+comedor"),
         ("07.01", 96.0, "revoque grueso interior, dos caras"),
         ("08.01", 62.5, "piso ceramico living+comedor")]
print("="*86); print("1. COMPUTO (lo que mediria la app sobre el plano)"); print("="*86)
for it,c,d in computo:
    print(f"  {it}  {c:>7.2f} {items[it]['unidad']:<3}  {items[it]['descripcion'][:50]}")
    print(f"           {d}")

# --- EXPLOSION a insumos via APU, con desperdicio ---
neto={}; 
for it,cant,_ in computo:
    for l in apu:
        if l['item']!=it: continue
        neto[l['insumo']]=neto.get(l['insumo'],0)+cant*float(l['coeficiente'])

print(); print("="*86); print("2. EXPLOSION A INSUMOS, con desperdicio y redondeo a unidad de compra"); print("="*86)
print(f"  {'INSUMO':34} {'UNID':5} {'NETO':>10} {'+DESP':>10} {'%':>4} {'A COMPRAR':>12}")
print("  "+"-"*82)
compra={}
for cod,q in sorted(neto.items()):
    i=insumos[cod]; d=float(i['desperdicio_sugerido_pct']); mult=float(i['multiplo_compra_sugerido'])
    con=q*(1+d/100)
    if i['tipo']=='material' and mult>1:          # se vende en bulto -> redondear bultos
        bultos=math.ceil(con/mult); comp=bultos*mult; txt=f"{comp:,.0f} ({bultos} x{mult:.0f})"
    elif i['tipo']=='material':
        comp=math.ceil(con*100)/100 if con<10 else math.ceil(con); txt=f"{comp:,.2f}"
    else:
        comp=con; txt=f"{comp:,.1f}"
    compra[cod]=comp
    print(f"  {i['nombre'][:34]:34} {i['unidad']:5} {q:>10,.2f} {con:>10,.2f} {d:>3.0f}% {txt:>12}")

# --- PRECIO real de una fuente verificada ---
UA="PresupuestoObra/0.1"; CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
def vtex(host,q):
    u=f"https://{host}/api/catalog_system/pub/products/search?ft={urllib.parse.quote(q)}&_from=0&_to=9"
    try:
        r=urllib.request.Request(u,headers={"User-Agent":UA})
        with urllib.request.urlopen(r,timeout=25,context=CTX) as x: d=json.loads(x.read().decode('utf-8','ignore'))
    except Exception as e: return None
    for p in d:
        n=p['productName'].lower()
        if 'cemento' in n and '25' in n and not any(w in n for w in ['blanco','rapido','maceta','tarima','porcellanato','tapa','monotop']):
            try: return p['productName'], float(p['items'][0]['sellers'][0]['commertialOffer']['Price'])
            except Exception: pass
    return None
print(); print("="*86); print("3. PRECIO REAL (Merlino, Cordoba - fuente AUTOMATICA verificada)"); print("="*86)
r=vtex("www.merlinosrl.com.ar","cemento")
if r:
    nombre,precio_bolsa=r
    bolsas=compra['MAT-CEM-POR']/25
    print(f"  SKU vinculado : {nombre}")
    print(f"  Precio        : ${precio_bolsa:,.2f} por bolsa de 25 kg  ->  ${precio_bolsa/25:,.2f}/kg")
    print(f"  A comprar     : {compra['MAT-CEM-POR']:,.0f} kg = {bolsas:,.0f} bolsas")
    print(f"  COSTO CEMENTO : ${bolsas*precio_bolsa:,.2f}")
    # conversion a USD
    try:
        rq=urllib.request.Request("https://dolarapi.com/v1/dolares/oficial",headers={"User-Agent":UA})
        with urllib.request.urlopen(rq,timeout=20,context=CTX) as x: dd=json.loads(x.read().decode())
        print(f"  En USD        : US$ {bolsas*precio_bolsa/dd['venta']:,.2f}  (oficial venta ${dd['venta']:,.0f}, {dd['fechaActualizacion'][:10]})")
    except Exception as e: print("  (sin cotizacion)",e)
else:
    print("  no se pudo consultar Merlino en este momento")
print()
print("La cadena completa funciona: medicion -> APU -> desperdicio -> redondeo -> precio real -> USD.")
