#!/usr/bin/env python3
"""Detecta muros en un DXF emparejando las dos caras de cada muro.

    pip install "ezdxf[draw]"
    python3 tools/detectar_muros.py plano.dxf
    python3 tools/detectar_muros.py plano.dxf --svg muros.svg

POR QUE EXISTE: en un plano real (ejemplos/julian-sol) los muros no son
polilineas, son 255 LINE sueltas, y la deteccion por capas no sirve porque todo
esta en la capa '0'. De los 7 elementos que la deteccion automatica encontraba,
el autor del plano identifico 5 como muebles y ninguno era un muro. Emparejar
caras es la unica via para medir la mamposteria de un plano asi.

COMO FUNCIONA

  1. Filtra la basura: agrupa la geometria y descarta lo que cae lejos del
     cumulo principal. En el plano de prueba habia 17 INSERT a hasta 2.500
     unidades, entre ellos 12 bloques "puerta 2" que se habrian presupuestado
     como carpinterias inexistentes.
  2. Agrupa las lineas por direccion (angulo modulo 180 grados).
  3. Dentro de cada direccion, busca pares separados por una distancia
     perpendicular compatible con un espesor de muro, y que se solapen a lo
     largo.
  4. Acepta solo los emparejamientos MUTUOS: A es el mejor candidato de B y B
     el de A. Evita que una cara se use dos veces.

El resultado es, por muro: eje, largo, espesor. Lo que no se empareja queda
listado aparte, porque son aberturas, detalles o lineas sueltas de verdad.
"""
from __future__ import annotations
import argparse, collections, math, statistics, sys

import ezdxf
from ezdxf import recover


def leer(ruta):
    try:
        return ezdxf.readfile(ruta), False
    except Exception:
        doc, _ = recover.readfile(ruta)
        return doc, True


def lineas_utiles(msp, lejania: float):
    """Devuelve (lineas, descartadas_por_lejania). Filtra el cumulo principal."""
    crudas = []
    for e in msp.query("LINE"):
        a = (e.dxf.start.x, e.dxf.start.y)
        b = (e.dxf.end.x, e.dxf.end.y)
        if math.dist(a, b) > 1e-9:
            crudas.append((a, b, e.dxf.layer))
    if not crudas:
        return [], 0
    xs = [p[0] for a, b, _ in crudas for p in (a, b)]
    ys = [p[1] for a, b, _ in crudas for p in (a, b)]
    cx, cy = statistics.median(xs), statistics.median(ys)
    dentro, fuera = [], 0
    for a, b, capa in crudas:
        d = max(abs(a[0] - cx), abs(a[1] - cy), abs(b[0] - cx), abs(b[1] - cy))
        if d <= lejania:
            dentro.append((a, b, capa))
        else:
            fuera += 1
    return dentro, fuera


def inserts_lejanos(msp, lineas, lejania: float):
    if not lineas:
        return []
    xs = [p[0] for a, b, _ in lineas for p in (a, b)]
    ys = [p[1] for a, b, _ in lineas for p in (a, b)]
    cx, cy = statistics.median(xs), statistics.median(ys)
    out = []
    for e in msp.query("INSERT"):
        p = e.dxf.insert
        if max(abs(p.x - cx), abs(p.y - cy)) > lejania:
            out.append((e.dxf.name, (p.x, p.y)))
    return out


