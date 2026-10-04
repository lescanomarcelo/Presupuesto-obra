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

DOS COSAS APRENDIDAS CON UN MODELO REAL DE REVIT (Villa Giardino):

1. Hay que pedir la representacion "Body" explicitamente. Los muros de Revit
   traen dos: "Axis" (la linea de eje, Curve2D) y "Body" (el solido).
   create_shape(settings, muro) sin mas falla con "Failed to process shape"
   porque intenta procesar el Axis.

2. Cuando Revit PARTE un muro en varios IfcWall, cada pedazo se lleva el Qto
   ENTERO del muro original. Sumar el Qto de cada ejemplar multiplica la
   cantidad por el numero de pedazos: medido, 12,79 m3 en vez de 1,54, un
   +730%. La geometria de los pedazos SI suma bien (11 pedazos sumaron
   exactamente el Qto unico del muro). Por eso este script informa las tres
   sumas y avisa cuando detecta Qto repetido.
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


def volumen_geom(e, fac: float) -> float:
    """Volumen por geometria. Pide la representacion Body explicitamente:
    sin eso, create_shape falla en los muros de Revit (traen tambien un Axis)."""
    import ifcopenshell.geom as geom
    import ifcopenshell.util.shape as ush
    if not e.Representation:
        return 0.0
    cuerpo = next((r for r in e.Representation.Representations
                   if r.RepresentationIdentifier == "Body"), None)
    if cuerpo is None:
        return 0.0
    try:
        return ush.get_volume(geom.create_shape(geom.settings(), e, cuerpo).geometry) * fac ** 3
    except Exception:
        return 0.0


def cantidad(e, *claves):
    for pset in uel.get_psets(e, qtos_only=True).values():
        for k in claves:
            if k in pset:
                try:
                    return float(pset[k])
                except (TypeError, ValueError):
                    pass
    return None


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
        print(f"\n  VOLUMEN POR TRES CAMINOS (hasta {a.limite} elementos por clase)")
        print(f"    {'CLASE':22} {'n':>5} {'grupos':>6} {'A) Qto x n':>11} "
              f"{'B) Qto x grupo':>14} {'C) geometria':>12}")
        print("    " + "-" * 78)
        sospechosas = []
        for clase in CLASES_INTERES:
            try:
                els = f.by_type(clase, include_subtypes=False)[:a.limite]
            except Exception:
                continue
            if not els:
                continue
            grupos: dict = {}
            sa = sc = 0.0
            for e in els:
                vq = cantidad(e, "NetVolume", "GrossVolume")
                if vq is not None:
                    vq *= fac ** 3
                    sa += vq
                    grupos.setdefault((e.Name, round(vq, 8)), []).append(e)
                sc += volumen_geom(e, fac)
            sb = sum(k[1] for k in grupos)
            if sa == 0 and sc == 0:
                continue
            print(f"    {clase:22} {len(els):>5} {len(grupos):>6} {sa:>11.3f} {sb:>14.3f} {sc:>12.3f}")
            if sc > 1e-9 and sa > 0 and abs(sa - sc) / sc > 0.05:
                sospechosas.append((clase, len(els), len(grupos), sa, sb, sc))
        print(f"\n    medidos en {time.time()-t0:.1f} s")
        if sospechosas:
            print(f"\n  !! EL Qto NO COINCIDE CON LA GEOMETRIA en estas clases:")
            for clase, n, ng, sa, sb, sc in sospechosas:
                print(f"     {clase}: {n} ejemplares pero solo {ng} valores distintos de Qto.")
                print(f"       Revit partio los elementos y copio el Qto completo en cada pedazo.")
                print(f"       Sumar por ejemplar da {sa:.3f} m3 cuando lo real es {sc:.3f} m3 "
                      f"({(sa-sc)/sc*100:+.0f}%).")
                print(f"       USAR LA GEOMETRIA (columna C), no el Qto.")

    print(f"\n  VEREDICTO")
    muros = len(f.by_type("IfcWall", include_subtypes=True))
    print(f"    {'OK' if pisos else 'FALTA'}  niveles para la planta SVG")
    print(f"    {'OK' if muros else 'FALTA'}  muros ({muros})")
    print(f"    {'OK' if fac == 1.0 else 'ATENCION'}  unidades ({nombre_unidad})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
