#!/usr/bin/env python3
"""Analiza un IFC REAL y dice si sirve para computar.

    pip install ifcopenshell
    python3 tools/analizar_ifc.py modelo.ifc
    python3 tools/analizar_ifc.py modelo.ifc --geom     # ademas mide la geometria

Responde, sobre el archivo de verdad:
  - esquema, unidades y niveles
  - cuantos elementos hay de cada clase IFC
  - cuales traen BaseQuantities y cuales no
  - si las BaseQuantities COINCIDEN con la geometria (el punto de confianza)
  - que elementos quedarian sin clasificar (IfcBuildingElementProxy)

Las unidades importan: si el IFC esta en milimetros, un volumen viene en mm3 y
hay que escalar por 1e-9. Se lee de IfcUnitAssignment, no se asume.
"""
from __future__ import annotations
import argparse, collections, sys, time

import ifcopenshell
import ifcopenshell.util.element as uel

CLASES_INTERES = ["IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcBeam", "IfcColumn",
                  "IfcDoor", "IfcWindow", "IfcCovering", "IfcRoof", "IfcStair",
                  "IfcFooting", "IfcPlate", "IfcMember", "IfcSpace",
                  "IfcBuildingElementProxy"]

PREFIJOS = {"EXA":1e18,"PETA":1e15,"TERA":1e12,"GIGA":1e9,"MEGA":1e6,"KILO":1e3,
            "HECTO":1e2,"DECA":1e1,"DECI":1e-1,"CENTI":1e-2,"MILLI":1e-3,
            "MICRO":1e-6,"NANO":1e-9}


def factor_longitud(f) -> tuple[float, str]:
    """Metros por unidad de longitud del archivo. Un IFC en mm da 0.001."""
    for ua in f.by_type("IfcUnitAssignment"):
        for u in ua.Units:
            if getattr(u, "UnitType", None) != "LENGTHUNIT":
                continue
            if u.is_a("IfcSIUnit"):
                fac = PREFIJOS.get(u.Prefix, 1.0) if u.Prefix else 1.0
                return fac, f"{u.Prefix or ''}{u.Name}"
            if u.is_a("IfcConversionBasedUnit"):
                try:
                    return float(u.ConversionFactor.ValueComponent.wrappedValue), u.Name
                except Exception:
                    return 1.0, f"{u.Name} (factor no leido)"
    return 1.0, "no declarada (se asume metro)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--geom", action="store_true", help="medir tambien la geometria (lento)")
    ap.add_argument("--limite", type=int, default=400, help="maximo de elementos a medir con --geom")
    a = ap.parse_args()

    t0 = time.time()
    f = ifcopenshell.open(a.archivo)      # OJO: hay que retener `f` (ver prueba_ifc.py)
    fac, nombre_unidad = factor_longitud(f)

    print("=" * 86)
    print(f"  {a.archivo}")
    print("=" * 86)
    print(f"  esquema           : {f.schema}")
    print(f"  unidad de longitud: {nombre_unidad}   (1 unidad = {fac} m)")
    if fac != 1.0:
        print(f"  !! OJO: NO esta en metros. Areas x {fac**2:g}, volumenes x {fac**3:g}")
    print(f"  entidades totales : {len(f.by_type('IfcRoot')):,}")
    print(f"  abierto en        : {time.time()-t0:.2f} s")

    pisos = f.by_type("IfcBuildingStorey")
    print(f"\n  NIVELES ({len(pisos)}):")
    for p in pisos:
        elev = getattr(p, "Elevation", None)
        print(f"    {p.Name or '(sin nombre)':30} elev={f'{elev*fac:+.2f} m' if elev is not None else '-'}")
    if not pisos:
        print("    NINGUNO. ifcopenshell.draw no va a poder generar la planta.")

    print(f"\n  ELEMENTOS POR CLASE, y cuantos traen BaseQuantities:")
    print(f"    {'CLASE':28} {'TOTAL':>7} {'con Qto':>8} {'%':>6}  CANTIDADES QUE TRAE")
    print("    " + "-" * 78)
    sin_qto = collections.Counter()
    for clase in CLASES_INTERES:
        try:
            els = f.by_type(clase, include_subtypes=False)
        except Exception:
            continue
        if not els:
            continue
        con, campos = 0, collections.Counter()
        for e in els:
            q = uel.get_psets(e, qtos_only=True)
            if q:
                con += 1
                for pset in q.values():
                    campos.update(k for k in pset if k != "id")
            else:
                sin_qto[clase] += 1
        top = ", ".join(k for k, _ in campos.most_common(4)) or "-"
        pct = con / len(els) * 100
        print(f"    {clase:28} {len(els):>7,} {con:>8,} {pct:>5.0f}%  {top[:44]}")

    proxy = len(f.by_type("IfcBuildingElementProxy", include_subtypes=False))
    if proxy:
        print(f"\n  !! {proxy:,} IfcBuildingElementProxy: elementos SIN clasificar. En Revit son")
        print(f"     familias genericas o categorias mal mapeadas. Hay que asignarlos a mano.")
    if sin_qto:
        print(f"\n  Clases sin BaseQuantities (se calculan por geometria):")
        for c, n in sin_qto.most_common():
            print(f"    {c:30} {n:,}")

    if a.geom:
        import ifcopenshell.geom as geom
        import ifcopenshell.util.shape as ush
        print(f"\n  COMPARACION Qto vs GEOMETRIA (hasta {a.limite} elementos)")
        print(f"    {'CLASE':24} {'n':>5} {'vol Qto':>12} {'vol geom':>12} {'dif':>8}")
        print("    " + "-" * 68)
        s = geom.settings()
        it = geom.iterator(s, f, include=[c for c in ("IfcWall","IfcWallStandardCase","IfcSlab","IfcColumn","IfcBeam") if f.by_type(c, include_subtypes=False)])
        acum = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
        n = 0
        if it.initialize():
            while n < a.limite:
                sh = it.get()
                el = f.by_id(sh.id)
                clase = el.is_a()
                try:
                    vg = ush.get_volume(sh.geometry) * fac**3
                except Exception:
                    vg = None
                vq = None
                for pset in uel.get_psets(el, qtos_only=True).values():
                    for k in ("NetVolume", "GrossVolume"):
                        if k in pset:
                            vq = float(pset[k]) * fac**3
                            break
                r = acum[clase]
                r[0] += 1
                if vg: r[2] += vg
                if vq: r[1] += vq
                if vq and vg and abs(vg) > 1e-9 and abs(vq-vg)/vg > 0.02: r[3] += 1
                n += 1
                if not it.next():
                    break
        for clase, (cnt, vq, vg, disc) in sorted(acum.items()):
            dif = f"{(vq-vg)/vg*100:+.1f}%" if vg > 1e-9 and vq > 0 else "-"
            print(f"    {clase:24} {cnt:>5} {vq:>12.3f} {vg:>12.3f} {dif:>8}"
                  + (f"   {disc} elementos difieren >2%" if disc else ""))
        print(f"\n    medidos {n} elementos en {time.time()-t0:.1f} s")
        if not acum:
            print("    no se pudo medir ninguno: el kernel no genero geometria")

    print(f"\n  VEREDICTO")
    muros = len(f.by_type("IfcWall", include_subtypes=True))
    print(f"    {'OK' if pisos else 'FALTA'}  niveles para la planta SVG")
    print(f"    {'OK' if muros else 'FALTA'}  muros ({muros})")
    print(f"    {'OK' if fac == 1.0 else 'ATENCION'}  unidades ({nombre_unidad})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