def emparejar(lineas, esp_min, esp_max, solape_min, tol_ang):
    """Empareja caras de muro. Devuelve (muros, indices_sin_pareja)."""
    datos = []
    for a, b, capa in lineas:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        ang = math.atan2(dy, dx) % math.pi          # direccion modulo 180
        ux, uy = dx / L, dy / L
        datos.append(dict(a=a, b=b, L=L, ang=ang, u=(ux, uy), capa=capa))

    # agrupar por direccion
    grupos = collections.defaultdict(list)
    paso = math.radians(tol_ang)
    for i, d in enumerate(datos):
        grupos[round(d["ang"] / paso)].append(i)
    # incluir el grupo vecino para no cortar justo en el borde del bucket
    claves = sorted(grupos)
    candidatos = collections.defaultdict(set)
    for k in claves:
        pool = list(grupos[k]) + list(grupos.get(k + 1, [])) + list(grupos.get(k - 1, []))
        for i in pool:
            candidatos[i].update(pool)

    def evaluar(i, j):
        """Devuelve (espesor, solape) si i y j pueden ser las dos caras de un muro."""
        di, dj = datos[i], datos[j]
        if abs((di["ang"] - dj["ang"] + math.pi / 2) % math.pi - math.pi / 2) > math.radians(tol_ang):
            return None
        ux, uy = di["u"]
        nx, ny = -uy, ux                              # normal
        # distancia perpendicular entre las rectas
        esp = abs((dj["a"][0] - di["a"][0]) * nx + (dj["a"][1] - di["a"][1]) * ny)
        if not (esp_min <= esp <= esp_max):
            return None
        # solape de las proyecciones sobre la direccion
        pi0 = di["a"][0] * ux + di["a"][1] * uy
        pi1 = di["b"][0] * ux + di["b"][1] * uy
        pj0 = dj["a"][0] * ux + dj["a"][1] * uy
        pj1 = dj["b"][0] * ux + dj["b"][1] * uy
        lo = max(min(pi0, pi1), min(pj0, pj1))
        hi = min(max(pi0, pi1), max(pj0, pj1))
        sol = hi - lo
        if sol < solape_min or sol < 0.5 * min(di["L"], dj["L"]):
            return None
        return esp, sol

    # mejor candidato de cada linea
    mejor = {}
    for i in range(len(datos)):
        opciones = []
        for j in candidatos[i]:
            if j == i:
                continue
            r = evaluar(i, j)
            if r:
                esp, sol = r
                opciones.append((sol, -esp, j))        # mas solape, menos espesor
        if opciones:
            mejor[i] = max(opciones)[2]

    # solo los emparejamientos mutuos
    muros, usados = [], set()
    for i, j in mejor.items():
        if i in usados or j in usados or mejor.get(j) != i:
            continue
        esp, sol = evaluar(i, j)
        di, dj = datos[i], datos[j]
        ux, uy = di["u"]
        pi0 = di["a"][0] * ux + di["a"][1] * uy
        pi1 = di["b"][0] * ux + di["b"][1] * uy
        pj0 = dj["a"][0] * ux + dj["a"][1] * uy
        pj1 = dj["b"][0] * ux + dj["b"][1] * uy
        lo = max(min(pi0, pi1), min(pj0, pj1))
        hi = min(max(pi0, pi1), max(pj0, pj1))
        # eje: punto medio entre las dos caras, recortado al solape
        mx = (di["a"][0] + dj["a"][0]) / 2
        my = (di["a"][1] + dj["a"][1]) / 2
        base = mx * ux + my * uy
        ex = mx + (lo - base) * ux
        ey = my + (lo - base) * uy
        fx = mx + (hi - base) * ux
        fy = my + (hi - base) * uy
        muros.append(dict(eje=((ex, ey), (fx, fy)), largo=hi - lo, espesor=esp,
                          caras=(i, j), capa=di["capa"]))
        usados.add(i)
        usados.add(j)
    sueltas = [i for i in range(len(datos)) if i not in usados]
    return muros, sueltas, datos


