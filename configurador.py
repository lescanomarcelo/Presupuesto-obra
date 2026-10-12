#!/usr/bin/env python3
"""Configurador de computo — Presupuesto de Obra

Abri un plano DXF, mira lo que el programa detecto, corregilo, y exporta el
computo.

    pip install PySide6 ezdxf shapely
    python configurador.py

El detector es un BORRADOR, no una autoridad: su trabajo no es acertar, es que
corregir salga mas barato que dibujar todo de cero. Lo que vale es cuantas
correcciones te cuesta, no cuanto detecta.

Un solo archivo a proposito: no hay que instalar el proyecto ni usar git.
"""
from __future__ import annotations

import collections
import csv
import json
import math
import os
import statistics
import sys

import ezdxf
from ezdxf import recover

from PySide6 import QtCore, QtGui, QtWidgets

# ───────────────────────────── catalogo minimo ─────────────────────────────
# Subconjunto de seed/items.csv. Unidad y descripcion para asignar a los grupos.
ITEMS = [
    ("", "— sin asignar —", ""),
    ("IGNORAR", "✕ ignorar (no va al computo)", ""),
    ("04.01", "Mampostería ladrillo hueco 12x18x33", "m2"),
    ("04.02", "Mampostería ladrillo hueco 18x18x33", "m2"),
    ("04.03", "Mampostería ladrillo común 0,15", "m2"),
    ("07.01", "Revoque grueso a la cal, interior", "m2"),
    ("07.02", "Revoque fino a la cal, interior", "m2"),
    ("07.03", "Revoque grueso impermeable, exterior", "m2"),
    ("06.01", "Contrapiso de hormigón de cascote", "m2"),
    ("06.02", "Carpeta de concreto bajo piso", "m2"),
    ("08.01", "Piso cerámico esmaltado", "m2"),
    ("08.02", "Zócalo cerámico", "m"),
    ("13.01", "Pintura látex interior", "m2"),
    ("13.02", "Pintura látex exterior", "m2"),
]
ALTURA_DEFECTO = 2.60   # para pasar de metros lineales de muro a m2

# ───────────────────────────── lectura del DXF ─────────────────────────────
UNIDADES = {0: "sin definir", 1: "pulgadas", 2: "pies", 4: "milímetros",
            5: "centímetros", 6: "metros"}


def abrir_dxf(ruta):
    try:
        return ezdxf.readfile(ruta)
    except Exception:
        doc, _ = recover.readfile(ruta)       # archivos dañados
        return doc


def resolver_unidades(doc):
    """El header miente: declara milimetros en dibujos que estan en metros.
    Las cotas son la fuente de verdad (una puerta de 0,80 lo confirma)."""
    insunits = doc.header.get("$INSUNITS", 0)
    medidas = []
    for d in doc.modelspace().query("DIMENSION"):
        try:
            m = float(d.get_measurement())
            if m > 0:
                medidas.append(m)
        except Exception:
            pass
    if medidas:
        mediana = statistics.median(medidas)
        if 0.3 <= mediana <= 50:
            return "metros (deducido de las cotas)", 1.0, insunits
        if 300 <= mediana <= 50000:
            return "milímetros (deducido de las cotas)", 0.001, insunits
    return UNIDADES.get(insunits, "?") + " (del header)", \
           (0.001 if insunits == 4 else 1.0), insunits


def deduplicar(lineas, tol=0.001):
    vistas, out, rep = set(), [], 0
    q = lambda v: round(v / tol)
    for a, b in lineas:
        k1 = (q(a[0]), q(a[1]), q(b[0]), q(b[1]))
        k2 = (q(b[0]), q(b[1]), q(a[0]), q(a[1]))
        if k1 in vistas or k2 in vistas:
            rep += 1
            continue
        vistas.add(k1)
        out.append((a, b))
    return out, rep


