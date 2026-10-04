#!/usr/bin/env python3
"""Verifica el supuesto mas grande que tenia el plan: que pasa si el IFC
exportado de Revit NO trae BaseQuantities.

    pip install ifcopenshell numpy
    python3 tools/prueba_ifc.py

Construye dos modelos IFC equivalentes -- uno con Qto_WallBaseQuantities y otro
sin -- y un tercero con un hueco de ventana, y prueba los dos caminos de lectura:

  PLAN A  leer las BaseQuantities que exporto Revit (ifcopenshell.util.element)
  PLAN B  calcular desde la geometria real del solido (ifcopenshell.geom)

Resultado medido: el PLAN B da el volumen EXACTO (error 0,0000%), con y sin
huecos. O sea que la ausencia de BaseQuantities no es un bloqueante.

OJO con elegir la funcion correcta de ifcopenshell.util.shape:
  get_area       superficie TOTAL de las 6 caras   -> NO sirve para revoque
  get_side_area  area de las caras verticales      -> SI, y descuenta el hueco
"""
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.shape as ush

L, T, H = 4.0, 0.20, 2.60      # muro
VW, HW = 1.20, 1.10            # ventana


def _base(f):
    mk = f.create_entity
    unidades = [mk("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE"),
                mk("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE"),
                mk("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE")]
    origen = mk("IfcCartesianPoint", Coordinates=(0., 0., 0.))
    ax = mk("IfcAxis2Placement3D", Location=origen)
    ctx = mk("IfcGeometricRepresentationContext", ContextType="Model",
             CoordinateSpaceDimension=3, Precision=1e-5, WorldCoordinateSystem=ax)
    mk("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Prueba",
       UnitsInContext=mk("IfcUnitAssignment", Units=unidades), RepresentationContexts=[ctx])
    return mk, ax, ctx


def _extruido(mk, dx, dy, dz, px, py, pz):
    pos2 = mk("IfcAxis2Placement2D", Location=mk("IfcCartesianPoint", Coordinates=(0., 0.)))
    perfil = mk("IfcRectangleProfileDef", ProfileType="AREA", XDim=dx, YDim=dy, Position=pos2)
    pl = mk("IfcAxis2Placement3D", Location=mk("IfcCartesianPoint", Coordinates=(px, py, pz)))
    return mk("IfcExtrudedAreaSolid", SweptArea=perfil, Position=pl,
              ExtrudedDirection=mk("IfcDirection", DirectionRatios=(0., 0., 1.)), Depth=dz)


def construir(con_cantidades=False, con_hueco=False):
    f = ifcopenshell.file(schema="IFC4")
    mk, ax, ctx = _base(f)
    cuerpo = _extruido(mk, L, T, H, 0., 0., 0.)
    rep = mk("IfcShapeRepresentation", ContextOfItems=ctx, RepresentationIdentifier="Body",
             RepresentationType="SweptSolid", Items=[cuerpo])
    muro = mk("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Muro 0,20",
              ObjectPlacement=mk("IfcLocalPlacement", RelativePlacement=ax),
              Representation=mk("IfcProductDefinitionShape", Representations=[rep]))
    if con_cantidades:
        qs = [mk("IfcQuantityLength", Name="Length", LengthValue=L),
              mk("IfcQuantityArea", Name="NetSideArea", AreaValue=L * H),
              mk("IfcQuantityVolume", Name="NetVolume", VolumeValue=L * T * H)]
        eq = mk("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(),
                Name="Qto_WallBaseQuantities", Quantities=qs)
        mk("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
           RelatedObjects=[muro], RelatingPropertyDefinition=eq)
    if con_hueco:
        hb = _extruido(mk, VW, T * 2, HW, 0., -T / 2, 0.90)
        hrep = mk("IfcShapeRepresentation", ContextOfItems=ctx, RepresentationIdentifier="Body",
                  RepresentationType="SweptSolid", Items=[hb])
        hueco = mk("IfcOpeningElement", GlobalId=ifcopenshell.guid.new(), Name="Vano ventana",
                   ObjectPlacement=mk("IfcLocalPlacement", RelativePlacement=ax),
                   Representation=mk("IfcProductDefinitionShape", Representations=[hrep]))
        mk("IfcRelVoidsElement", GlobalId=ifcopenshell.guid.new(),
           RelatingBuildingElement=muro, RelatedOpeningElement=hueco)
    return f, muro


def plan_a(muro):
    """Leer las BaseQuantities. Devuelve None si el IFC no las trae."""
    psets = uel.get_psets(muro, qtos_only=True)
    if not psets:
        return None
    nombre, q = next(iter(psets.items()))
    return nombre, {k: v for k, v in q.items() if k != "id"}


def plan_b(muro):
    """Calcular desde la geometria. Funciona siempre."""
    g = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), muro).geometry
    return dict(volumen=ush.get_volume(g),
                area_lateral=ush.get_side_area(g),
                area_total_6_caras=ush.get_area(g),
                huella=ush.get_footprint_area(g))


def main():
    casos = [("CON BaseQuantities",            dict(con_cantidades=True),  L * T * H),
             ("SIN BaseQuantities",            dict(),                     L * T * H),
             ("SIN BaseQuantities + ventana",  dict(con_hueco=True),       L * T * H - VW * T * HW)]
    print("=" * 78)
    print(f"  Muro {L} x {T} x {H} m, ventana {VW} x {HW} m")
    print("=" * 78)
    fallos = 0
    for etiqueta, kw, vol_esperado in casos:
        f, muro = construir(**kw)
        a, b = plan_a(muro), plan_b(muro)
        print(f"\n{etiqueta}")
        print(f"  PLAN A  {a[0] + ' -> ' + str(a[1]) if a else 'NADA: el IFC no trae IfcElementQuantity'}")
        err = abs(b["volumen"] - vol_esperado) / vol_esperado * 100
        ok = "OK" if err < 0.01 else "FALLO"
        if err >= 0.01:
            fallos += 1
        print(f"  PLAN B  volumen {b['volumen']:.4f} m3  (esperado {vol_esperado:.4f}, error {err:.4f}%)  {ok}")
        print(f"          area lateral {b['area_lateral']:.4f} m2   <- esta es la de revoque")
        print(f"          area 6 caras {b['area_total_6_caras']:.4f} m2   <- get_area, NO usar para revoque")
    print(f"\n{'TODO OK' if not fallos else str(fallos) + ' FALLOS'}: "
          "sin BaseQuantities el volumen se calcula igual, y exacto.")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