def svg(muros, datos, sueltas, ruta):
    """Dibuja: los espesores frecuentes en color, los raros en rojo punteado
    (son candidatos a falso positivo), y lo no emparejado en naranja fino."""
    xs = [p[0] for d in datos for p in (d["a"], d["b"])]
    ys = [p[1] for d in datos for p in (d["a"], d["b"])]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    W = 1000.0
    esc = W / (x1 - x0)
    H = (y1 - y0) * esc
    T = lambda x, y: ((x - x0) * esc, H - (y - y0) * esc)

    cuenta = collections.Counter(round(m["espesor"], 2) for m in muros)
    frecuentes = [g for g, n in cuenta.most_common() if n >= 3]
    pal = ["#2563eb", "#16a34a", "#0891b2", "#9333ea", "#ca8a04"]
    color = {g: pal[k % len(pal)] for k, g in enumerate(sorted(frecuentes))}

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H+92:.0f}" '
           f'viewBox="0 0 {W:.0f} {H+92:.0f}">', '<rect width="100%" height="100%" fill="#fff"/>']
    for i in sueltas:                                    # fondo: sin pareja
        a, b = T(*datos[i]["a"]), T(*datos[i]["b"])
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                   f'stroke="#fbbf24" stroke-width="1.2"/>')
    raros = []
    for m in muros:
        g = round(m["espesor"], 2)
        a, b = T(*m["eje"][0]), T(*m["eje"][1])
        ancho = max(2.5, m["espesor"] * esc)
        if g in color:
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                       f'stroke="{color[g]}" stroke-width="{ancho:.1f}" stroke-opacity="0.5" '
                       f'stroke-linecap="butt"/>')
        else:
            raros.append(m)
            out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                       f'stroke="#dc2626" stroke-width="{ancho:.1f}" stroke-opacity="0.45" '
                       f'stroke-dasharray="7 4" stroke-linecap="butt"/>')
    for k, m in enumerate(raros):                        # numerar los sospechosos
        cx = (T(*m["eje"][0])[0] + T(*m["eje"][1])[0]) / 2
        cy = (T(*m["eje"][0])[1] + T(*m["eje"][1])[1]) / 2
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="13" fill="#dc2626"/>'
                   f'<text x="{cx:.1f}" y="{cy+5:.1f}" font-family="sans-serif" font-size="14" '
                   f'font-weight="bold" fill="#fff" text-anchor="middle">{k+1}</text>')

    largo = collections.Counter()
    for m in muros:
        largo[round(m["espesor"], 2)] += m["largo"]
    out.append(f'<rect x="8" y="{H+6:.0f}" width="{W-16:.0f}" height="78" fill="#f8fafc" '
               f'stroke="#cbd5e1"/>')
    fila, col = 0, 0
    for g in sorted(frecuentes):
        px, py = 22 + col * 330, H + 26 + fila * 24
        out.append(f'<rect x="{px}" y="{py-10}" width="26" height="11" fill="{color[g]}" fill-opacity="0.6"/>'
                   f'<text x="{px+32}" y="{py}" font-family="sans-serif" font-size="14" fill="#0f172a">'
                   f'esp. {g:.2f} m — {cuenta[g]} muros, {largo[g]:.1f} m</text>')
        col += 1
        if col == 3:
            col, fila = 0, fila + 1
    py = H + 26 + (fila + 1) * 24
    out.append(f'<line x1="22" y1="{py-5}" x2="48" y2="{py-5}" stroke="#dc2626" stroke-width="4" '
               f'stroke-dasharray="7 4"/>'
               f'<text x="54" y="{py}" font-family="sans-serif" font-size="14" fill="#0f172a">'
               f'{len(raros)} espesores raros, numerados — revisar si son muros</text>')
    out.append(f'<line x1="562" y1="{py-5}" x2="588" y2="{py-5}" stroke="#fbbf24" stroke-width="3"/>'
               f'<text x="594" y="{py}" font-family="sans-serif" font-size="14" fill="#0f172a">'
               f'{len(sueltas)} lineas sin pareja</text>')
    out.append("</svg>")
    open(ruta, "w", encoding="utf-8").write("\n".join(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--esp-min", type=float, default=0.05)
    ap.add_argument("--esp-max", type=float, default=0.60)
    ap.add_argument("--solape-min", type=float, default=0.30)
    ap.add_argument("--tol-ang", type=float, default=1.5, help="grados")
    ap.add_argument("--lejania", type=float, default=40.0,
                    help="descarta geometria a mas de N unidades del cumulo principal")
    ap.add_argument("--svg", default=None)
    a = ap.parse_args()

    doc, recuperado = leer(a.archivo)
    msp = doc.modelspace()
    lineas, fuera = lineas_utiles(msp, a.lejania)
    bloques_lejos = inserts_lejanos(msp, lineas, a.lejania)

    print("=" * 84)
    print(f"  {a.archivo}")
    print("=" * 84)
    print(f"  lineas en el cumulo principal : {len(lineas)}")
    if fuera:
        print(f"  lineas descartadas por lejanas: {fuera}")
    if bloques_lejos:
        c = collections.Counter(n for n, _ in bloques_lejos)
        print(f"  !! {len(bloques_lejos)} INSERT fuera del plano, NO se computan: {dict(c)}")

    muros, sueltas, datos = emparejar(lineas, a.esp_min, a.esp_max, a.solape_min, a.tol_ang)

    print(f"\n  MUROS DETECTADOS: {len(muros)}  (de {len(lineas)} lineas, "
          f"{len(sueltas)} quedaron sin pareja)")
    if muros:
        por_esp = collections.defaultdict(list)
        for m in muros:
            por_esp[round(m["espesor"], 2)].append(m["largo"])
        print(f"\n     {'ESPESOR':>9} {'MUROS':>6} {'LARGO TOTAL':>13} {'largo medio':>12}")
        print("     " + "-" * 44)
        for esp in sorted(por_esp):
            ls = por_esp[esp]
            print(f"     {esp:>8.2f} m {len(ls):>6} {sum(ls):>11.2f} m {statistics.mean(ls):>11.2f} m")
        print("     " + "-" * 44)
        print(f"     {'TOTAL':>9} {len(muros):>6} {sum(m['largo'] for m in muros):>11.2f} m")
        print(f"\n     muro mas largo: {max(m['largo'] for m in muros):.2f} m")
        print(f"     muro mas corto: {min(m['largo'] for m in muros):.2f} m")

    L_sueltas = sum(datos[i]["L"] for i in sueltas)
    print(f"\n  SIN PAREJA: {len(sueltas)} lineas, {L_sueltas:.2f} m en total")
    print("     Son aberturas, detalles, mobiliario dibujado a mano o caras cuyo")
    print("     par quedo fuera del rango de espesor. Hay que revisarlas a ojo.")

    if a.svg:
        svg(muros, datos, sueltas, a.svg)
        print(f"\n  {a.svg} generado: muros por espesor, y en naranja lo que no se emparejo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