def leer_geometria(doc, lejania=40.0):
    """Lineas del cumulo principal. Lo que cae lejos es basura: en un plano real
    habia 12 bloques 'puerta' fuera del dibujo que se habrian presupuestado."""
    msp = doc.modelspace()
    crudas = []
    for e in msp.query("LINE"):
        a = (e.dxf.start.x, e.dxf.start.y)
        b = (e.dxf.end.x, e.dxf.end.y)
        if math.dist(a, b) > 1e-9:
            crudas.append((a, b))
    if not crudas:
        return [], [], [], 0, 0
    xs = [p[0] for a, b in crudas for p in (a, b)]
    ys = [p[1] for a, b in crudas for p in (a, b)]
    cx, cy = statistics.median(xs), statistics.median(ys)
    cerca, lejos = [], 0
    for a, b in crudas:
        if max(abs(a[0] - cx), abs(a[1] - cy), abs(b[0] - cx), abs(b[1] - cy)) <= lejania:
            cerca.append((a, b))
        else:
            lejos += 1
    cerca, rep = deduplicar(cerca)

    hatches = []
    for h in msp.query("HATCH"):
        for p in h.paths:
            v = getattr(p, "vertices", None)
            if v and len(v) > 2:
                pts = [(x[0], x[1]) for x in v]
                area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                               - pts[(i + 1) % len(pts)][0] * pts[i][1]
                               for i in range(len(pts)))) / 2
                if area > 0.05:
                    hatches.append(dict(pts=pts, area=area,
                                        patron=str(h.dxf.get("pattern_name", "?"))))
    inserts = []
    for e in msp.query("INSERT"):
        p = e.dxf.insert
        inserts.append(dict(nombre=str(e.dxf.name), pos=(p.x, p.y),
                            lejos=max(abs(p.x - cx), abs(p.y - cy)) > lejania))
    return cerca, hatches, inserts, lejos, rep


def detectar_muros(lineas, esp_min=0.05, esp_max=0.60, solape_min=0.30, tol_ang=1.5):
    """Empareja las dos caras de cada muro. Cuatro cosas aprendidas midiendo:
    asignacion global (no mutua), se reserva el TRAMO y no la linea, se
    autocalibra por frecuencia de espesor, y se deduplica antes."""
    datos = []
    for a, b in lineas:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        datos.append(dict(a=a, b=b, L=L, ang=math.atan2(dy, dx) % math.pi,
                          u=(dx / L, dy / L)))
    grupos = collections.defaultdict(list)
    paso = math.radians(tol_ang)
    for i, d in enumerate(datos):
        grupos[round(d["ang"] / paso)].append(i)
    cand = collections.defaultdict(set)
    for k in list(grupos):
        pool = grupos[k] + grupos.get(k + 1, []) + grupos.get(k - 1, [])
        for i in pool:
            cand[i].update(pool)

    def evaluar(i, j):
        di, dj = datos[i], datos[j]
        if abs((di["ang"] - dj["ang"] + math.pi / 2) % math.pi - math.pi / 2) > paso:
            return None
        ux, uy = di["u"]
        nx, ny = -uy, ux
        esp = abs((dj["a"][0] - di["a"][0]) * nx + (dj["a"][1] - di["a"][1]) * ny)
        if not (esp_min <= esp <= esp_max):
            return None
        pi0, pi1 = di["a"][0]*ux + di["a"][1]*uy, di["b"][0]*ux + di["b"][1]*uy
        pj0, pj1 = dj["a"][0]*ux + dj["a"][1]*uy, dj["b"][0]*ux + dj["b"][1]*uy
        sol = min(max(pi0, pi1), max(pj0, pj1)) - max(min(pi0, pi1), min(pj0, pj1))
        if sol < solape_min or sol < 0.5 * min(di["L"], dj["L"]):
            return None
        return esp, sol

    pares = []
    for i in range(len(datos)):
        for j in cand[i]:
            if j <= i:
                continue
            r = evaluar(i, j)
            if r:
                pares.append((r[1], -r[0], i, j))
    peso = collections.Counter()
    for sol, nesp, i, j in pares:
        peso[round(-nesp, 2)] += sol
    pares = [(peso[round(-nesp, 2)], sol, nesp, i, j) for sol, nesp, i, j in pares]
    pares.sort(reverse=True)

    proy = lambda d, x, y: x * d["u"][0] + y * d["u"][1]
    consumido = collections.defaultdict(list)

    def libre(idx, p0, p1, margen=0.25):
        lo, hi = min(p0, p1), max(p0, p1)
        if hi - lo <= 0:
            return False
        return all(min(hi, c1) - max(lo, c0) <= margen * (hi - lo)
                   for c0, c1 in consumido[idx])

    muros = []
    for _, _, _, i, j in pares:
        r = evaluar(i, j)
        if not r:
            continue
        esp, _ = r
        di, dj = datos[i], datos[j]
        ux, uy = di["u"]
        lo = max(min(proy(di, *di["a"]), proy(di, *di["b"])),
                 min(proy(di, *dj["a"]), proy(di, *dj["b"])))
        hi = min(max(proy(di, *di["a"]), proy(di, *di["b"])),
                 max(proy(di, *dj["a"]), proy(di, *dj["b"])))
        mx, my = (di["a"][0] + dj["a"][0]) / 2, (di["a"][1] + dj["a"][1]) / 2
        base = mx * ux + my * uy
        ex, ey = mx + (lo - base) * ux, my + (lo - base) * uy
        fx, fy = mx + (hi - base) * ux, my + (hi - base) * uy
        ai, bi = proy(di, ex, ey), proy(di, fx, fy)
        aj, bj = proy(dj, ex, ey), proy(dj, fx, fy)
        if not (libre(i, ai, bi) and libre(j, aj, bj)):
            continue
        consumido[i].append((min(ai, bi), max(ai, bi)))
        consumido[j].append((min(aj, bj), max(aj, bj)))
        muros.append(dict(a=(ex, ey), b=(fx, fy), largo=hi - lo,
                          espesor=esp, manual=False))
    return muros


