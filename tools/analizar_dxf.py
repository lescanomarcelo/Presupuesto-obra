#!/usr/bin/env python3
"""Analiza un DXF real y contesta si sirve para computar.

    pip install "ezdxf[draw]" shapely
    python3 tools/analizar_dxf.py plano.dxf

Contesta las tres preguntas que condicionan las etapas 1 a 3 del plan:

  1. UNIDADES Y ESCALA  -- esta en metros? las medidas cierran?
  2. CONVENCION DE CAPAS -- hay capas con nombres utiles, o es todo "0"?
  3. CONTORNOS CERRADOS  -- se pueden medir areas, o las polilineas estan abiertas?

La tercera es el riesgo mas alto del plan: una polilinea que se ve cerrada en
pantalla pero no tiene el flag de cerrada no se puede medir como area. Este
script las cuenta aparte, porque son recuperables cerrandolas por tolerancia.
"""
from __future__ import annotations
import argparse, collections, math, sys

import ezdxf
from ezdxf import recover

UNIDADES = {0: "sin definir", 1: "pulgadas", 2: "pies", 4: "milimetros",
            5: "centimetros", 6: "metros", 7: "kilometros", 8: "micropulgadas",
            9: "milipulgadas", 10: "yardas", 11: "angstroms", 12: "nanometros",
            13: "micrones", 14: "decimetros", 15: "decametros", 16: "hectometros",
            17: "gigametros", 18: "unidades astronomicas", 19: "anios luz", 20: "parsecs"}

RUIDO = ("cota", "dim", "eje", "text", "carat", "rotul", "mobil", "amobl",
         "vege", "arbol", "auto", "person", "defpoints", "hatch-ruido")


def es_ruido(capa: str) -> bool:
    c = capa.lower()
    return any(p in c for p in RUIDO)


def longitud(e) -> float:
    t = e.dxftype()
    try:
        if t == "LINE":
            return e.dxf.start.distance(e.dxf.end)
        if t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
            if e.closed and len(pts) > 2:
                pts.append(pts[0])
            return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if t == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            if e.is_closed and len(pts) > 2:
                pts.append(pts[0])
            return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if t in ("ARC", "CIRCLE"):
            r = e.dxf.radius
            if t == "CIRCLE":
                return 2 * math.pi * r
            a = (e.dxf.end_angle - e.dxf.start_angle) % 360
            return math.radians(a) * r
    except Exception:
        pass
    return 0.0


