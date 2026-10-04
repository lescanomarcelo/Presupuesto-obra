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

2. El Qto de Revit NO es confiable, y no hay regla que lo arregle. En el MISMO
   archivo:
     - IfcWall: 48 ejemplares de 7 Tags, el Qto esta REPETIDO en cada pedazo.
       Sumar por ejemplar da 12,79 m3 cuando lo real es 1,54: +730%.
     - IfcWallStandardCase: 132 ejemplares de 34 Tags, el Qto esta REPARTIDO
       por pedazo. Sumar por ejemplar da el valor correcto.
   Los dos casos son muros partidos y se ven igual en la estructura del
   archivo. Probe deduplicar por (nombre, valor) y por Tag: cada heuristica
   arregla una clase y rompe la otra (por Tag: muros +5,7% pero pilares -76%).
   Por eso este script usa la GEOMETRIA como respuesta y el Qto solo como
   control, sin intentar repararlo.

3. Al leer el Qto hay que aceptar NetVolume O GrossVolume. En IfcColumn faltan
   265 de 1383 NetVolume; con el respaldo, el total vuelve a coincidir.
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
        print(f"\n  VOLUMEN: la geometria es la respuesta, el Qto es el control")
        print(f"    {'CLASE':24} {'n':>5} {'GEOMETRIA m3':>13} {'Qto (control)':>14} {'dif':>8}")
        print("    " + "-" * 74)
        discrepan = []
        for clase in CLASES_INTERES:
            try:
                els = f.by_type(clase, include_subtypes=False)[:a.limite]
            except Exception:
                continue
            if not els:
                continue
            sq = sg = 0.0
            sin_net = 0
            for e in els:
                # NetVolume o, si falta, GrossVolume: en IfcColumn faltan 265 de 1383
                vq = cantidad(e, "NetVolume", "GrossVolume")
                if cantidad(e, "NetVolume") is None:
                    sin_net += 1
                if vq is not None:
                    sq += vq * fac ** 3
                sg += volumen_geom(e, fac)
            if sq == 0 and sg == 0:
                continue
            dif = f"{(sq-sg)/sg*100:+.1f}%" if sg > 1e-9 and sq > 0 else "-"
            print(f"    {clase:24} {len(els):>5} {sg:>13.3f} {sq:>14.3f} {dif:>8}"
                  + (f"   ({sin_net} sin NetVolume)" if sin_net else ""))
            if sg > 1e-9 and sq > 0 and abs(sq - sg) / sg > 0.05:
                tags = len({e.Tag for e in els})
                discrepan.append((clase, len(els), tags, sq, sg))
        print(f"\n    medidos en {time.time()-t0:.1f} s")
        if discrepan:
            print(f"\n  !! El Qto no coincide con la geometria en:")
            for clase, n, tags, sq, sg in discrepan:
                print(f"     {clase}: {n} ejemplares, {tags} Tags de Revit.")
                print(f"       Qto {sq:.3f} m3 contra {sg:.3f} m3 de geometria ({(sq-sg)/sg*100:+.0f}%).")
            print("     Revit reparte el Qto de forma inconsistente entre los pedazos de un")
            print("     elemento partido: en una clase lo repite y en otra lo divide, y las dos")
            print("     se ven igual en el archivo. NO se puede reparar deduplicando.")
            print("     El computo usa la columna GEOMETRIA. Esta discrepancia es informativa.")

    print(f"\n  VEREDICTO")
    muros = len(f.by_type("IfcWall", include_subtypes=True))
    print(f"    {'OK' if pisos else 'FALTA'}  niveles para la planta SVG")
    print(f"    {'OK' if muros else 'FALTA'}  muros ({muros})")
    print(f"    {'OK' if fac == 1.0 else 'ATENCION'}  unidades ({nombre_unidad})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
