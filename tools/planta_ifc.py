#!/usr/bin/env python3
"""Genera la planta de un nivel de un IFC como SVG, con un path por elemento.

    pip install ifcopenshell shapely numpy
    python3 tools/planta_ifc.py modelo.ifc                 # lista los niveles
    python3 tools/planta_ifc.py modelo.ifc "Nivel 0"       # dibuja ese nivel
    python3 tools/planta_ifc.py modelo.ifc "Nivel 0" -o planta.svg

POR QUE NO USAMOS ifcopenshell.draw: en 0.9.0 falla o se cuelga con un modelo
real de Revit. Probado contra un export de Revit 2023 con 18 niveles:
  - sin filtros          -> el proceso muere sin dejar traza
  - storey_filter="..."  -> TypeError: can only concatenate list (not "tuple")
  - include_entities     -> AttributeError: 'SwigPyObject' has no attribute 'is_a'
Construirla nosotros son 40 lineas, tarda 2,4 s para 416 elementos y queda bajo
nuestro control.

EL DETALLE QUE HAY QUE SABER: geometry.verts viene en coordenadas LOCALES. La
posicion esta aparte, en shape.transformation.matrix, y hay que aplicarla a mano.
Sin eso todos los elementos se apilan en el origen: medido, los 19 pilotes de un
nivel caian en un cuadrado de 0,20 x 0,20 m y la planta entera salia de
15,24 x 8,75 m en vez de 9,95 x 11,41.

Los volumenes NO se ven afectados: el volumen es invariante a la posicion. Por eso
el computo puede estar bien y la planta mal, y conviene probar las dos cosas.
"""
from __future__ import annotations
import argparse, collections, sys, time

import numpy as np
import ifcopenshell
import ifcopenshell.geom as geom
from shapely.geometry import Polygon
from shapely.ops import unary_union

COLORES = {"IfcWall": "#2563eb", "IfcWallStandardCase": "#1d4ed8",
           "IfcColumn": "#dc2626", "IfcBeam": "#16a34a", "IfcSlab": "#f59e0b",
           "IfcRoof": "#0891b2", "IfcBuildingElementProxy": "#a855f7"}


def elementos_del_nivel(f, nombre: str) -> list:
    out = []
    for st in f.by_type("IfcBuildingStorey"):
        if st.Name != nombre:
            continue
        for rel in f.get_inverse(st):
            if rel.is_a("IfcRelContainedInSpatialStructure") and rel.RelatingStructure == st:
                out += list(rel.RelatedElements)
    return out


def huella(e):
    """Poligono XY del solido, en coordenadas de mundo."""
    if not e.Representation:
        return None
    rep = next((r for r in e.Representation.Representations
                if r.RepresentationIdentifier == "Body"), None)
    if rep is None:
        return None
    try:
        sh = geom.create_shape(geom.settings(), e, rep)
    except Exception:
        return None
    v = np.array(sh.geometry.verts).reshape(-1, 3)
    m = np.array(sh.transformation.matrix).reshape(4, 4).T
    v = (m[:3, :3] @ v.T).T + m[:3, 3]          # local -> mundo. Imprescindible.
    caras = np.array(sh.geometry.faces).reshape(-1, 3)
    tri = []
    for a, b, c in caras:
        p = Polygon([v[a][:2], v[b][:2], v[c][:2]])
        if p.is_valid and p.area > 1e-9:
            tri.append(p)
    if not tri:
        return None
    u = unary_union(tri)
    return None if u.is_empty else u


def a_svg(polis, ancho=900.0) -> str:
    minx = min(p.bounds[0] for _, p in polis)
    miny = min(p.bounds[1] for _, p in polis)
    maxx = max(p.bounds[2] for _, p in polis)
    maxy = max(p.bounds[3] for _, p in polis)
    esc = ancho / (maxx - minx)
    alto = (maxy - miny) * esc

    def d(poly):
        gs = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
        s = ""
        for g in gs:
            for anillo in [g.exterior] + list(g.interiors):
                s += "M" + " L".join(f"{(x-minx)*esc:.1f},{alto-(y-miny)*esc:.1f}"
                                     for x, y in anillo.coords) + " Z "
        return s

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:ifc="http://ifcopenshell.org/" '
           f'width="{ancho:.0f}" height="{alto:.0f}" viewBox="0 0 {ancho:.0f} {alto:.0f}">',
           '<rect width="100%" height="100%" fill="#f8fafc"/>']
    for e, h in sorted(polis, key=lambda x: -x[1].area):   # grandes abajo
        out.append(f'<path d="{d(h)}" fill="{COLORES.get(e.is_a(), "#94a3b8")}" '
                   f'fill-opacity="0.5" stroke="#1e293b" stroke-width="0.7" '
                   f'ifc:guid="{e.GlobalId}" ifc:class="{e.is_a()}">'
                   f'<title>{e.is_a()} — {(e.Name or "")[:70]}</title></path>')
    out.append("</svg>")
    return "\n".join(out), (maxx - minx, maxy - miny)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("nivel", nargs="?")
    ap.add_argument("-o", "--salida", default=None)
    a = ap.parse_args()

    f = ifcopenshell.open(a.archivo)          # retener: el kernel usa este objeto
    niveles = f.by_type("IfcBuildingStorey")
    if not a.nivel:
        print(f"{len(niveles)} niveles en {a.archivo}:\n")
        for st in niveles:
            n = len(elementos_del_nivel(f, st.Name))
            print(f"  {st.Name or '(sin nombre)':36} {n:>5} elementos")
        print("\nPasá el nombre de uno como segundo argumento para dibujarlo.")
        return 0

    t = time.time()
    els = elementos_del_nivel(f, a.nivel)
    if not els:
        print(f"El nivel {a.nivel!r} no existe o no tiene elementos.", file=sys.stderr)
        return 1
    polis = [(e, h) for e in els if (h := huella(e)) is not None]
    if not polis:
        print("Ningún elemento produjo geometría.", file=sys.stderr)
        return 1
    svg, (anc, alt) = a_svg(polis)
    destino = a.salida or f"planta_{a.nivel.replace(' ', '_')}.svg"
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"{destino}: {len(polis)}/{len(els)} elementos, {anc:.2f} x {alt:.2f} m, "
          f"{time.time()-t:.1f} s")
    print(f"  por clase: {dict(collections.Counter(e.is_a() for e, _ in polis))}")
    print(f"  cada <path> lleva ifc:guid, así que un clic devuelve el objeto IFC")
    return 0


if __name__ == "__main__":
    sys.exit(main())