# ─────────────────────────── el modelo editable ────────────────────────────
# Un "elemento" es una cosa presupuestable (un muro, un hatch, un bloque).
# Un "grupo" junta elementos parecidos, y es la unidad de correccion: aceptar o
# descartar un grupo entero resuelve decenas de elementos de una.

UMBRAL_SOSPECHOSO = 3   # un espesor que aparece menos de 3 veces es dudoso


def co(x, dec=2):
    """Numero con coma decimal: es lo que el usuario lee en su plano."""
    return ("%.*f" % (dec, x)).replace(".", ",")


class Modelo:
    def __init__(self, ruta):
        self.ruta = ruta
        doc = abrir_dxf(ruta)
        self.unidades, factor, self.insunits = resolver_unidades(doc)
        cerca, hatches, inserts, self.lejos, self.repetidas = leer_geometria(doc)
        if factor != 1.0:
            esc = lambda p: (p[0] * factor, p[1] * factor)
            cerca = [(esc(a), esc(b)) for a, b in cerca]
            for h in hatches:
                h["pts"] = [esc(p) for p in h["pts"]]
                h["area"] *= factor ** 2
            for b in inserts:
                b["pos"] = esc(b["pos"])
        self.lineas = cerca
        self.elementos = []
        self.grupos = {}          # clave -> dict(titulo, unidad, item, orden)
        self._cargar(detectar_muros(cerca), hatches, inserts)
        self.cargar_json()

    # ---- construccion ----
    def _cargar(self, muros, hatches, inserts):
        freq = collections.Counter(round(m["espesor"], 2) for m in muros)
        for m in muros:
            esp = round(m["espesor"], 2)
            self.agregar(dict(tipo="muro", a=m["a"], b=m["b"], cant=m["largo"],
                              espesor=esp, manual=False,
                              sospechoso=freq[esp] < UMBRAL_SOSPECHOSO))
        for h in hatches:
            self.agregar(dict(tipo="hatch", pts=h["pts"], cant=h["area"],
                              patron=h["patron"]))
        for b in sorted(inserts, key=lambda b: (b["lejos"], b["nombre"])):
            self.agregar(dict(tipo="bloque", nombre=b["nombre"], cant=1,
                              pos=b["pos"], lejos=b["lejos"]))

    def agregar(self, el):
        el.setdefault("descartado", False)
        el.setdefault("manual", False)
        el["id"] = len(self.elementos)
        clave, titulo, unidad = self.clasificar(el)
        el["grupo"] = clave
        if clave not in self.grupos:
            self.grupos[clave] = dict(titulo=titulo, unidad=unidad, item="",
                                      orden=len(self.grupos))
        self.elementos.append(el)
        if el["tipo"] == "bloque" and el["lejos"]:
            el["descartado"] = True     # basura fuera del plano, por defecto no va
        return el

    @staticmethod
    def clasificar(el):
        if el["tipo"] == "muro":
            if el.get("manual"):
                return ("muro_manual_%.2f" % el["espesor"],
                        "Muros " + co(el["espesor"]) + " m (agregados a mano)", "m")
            if el.get("sospechoso"):
                return "sospechosos", "Espesores sospechosos (revisar)", "m"
            return ("muro_%.2f" % el["espesor"],
                    "Muros " + co(el["espesor"]) + " m", "m")
        if el["tipo"] == "hatch":
            return "hatch_" + el["patron"], "Hatches «%s»" % el["patron"], "m2"
        suf = " (fuera del plano)" if el["lejos"] else ""
        return ("bloque_%s_%d" % (el["nombre"], el["lejos"]),
                'Bloques «%s»%s' % (el["nombre"], suf), "u")

    # ---- consultas ----
    def grupos_ordenados(self):
        return sorted(self.grupos.items(), key=lambda kv: kv[1]["orden"])

    def del_grupo(self, clave):
        return [e for e in self.elementos if e["grupo"] == clave]

    def cantidad(self, clave):
        g = self.grupos[clave]
        n = sum(e["cant"] for e in self.del_grupo(clave) if not e["descartado"])
        if g["unidad"] == "u":
            return n
        unidad_item = dict((c, u) for c, _, u in ITEMS).get(g["item"], "")
        if g["unidad"] == "m" and unidad_item == "m2":
            return n * ALTURA_DEFECTO     # metros lineales de muro -> m2 de cara
        return n

    def unidad_salida(self, clave):
        u = dict((c, u) for c, _, u in ITEMS).get(self.grupos[clave]["item"], "")
        return u or self.grupos[clave]["unidad"]

    # ---- edicion ----
    def nuevo_muro(self, a, b, espesor):
        largo = math.dist(a, b)
        return self.agregar(dict(tipo="muro", a=a, b=b, cant=largo,
                                 espesor=round(espesor, 2), manual=True,
                                 sospechoso=False))

    # ---- persistencia: guarda las CORRECCIONES, no el resultado ----
    @property
    def ruta_json(self):
        return os.path.splitext(self.ruta)[0] + ".computo.json"

    @staticmethod
    def _firma(el):
        if el["tipo"] == "muro":
            p = sorted([tuple(round(v, 3) for v in el["a"]),
                        tuple(round(v, 3) for v in el["b"])])
            return "muro|%s|%s|%.2f" % (p[0], p[1], el["espesor"])
        if el["tipo"] == "hatch":
            return "hatch|%s|%.3f" % (el["patron"], el["cant"])
        return "bloque|%s|%.3f|%.3f" % (el["nombre"], el["pos"][0], el["pos"][1])

    def guardar_json(self):
        datos = dict(
            version=1, dxf=os.path.basename(self.ruta), altura=ALTURA_DEFECTO,
            items={k: g["item"] for k, g in self.grupos.items() if g["item"]},
            descartados=[self._firma(e) for e in self.elementos
                         if e["descartado"] and not e["manual"]],
            manuales=[dict(a=list(e["a"]), b=list(e["b"]), espesor=e["espesor"],
                           descartado=e["descartado"])
                      for e in self.elementos if e["manual"]],
        )
        with open(self.ruta_json, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        return self.ruta_json

    def cargar_json(self):
        if not os.path.exists(self.ruta_json):
            return False
        try:
            with open(self.ruta_json, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return False
        for m in d.get("manuales", []):
            el = self.nuevo_muro(tuple(m["a"]), tuple(m["b"]), m["espesor"])
            el["descartado"] = bool(m.get("descartado"))
        fuera = set(d.get("descartados", []))
        for e in self.elementos:
            if not e["manual"] and self._firma(e) in fuera:
                e["descartado"] = True
        for k, v in d.get("items", {}).items():
            if k in self.grupos:
                self.grupos[k]["item"] = v
        return True

    def exportar_csv(self, ruta):
        """Preset Excel es-AR: separador ';' y UTF-8 CON BOM."""
        filas = []
        for clave, g in self.grupos_ordenados():
            if not g["item"] or g["item"] == "IGNORAR":
                continue
            vivos = [e for e in self.del_grupo(clave) if not e["descartado"]]
            if not vivos:
                continue
            desc = dict((c, d) for c, d, _ in ITEMS)[g["item"]]
            filas.append([g["item"], desc, self.unidad_salida(clave),
                          co(self.cantidad(clave)),
                          len(vivos), g["titulo"]])
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["item", "descripcion", "unidad", "cantidad",
                        "elementos", "origen"])
            w.writerows(filas)
        return ruta, filas


# ──────────────────────────────── la vista ─────────────────────────────────
GRIS = QtGui.QColor(185, 185, 185)
PALETA = [QtGui.QColor(c) for c in
          ("#1f77b4", "#2ca02c", "#9467bd", "#17becf", "#8c564b", "#e377c2")]
ROJO = QtGui.QColor("#d62728")
NARANJA = QtGui.QColor("#ff7f0e")
APAGADO = QtGui.QColor(225, 225, 225)


def color_de(clave, grupos):
    if clave == "sospechosos":
        return ROJO
    if clave.startswith("muro_manual"):
        return NARANJA
    orden = [k for k, _ in sorted(grupos.items(), key=lambda kv: kv[1]["orden"])]
    return PALETA[orden.index(clave) % len(PALETA)]


class Lienzo(QtWidgets.QGraphicsView):
    """Rueda = zoom, arrastre = pan, clic = seleccionar, Supr = descartar."""
    clic_mapa = QtCore.Signal(float, float)
    seleccion = QtCore.Signal(object)
    borrar = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.escena = QtWidgets.QGraphicsScene(self)   # retener o se recolecta
        self.setScene(self.escena)
        self.setRenderHints(QtGui.QPainter.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QtGui.QColor("white"))
        self.scale(1, -1)                 # el DXF crece hacia arriba
        self.modo_agregar = False
        self.pendiente = None
        self.items = {}

    # --- dibujo ---
    def pintar(self, modelo):
        self.escena.clear()
        self.items.clear()
        fino = QtGui.QPen(GRIS)
        fino.setCosmetic(True)
        for a, b in modelo.lineas:
            self.escena.addLine(a[0], a[1], b[0], b[1], fino)
        for el in modelo.elementos:
            col = APAGADO if el["descartado"] else color_de(el["grupo"], modelo.grupos)
            it = None
            if el["tipo"] == "muro":
                pen = QtGui.QPen(col)
                pen.setCosmetic(True)
                pen.setWidth(4 if not el["descartado"] else 2)
                if el["grupo"] == "sospechosos":
                    pen.setStyle(QtCore.Qt.DashLine)
                it = self.escena.addLine(el["a"][0], el["a"][1],
                                         el["b"][0], el["b"][1], pen)
            elif el["tipo"] == "bloque" and not el["lejos"]:
                pen = QtGui.QPen(col)
                pen.setCosmetic(True)
                br = QtGui.QColor(col)
                br.setAlpha(90)
                x, y = el["pos"]
                it = self.escena.addEllipse(x - 0.12, y - 0.12, 0.24, 0.24,
                                            pen, QtGui.QBrush(br))
            elif el["tipo"] == "hatch":
                poly = QtGui.QPolygonF([QtCore.QPointF(*p) for p in el["pts"]])
                br = QtGui.QColor(col)
                br.setAlpha(60)
                pen = QtGui.QPen(col)
                pen.setCosmetic(True)
                it = self.escena.addPolygon(poly, pen, QtGui.QBrush(br))
            if it is not None:
                it.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)
                it.setData(0, el["id"])
                self.items[el["id"]] = it
        if self.escena.itemsBoundingRect().isValid():
            self.escena.setSceneRect(
                self.escena.itemsBoundingRect().adjusted(-2, -2, 2, 2))

    def encuadrar(self):
        r = self.escena.itemsBoundingRect()
        if r.isValid():
            self.fitInView(r.adjusted(-1, -1, 1, 1), QtCore.Qt.KeepAspectRatio)

    # --- interaccion ---
    def wheelEvent(self, ev):
        f = 1.25 if ev.angleDelta().y() > 0 else 0.8
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.scale(f, f)

    def mousePressEvent(self, ev):
        if self.modo_agregar and ev.button() == QtCore.Qt.LeftButton:
            p = self.mapToScene(ev.position().toPoint())
            self.clic_mapa.emit(p.x(), p.y())
            return
        super().mousePressEvent(ev)
        it = self.itemAt(ev.position().toPoint())
        self.seleccion.emit(it.data(0) if it is not None and
                            it.data(0) is not None else None)

    def keyPressEvent(self, ev):
        if ev.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.borrar.emit()
            return
        super().keyPressEvent(ev)