def puntos(e):
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return [(p[0], p[1]) for p in e.get_points()], bool(e.closed)
    if t == "POLYLINE":
        return [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices], bool(e.is_closed)
    return None, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--tol", type=float, default=0.02,
                    help="tolerancia para considerar una polilinea 'casi cerrada' (def. 0.02)")
    a = ap.parse_args()

    try:
        doc = ezdxf.readfile(a.archivo)
        recuperado = False
    except Exception:
        doc, auditor = recover.readfile(a.archivo)      # para archivos danados
        recuperado = True

    h = doc.header
    insunits = h.get("$INSUNITS", 0)
    print("=" * 86)
    print(f"  {a.archivo}")
    print("=" * 86)
    print(f"  version DXF        : {doc.dxfversion}  ({doc.acad_release})")
    print(f"  recuperado         : {'SI (el archivo tenia errores)' if recuperado else 'no hizo falta'}")
    print(f"  unidad de insercion: {UNIDADES.get(insunits, '?')}  ($INSUNITS = {insunits})")
    try:
        emin, emax = h["$EXTMIN"], h["$EXTMAX"]
        anc, alt = emax[0] - emin[0], emax[1] - emin[1]
        print(f"  extension dibujada : {anc:.2f} x {alt:.2f} unidades")
        print(f"  origen             : el dibujo arranca en ({emin[0]:.1f}, {emin[1]:.1f})")
    except Exception:
        anc = alt = None
        print("  extension dibujada : no declarada en el header")

    msp = doc.modelspace()
    layouts = [l.name for l in doc.layouts if l.name.lower() != "model"]
    print(f"  layouts de papel   : {len(layouts)}  {layouts[:6]}")
    xrefs = [b.name for b in doc.blocks if b.block.dxf.flags & 4]
    if xrefs:
        print(f"  !! XREFs           : {len(xrefs)} -> {xrefs[:4]}  (geometria en archivos externos)")

    # ---------- 1. inventario por capa ----------
    por_capa = collections.defaultdict(collections.Counter)
    for e in msp:
        por_capa[e.dxf.layer][e.dxftype()] += 1
    total = sum(sum(c.values()) for c in por_capa.values())

    print(f"\n  1) CAPAS: {len(por_capa)} con contenido, {total:,} entidades en modelspace")
    print(f"     {'CAPA':30} {'ENT':>6}  TIPOS")
    print("     " + "-" * 74)
    for capa, c in sorted(por_capa.items(), key=lambda x: -sum(x[1].values())):
        tipos = ", ".join(f"{t}:{n}" for t, n in c.most_common(4))
        marca = "  (ruido?)" if es_ruido(capa) else ""
        print(f"     {capa[:30]:30} {sum(c.values()):>6}  {tipos[:48]}{marca}")

    utiles = {k: v for k, v in por_capa.items() if not es_ruido(k)}
    if len(por_capa) <= 2 and "0" in por_capa:
        print("\n     !! Todo esta en la capa '0': NO hay convencion de capas.")
        print("        La asignacion capa->item no sirve; hay que seleccionar a mano.")
    else:
        print(f"\n     {len(utiles)} capas potencialmente utiles para computar.")

    # ---------- 2. polilineas: cerradas, abiertas, casi cerradas ----------
    cerradas = abiertas = casi = 0
    area_cerr = 0.0
    casi_detalle = []
    for e in msp.query("LWPOLYLINE POLYLINE"):
        pts, cerrada = puntos(e)
        if not pts or len(pts) < 3:
            continue
        if cerrada:
            cerradas += 1
            try:
                from shapely.geometry import Polygon
                p = Polygon(pts)
                if p.is_valid:
                    area_cerr += p.area
            except Exception:
                pass
        else:
            d = math.dist(pts[0], pts[-1])
            if d <= a.tol:
                casi += 1
                casi_detalle.append((e.dxf.layer, d))
            else:
                abiertas += 1

    print(f"\n  2) CONTORNOS (el riesgo mas alto del plan)")
    print(f"     polilineas cerradas      : {cerradas:>5}   area total {area_cerr:,.2f} u2")
    print(f"     'casi cerradas' (<{a.tol} u) : {casi:>5}   recuperables cerrando por tolerancia")
    print(f"     abiertas de verdad       : {abiertas:>5}")
    if casi:
        cc = collections.Counter(c for c, _ in casi_detalle)
        print(f"     capas con casi-cerradas  : {dict(cc.most_common(5))}")

    # ---------- 3. hatches y bloques ----------
    hatches = list(msp.query("HATCH"))
    area_h = 0.0
    for hh in hatches:
        try:
            area_h += abs(hh.paths.external_paths()[0].area) if hasattr(hh.paths, "external_paths") else 0
        except Exception:
            pass
    print(f"\n  3) OTRAS FUENTES DE MEDIDA")
    print(f"     HATCH (areas rellenas)   : {len(hatches):>5}   <- la via mas confiable para areas")
    inserts = collections.Counter(e.dxf.name for e in msp.query("INSERT"))
    print(f"     INSERT (bloques)         : {sum(inserts.values()):>5} de {len(inserts)} bloques distintos")
    for n, c in inserts.most_common(8):
        print(f"       {n[:44]:44} x{c}")
    dims = len(msp.query("DIMENSION"))
    textos = len(msp.query("TEXT MTEXT"))
    print(f"     DIMENSION (cotas)        : {dims:>5}   <- sirven para verificar la escala")
    print(f"     TEXT / MTEXT             : {textos:>5}")

    # ---------- longitudes por capa ----------
    print(f"\n  4) LONGITUD POR CAPA (solo capas que no parecen ruido)")
    largos = collections.Counter()
    for e in msp:
        if e.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"):
            if not es_ruido(e.dxf.layer):
                largos[e.dxf.layer] += longitud(e)
    for capa, L in largos.most_common(12):
        print(f"     {capa[:34]:34} {L:>12,.2f} u")

    # ---------- veredicto ----------
    print(f"\n  VEREDICTO")
    ok_u = insunits == 6
    print(f"    {'OK      ' if ok_u else 'ATENCION'}  unidades: {UNIDADES.get(insunits,'?')}"
          + ("" if ok_u else "  -> hay que calibrar la escala a mano"))
    conv = not (len(por_capa) <= 2 and "0" in por_capa)
    print(f"    {'OK      ' if conv else 'FALTA   '}  convencion de capas ({len(por_capa)} capas)")
    med = cerradas + len(hatches)
    print(f"    {'OK      ' if med else 'FALTA   '}  fuentes de area: {cerradas} polilineas cerradas + {len(hatches)} hatches")
    if abiertas > cerradas and cerradas == 0:
        print(f"    ATENCION  {abiertas} polilineas abiertas y ninguna cerrada: las areas hay que armarlas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
