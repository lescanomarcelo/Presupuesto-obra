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

DOS TRAMPAS que esta prueba documenta, las dos encontradas midiendo:

1. Elegir la funcion correcta de ifcopenshell.util.shape:
     get_area           superficie de las 6 caras    -> NO, sobrevalua 2,25x
     get_side_area      depende de la ORIENTACION    -> NO, da 0,74 en un muro girado
     get_max_side_area  la cara mas grande           -> SI. x2 para revocar dos caras
   get_max_side_area es independiente del giro y descuenta los huecos.

2. El objeto `file` tiene que seguir vivo mientras se usen sus entidades.
   Si se recolecta, el kernel C++ lee memoria liberada y el proceso muere con
   SIGSEGV, sin excepcion de Python que se pueda atrapar. Por eso construir()
   devuelve (file, muro) y no solo el muro.
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


def construir(con_cantidades=False, con_hueco=False, rotado=False):
    """Devuelve (file, muro). El file SE TIENE QUE RETENER: si se recolecta
    mientras el muro sigue en uso, el kernel de geometria produce un SIGSEGV."""
    f = ifcopenshell.file(schema="IFC4")
    mk, ax, ctx = _base(f)
    dx, dy = (T, L) if rotado else (L, T)
    cuerpo = _extruido(mk, dx, dy, H, 0., 0., 0.)
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
        hx, hy = (T * 2, VW) if rotado else (VW, T * 2)
        hpx, hpy = (-T / 2, 0.) if rotado else (0., -T / 2)
        hb = _extruido(mk, hx, hy, HW, hpx, hpy, 0.90)
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
                cara_mayor=ush.get_max_side_area(g),      # la correcta
                side_area=ush.get_side_area(g),           # depende del giro: no usar
                area_total_6_caras=ush.get_area(g),       # las 6 caras: no usar
                huella=ush.get_footprint_area(g))


def main():
    vol_pleno = L * T * H
    vol_hueco = vol_pleno - VW * T * HW
    cara_plena = L * H
    cara_hueco = cara_plena - VW * HW
    casos = [
        ("CON BaseQuantities",                 dict(con_cantidades=True),              vol_pleno, cara_plena),
        ("SIN BaseQuantities",                 dict(),                                 vol_pleno, cara_plena),
        ("SIN BaseQuantities + ventana",       dict(con_hueco=True),                   vol_hueco, cara_hueco),
        ("SIN BaseQuantities + ventana, GIRADO 90", dict(con_hueco=True, rotado=True), vol_hueco, cara_hueco),
    ]
    print("=" * 80)
    print(f"  Muro {L} x {T} x {H} m, ventana {VW} x {HW} m")
    print("=" * 80)
    fallos = 0
    for etiqueta, kw, vol_esp, cara_esp in casos:
        f, muro = construir(**kw)            # retener f: ver el docstring
        a, b = plan_a(muro), plan_b(muro)
        print(f"\n{etiqueta}")
        print(f"  PLAN A  {a[0] + ' -> ' + str(a[1]) if a else 'NADA: el IFC no trae IfcElementQuantity'}")

        e_vol = abs(b["volumen"] - vol_esp) / vol_esp * 100
        e_cara = abs(b["cara_mayor"] - cara_esp) / cara_esp * 100
        fallos += (e_vol >= 0.01) + (e_cara >= 0.01)
        print(f"  PLAN B  volumen          {b['volumen']:8.4f} m3  esperado {vol_esp:8.4f}  error {e_vol:.4f}%  "
              f"{'OK' if e_vol < 0.01 else 'FALLO'}")
        print(f"          get_max_side_area {b['cara_mayor']:8.4f} m2  esperado {cara_esp:8.4f}  error {e_cara:.4f}%  "
              f"{'OK' if e_cara < 0.01 else 'FALLO'}")
        print(f"          revoque 2 caras   {2 * b['cara_mayor']:8.4f} m2")
        marca = "  <-- MAL, depende del giro" if abs(b["side_area"] - b["cara_mayor"]) > 0.01 else ""
        print(f"          get_side_area     {b['side_area']:8.4f} m2{marca}")
        print(f"          get_area (6 caras){b['area_total_6_caras']:8.4f} m2  <-- MAL para revoque")
    print(f"\n{'TODO OK' if not fallos else str(fallos) + ' FALLOS'}")
    print("  - Sin BaseQuantities el volumen se calcula igual, y exacto.")
    print("  - get_max_side_area es la correcta: no depende del giro y descuenta huecos.")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