# ──────────────────────────────── la ventana ────────────────────────────────
class Ventana(QtWidgets.QMainWindow):
    def __init__(self, ruta=None):
        super().__init__()
        self.setWindowTitle("Configurador de cómputo")
        self.resize(1280, 800)
        self.modelo = None
        self.sel = None
        self._puntos = []
        self._pendiente_refresco = False
        self._repintar = False

        self.lienzo = Lienzo()
        self.lienzo.clic_mapa.connect(self.clic_mapa)
        self.lienzo.seleccion.connect(self.set_seleccion)
        self.lienzo.borrar.connect(self.descartar_seleccion)

        self.arbol = QtWidgets.QTreeWidget()
        self.arbol.setHeaderLabels(["Grupo", "Cant.", "Medida", "Ítem del catálogo"])
        self.arbol.setColumnWidth(0, 215)
        self.arbol.setColumnWidth(1, 48)
        self.arbol.setColumnWidth(2, 82)
        self.arbol.header().setStretchLastSection(True)
        self.arbol.itemChanged.connect(self.cambio_check)
        self.arbol.itemSelectionChanged.connect(self.cambio_sel_arbol)

        der = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(der)
        lay.setContentsMargins(6, 6, 6, 6)
        self.info = QtWidgets.QLabel("Abrí un DXF para empezar.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addWidget(self.arbol, 1)

        fila = QtWidgets.QHBoxLayout()
        self.btn_agregar = QtWidgets.QPushButton("Agregar muro (2 clics)")
        self.btn_agregar.setCheckable(True)
        self.btn_agregar.toggled.connect(self.toggle_agregar)
        self.esp = QtWidgets.QDoubleSpinBox()
        self.esp.setRange(0.05, 1.0)
        self.esp.setSingleStep(0.05)
        self.esp.setValue(0.20)
        self.esp.setSuffix(" m")
        self.esp.setLocale(QtCore.QLocale("es_AR"))
        fila.addWidget(self.btn_agregar, 1)
        fila.addWidget(QtWidgets.QLabel("espesor"))
        fila.addWidget(self.esp)
        lay.addLayout(fila)

        self.pie = QtWidgets.QLabel("")
        self.pie.setWordWrap(True)
        lay.addWidget(self.pie)
        der.setMinimumWidth(560)

        split = QtWidgets.QSplitter()
        split.addWidget(self.lienzo)
        split.addWidget(der)
        split.setStretchFactor(0, 1)
        split.setSizes([700, 580])
        self.setCentralWidget(split)

        b = self.addToolBar("acciones")
        b.addAction("Abrir DXF…", self.abrir)
        b.addAction("Encuadrar", self.lienzo.encuadrar)
        b.addSeparator()
        b.addAction("Guardar correcciones", self.guardar)
        b.addAction("Exportar cómputo CSV…", self.exportar)
        self.statusBar().showMessage("Listo")

        if ruta:
            self.cargar(ruta)

    # ---- archivos ----
    def abrir(self):
        r, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Abrir plano DXF", "", "Planos DXF (*.dxf);;Todos (*)")
        if r:
            self.cargar(r)

    def cargar(self, ruta):
        try:
            self.modelo = Modelo(ruta)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "No se pudo abrir", str(e))
            return
        m = self.modelo
        self.setWindowTitle("Configurador de cómputo — " + os.path.basename(ruta))
        reusado = os.path.exists(m.ruta_json)
        self.info.setText(
            "<b>%s</b><br>Unidades: %s · %d líneas · %d duplicadas descartadas · "
            "%d líneas y bloques lejos del plano%s" % (
                os.path.basename(ruta), m.unidades, len(m.lineas), m.repetidas,
                m.lejos, "<br><b>Se reabrieron tus correcciones guardadas.</b>"
                if reusado else ""))
        self.lienzo.pintar(m)
        self.lienzo.encuadrar()
        self.refrescar()

    def guardar(self):
        if self.modelo:
            self.statusBar().showMessage("Guardado en " + self.modelo.guardar_json())

    def exportar(self):
        if not self.modelo:
            return
        sug = os.path.join(os.path.dirname(self.modelo.ruta), "computo.csv")
        r, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Exportar cómputo", sug, "CSV (*.csv)")
        if not r:
            return
        _, filas = self.modelo.exportar_csv(r)
        self.modelo.guardar_json()
        if not filas:
            QtWidgets.QMessageBox.warning(
                self, "Cómputo vacío",
                "Ningún grupo tiene un ítem del catálogo asignado todavía.\n"
                "Elegí el ítem en la última columna del panel.")
        else:
            self.statusBar().showMessage("%d filas en %s" % (len(filas), r))

    # ---- panel ----
    def refrescar(self):
        m = self.modelo
        self.arbol.blockSignals(True)
        self.arbol.clear()
        for clave, g in m.grupos_ordenados():
            els = m.del_grupo(clave)
            vivos = [e for e in els if not e["descartado"]]
            nodo = QtWidgets.QTreeWidgetItem([
                g["titulo"], "%d/%d" % (len(vivos), len(els)),
                co(m.cantidad(clave)) + " " + m.unidad_salida(clave), ""])
            nodo.setData(0, QtCore.Qt.UserRole, ("grupo", clave))
            nodo.setFlags(nodo.flags() | QtCore.Qt.ItemIsUserCheckable)
            nodo.setCheckState(0, QtCore.Qt.Checked if vivos else QtCore.Qt.Unchecked)
            col = color_de(clave, m.grupos)
            nodo.setForeground(0, QtGui.QBrush(col))
            self.arbol.addTopLevelItem(nodo)

            combo = QtWidgets.QComboBox()
            for cod, desc, uni in ITEMS:
                combo.addItem(desc + (" [%s]" % uni if uni else ""), cod)
            combo.setCurrentIndex(max(0, [c for c, _, _ in ITEMS].index(g["item"])
                                      if g["item"] in [c for c, _, _ in ITEMS] else 0))
            combo.setMinimumWidth(215)
            combo.currentIndexChanged.connect(
                lambda _i, c=clave, cb=combo: self.set_item(c, cb.currentData()))
            self.arbol.setItemWidget(nodo, 3, combo)

            for e in els:
                if e["tipo"] == "muro":
                    txt = "%s m · %s m de espesor%s" % (
                        co(e["cant"]), co(e["espesor"]),
                        " · a mano" if e["manual"] else "")
                elif e["tipo"] == "hatch":
                    txt = co(e["cant"]) + " m²"
                else:
                    txt = "en %s , %s" % (co(e["pos"][0], 1), co(e["pos"][1], 1))
                hijo = QtWidgets.QTreeWidgetItem([txt, "", "", ""])
                hijo.setData(0, QtCore.Qt.UserRole, ("elem", e["id"]))
                hijo.setFlags(hijo.flags() | QtCore.Qt.ItemIsUserCheckable)
                hijo.setCheckState(0, QtCore.Qt.Unchecked if e["descartado"]
                                   else QtCore.Qt.Checked)
                nodo.addChild(hijo)
        self.arbol.blockSignals(False)
        self.resumen()

    def resumen(self):
        m = self.modelo
        muros = [e for e in m.elementos
                 if e["tipo"] == "muro" and not e["descartado"]]
        area = sum(m.cantidad(k) for k, g in m.grupos.items()
                   if m.unidad_salida(k) == "m2")
        sin = [g["titulo"] for k, g in m.grupos_ordenados() if not g["item"]
               and any(not e["descartado"] for e in m.del_grupo(k))]
        self.pie.setText(
            "<b>%d muros · %s m</b> lineales · %s m² asignados.<br>%s" % (
                len(muros), co(sum(e["cant"] for e in muros)), co(area),
                ("Falta elegir el ítem en %d grupos: %s%s" % (
                    len(sin), ", ".join(sin[:3]), " …" if len(sin) > 3 else ""))
                if sin else "Todos los grupos activos tienen ítem."))

    def programar_refresco(self, repintar=False):
        """Nunca reconstruir el arbol DENTRO de una senal suya: Qt borra el
        widget que esta emitiendo y el proceso muere con segfault."""
        if repintar:
            self._repintar = True
        if not self._pendiente_refresco:
            self._pendiente_refresco = True
            QtCore.QTimer.singleShot(0, self._refresco_diferido)

    def _refresco_diferido(self):
        self._pendiente_refresco = False
        if self._repintar:
            self._repintar = False
            self.lienzo.pintar(self.modelo)
        self.refrescar()

    def set_item(self, clave, cod):
        self.modelo.grupos[clave]["item"] = cod or ""
        self.programar_refresco()

    def cambio_check(self, item, col):
        if col != 0:
            return
        que, val = item.data(0, QtCore.Qt.UserRole)
        apagar = item.checkState(0) == QtCore.Qt.Unchecked
        if que == "grupo":
            for e in self.modelo.del_grupo(val):
                e["descartado"] = apagar
        else:
            self.modelo.elementos[val]["descartado"] = apagar
        self.programar_refresco(repintar=True)

    def cambio_sel_arbol(self):
        it = self.arbol.currentItem()
        if not it:
            return
        que, val = it.data(0, QtCore.Qt.UserRole)
        if que == "elem" and val in self.lienzo.items:
            self.lienzo.escena.clearSelection()
            self.lienzo.items[val].setSelected(True)
            self.sel = val

    # ---- acciones sobre el dibujo ----
    def set_seleccion(self, eid):
        self.sel = eid
        if eid is None:
            self.statusBar().showMessage("")
            return
        e = self.modelo.elementos[eid]
        self.statusBar().showMessage(
            "%s · %s · Supr para descartarlo" % (e["tipo"], co(e["cant"])))

    def descartar_seleccion(self):
        if self.sel is None or not self.modelo:
            return
        e = self.modelo.elementos[self.sel]
        e["descartado"] = not e["descartado"]
        self.programar_refresco(repintar=True)
        self.statusBar().showMessage(
            "Descartado" if e["descartado"] else "Recuperado")

    def toggle_agregar(self, on):
        self.lienzo.modo_agregar = on
        self.lienzo.setDragMode(QtWidgets.QGraphicsView.NoDrag if on
                                else QtWidgets.QGraphicsView.ScrollHandDrag)
        self._puntos = []
        self.statusBar().showMessage(
            "Hacé clic en los dos extremos del muro" if on else "")

    def clic_mapa(self, x, y):
        self._puntos.append((x, y))
        if len(self._puntos) < 2:
            self.statusBar().showMessage("Ahora el otro extremo")
            return
        a, b = self._puntos
        self._puntos = []
        if math.dist(a, b) < 0.05:
            self.statusBar().showMessage("Muy corto, ignorado")
            return
        self.modelo.nuevo_muro(a, b, self.esp.value())
        self.programar_refresco(repintar=True)
        self.statusBar().showMessage("Muro de " + co(math.dist(a, b)) + " m agregado")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    png = csv_out = None
    if "--png" in argv:
        png = argv.pop(argv.index("--png") + 1); argv.remove("--png")
    if "--csv" in argv:
        csv_out = argv.pop(argv.index("--csv") + 1); argv.remove("--csv")
    salir = "--salir" in argv
    if salir:
        argv.remove("--salir")
    ruta = argv[0] if argv else None

    app = QtWidgets.QApplication([])
    v = Ventana(ruta)
    v.show()
    if png and v.modelo:
        app.processEvents()
        v.lienzo.encuadrar()
        v.lienzo.grab().save(png)
        print("PNG:", png)
    if csv_out and v.modelo:
        r, filas = v.modelo.exportar_csv(csv_out)
        print("CSV:", r, len(filas), "filas")
    if salir:
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
