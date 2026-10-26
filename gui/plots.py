"""Componentes gráficos (pyqtgraph): partículas e gráficos de grandezas."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .geometry import Domain
from .observables import Observable

pg.setConfigOptions(antialias=True, background="w", foreground="#343a40")

SIDE_COLORS = ("#1c7ed6", "#f76707")   # esquerda / direita no instante inicial
SOLID_COLOR = (82, 103, 125)


def _lut_brushes(cmap_name: str = "plasma", n: int = 128):
    cmap = pg.colormap.get(cmap_name)
    colors = cmap.getLookupTable(0.0, 0.92, n, alpha=False)
    return cmap, [pg.mkBrush(int(r), int(g), int(b)) for r, g, b in colors]


class ParticleView(pg.GraphicsLayoutWidget):
    """Caixa com sólidos e partículas coloridas por velocidade ou lado inicial."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plot = self.addPlot(row=0, col=0)
        self.plot.setAspectLocked(True)
        self.plot.setLabel("bottom", "x")
        self.plot.setLabel("left", "y")
        self.plot.showGrid(False, False)
        self.plot.setMenuEnabled(False)
        self.solids = pg.ImageItem()
        self.plot.addItem(self.solids)
        self.border = pg.PlotCurveItem(pen=pg.mkPen(SOLID_COLOR, width=2))
        self.plot.addItem(self.border)
        self.scatter = pg.ScatterPlotItem(size=6, pen=pg.mkPen(255, 255, 255, 120, width=0.5), pxMode=True)
        self.plot.addItem(self.scatter)
        self.cmap, self.brushes = _lut_brushes()
        self.side_brushes = [pg.mkBrush(c) for c in SIDE_COLORS]
        self.colorbar = pg.ColorBarItem(values=(0, 1), colorMap=self.cmap, interactive=False,
                                        label="|v|", width=14)
        self.addItem(self.colorbar, row=0, col=1)
        self.legend_label = pg.LabelItem("", justify="left")
        self.addItem(self.legend_label, row=1, col=0, colspan=2)
        self.mode = "speed"
        self.vmax = 1.0
        self.side: np.ndarray | None = None
        self.species: np.ndarray | None = None
        self.domain: Domain | None = None
        # pistão: barra grossa e região inacessível sombreada
        self.piston_line = pg.PlotCurveItem(pen=pg.mkPen((52, 58, 64), width=6))
        self.piston_shade = QtWidgets.QGraphicsRectItem()
        self.piston_shade.setBrush(pg.mkBrush(134, 142, 150, 110))
        self.piston_shade.setPen(pg.mkPen(None))
        for item in (self.piston_shade, self.piston_line):
            item.setZValue(5)
            item.setVisible(False)
            self.plot.addItem(item)
        self.wall_items: list = []

    def set_domain(self, domain: Domain, temperature: float, kB: float, mass: float, meta: dict | None = None):
        self.domain = domain
        meta = meta or {}
        sp = meta.get("species")
        self.species = np.asarray(sp, dtype=int) if sp is not None else None
        self._draw_walls(domain, meta.get("wall_temperatures") or [None] * 4, temperature)
        self.piston_line.setVisible(meta.get("piston") is not None)
        self.piston_shade.setVisible(meta.get("piston") is not None)
        rgba = np.zeros((domain.nx, domain.ny, 4), dtype=np.ubyte)
        solid = ~domain.fluid.T
        rgba[solid] = (*SOLID_COLOR, 255)
        self.solids.setImage(rgba, levels=None)
        x0, y0 = domain.lower
        w, h = domain.size
        self.solids.setRect(QtCore.QRectF(x0, y0, w, h))
        self.border.setData([x0, x0 + w, x0 + w, x0, x0], [y0, y0, y0 + h, y0 + h, y0])
        pad = 0.02 * max(w, h)
        self.plot.setRange(xRange=(x0 - pad, x0 + w + pad), yRange=(y0 - pad, y0 + h + pad), padding=0)
        self.vmax = max(1e-12, 3.0 * np.sqrt(kB * max(temperature, 1e-12) / mass))
        self.colorbar.setLevels((0, self.vmax))
        self.side = None
        self.scatter.clear()

    def _draw_walls(self, domain: Domain, temps, t_gas: float):
        """Paredes térmicas: vermelho = mais quente que o gás inicial, azul = mais fria."""
        for item in self.wall_items:
            self.plot.removeItem(item)
        self.wall_items = []
        x0, y0 = domain.lower
        x1, y1 = domain.upper
        segments = [([x0, x0], [y0, y1]), ([x1, x1], [y0, y1]), ([x0, x1], [y0, y0]), ([x0, x1], [y1, y1])]
        for (xs, ys), t in zip(segments, temps):
            if t is None:
                continue
            color = "#e03131" if t > t_gas * 1.0001 else ("#1971c2" if t < t_gas * 0.9999 else "#f08c00")
            line = pg.PlotCurveItem(xs, ys, pen=pg.mkPen(color, width=7))
            line.setZValue(4)
            line.setToolTip(f"Parede térmica: T = {t:g}")
            self.plot.addItem(line)
            vertical = xs[0] == xs[1]
            if vertical:   # rótulo dentro da caixa, junto ao topo da parede
                text = pg.TextItem(f"T = {t:g}", color=color, anchor=(0.0, 0.0) if xs[0] == x0 else (1.0, 0.0),
                                   fill=pg.mkBrush(255, 255, 255, 170))
                text.setPos(xs[0], y1)
            else:          # rótulo fora da caixa, no meio da parede
                text = pg.TextItem(f"T = {t:g}", color=color, anchor=(0.5, 1.0 if ys[0] == y1 else 0.0))
                text.setPos(0.5 * (x0 + x1), ys[0])
            self.plot.addItem(text)
            self.wall_items += [line, text]

    def update_piston(self, x: float | None):
        if self.domain is None or x is None:
            return
        y0, y1 = self.domain.lower[1], self.domain.upper[1]
        self.piston_line.setData([x, x], [y0, y1])
        self.piston_shade.setRect(QtCore.QRectF(x, y0, max(self.domain.upper[0] - x, 0.0), y1 - y0))

    def set_initial(self, pos: np.ndarray):
        if self.domain is None:
            return
        xc = self.domain.lower[0] + 0.5 * self.domain.size[0]
        self.side = (pos[:, 0] > xc).astype(int)

    def set_mode(self, mode: str):
        self.mode = mode
        self.colorbar.setVisible(mode == "speed")
        if mode == "initial_side":
            self.legend_label.setText(
                f"<span style='color:{SIDE_COLORS[0]}'>●</span> começou na metade esquerda &nbsp;&nbsp;"
                f"<span style='color:{SIDE_COLORS[1]}'>●</span> começou na metade direita", size="9pt")
        elif mode == "species":
            self.legend_label.setText(
                f"<span style='color:{SIDE_COLORS[0]}'>●</span> espécie A &nbsp;&nbsp;"
                f"<span style='color:{SIDE_COLORS[1]}'>●</span> espécie B", size="9pt")
        else:
            self.legend_label.setText("Cinza: sólido • cor: módulo da velocidade", size="9pt")

    def set_point_size(self, size: float):
        self.scatter.setSize(size)

    def update_particles(self, pos: np.ndarray, vel: np.ndarray):
        if self.mode == "initial_side" and self.side is not None and len(self.side) == len(pos):
            brushes = [self.side_brushes[i] for i in self.side]
        elif self.mode == "species":
            sp = self.species if self.species is not None and len(self.species) == len(pos) else np.zeros(len(pos), int)
            brushes = [self.side_brushes[i] for i in sp]
        else:
            speed = np.hypot(vel[:, 0], vel[:, 1])
            top = float(speed.max()) if len(speed) else 1.0
            if top > self.vmax * 1.5 or top < self.vmax * 0.3:
                self.vmax = max(top / 1.2, 1e-12)
                self.colorbar.setLevels((0, self.vmax))
            idx = np.clip((speed / self.vmax * (len(self.brushes) - 1)).astype(int), 0, len(self.brushes) - 1)
            brushes = [self.brushes[i] for i in idx]
        self.scatter.setData(pos[:, 0], pos[:, 1], brush=brushes)

    def export_png(self, path: str):
        self.grab().save(path)


class ObservablePlot(pg.PlotWidget):
    """Gráfico genérico: série temporal, distribuição ou perfil."""

    def __init__(self, obs: Observable, parent=None):
        super().__init__(parent)
        self.obs = obs
        self.setMinimumHeight(210)
        self.setTitle(obs.title, size="10pt")
        self.setLabel("bottom", obs.xlabel)
        self.setLabel("left", obs.ylabel)
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setToolTip(obs.help)
        self.addLegend(offset=(-8, 8), labelTextSize="8pt", brush=pg.mkBrush(255, 255, 255, 120))
        self.items: dict[str, pg.GraphicsObject] = {}
        for c in obs.curves:
            if c.style == "bars":
                item = pg.BarGraphItem(x=[], height=[], width=1, brush=pg.mkBrush(c.color),
                                       pen=pg.mkPen("#ffffff", width=0.5), name=c.name)
                self.addItem(item)
            else:
                pen = pg.mkPen(c.color, width=2, style=QtCore.Qt.DashLine if c.style == "dash" else QtCore.Qt.SolidLine)
                item = self.plot([], [], pen=pen, name=c.name)
            self.items[c.name] = item
        if len(obs.curves) == 1:
            self.plotItem.legend.hide()
        for side in ("left", "bottom"):
            self.getAxis(side).enableAutoSIPrefix(False)
        self.refs: list[pg.GraphicsObject] = []

    def set_references(self, refs):
        for line in self.refs:
            self.removeItem(line)
        self.refs = []
        for r in refs or []:
            line = pg.InfiniteLine(pos=r.value, angle=0, movable=False,
                                   pen=pg.mkPen("#495057", width=1.2, style=QtCore.Qt.DashLine),
                                   label=r.label, labelOpts={"position": 0.06, "color": "#495057",
                                                             "fill": (255, 255, 255, 180), "anchors": [(0, 0), (0, 0)]})
            self.addItem(line)
            self.refs.append(line)
            # ponto invisível: garante que a escala automática inclua a referência
            anchor = pg.ScatterPlotItem([0.0], [r.value], size=1, pen=None, brush=pg.mkBrush(0, 0, 0, 0))
            self.addItem(anchor)
            self.refs.append(anchor)

    def clear_data(self):
        for c in self.obs.curves:
            item = self.items[c.name]
            if isinstance(item, pg.BarGraphItem):
                item.setOpts(x=[], height=[])
            else:
                item.setData([], [])

    def update_series(self, t: list[float], data: dict[str, list[float]]):
        for name, values in data.items():
            self.items[name].setData(t, values, connect="finite")

    def update_distribution(self, x: np.ndarray, data: dict[str, np.ndarray]):
        width = float(x[1] - x[0]) * 0.92 if len(x) > 1 else 1.0
        for name, y in data.items():
            item = self.items[name]
            y = np.asarray(y, float)
            if isinstance(item, pg.BarGraphItem):
                ok = np.isfinite(y)
                item.setOpts(x=x[ok], height=y[ok], width=width)
            else:
                item.setData(x, y, connect="finite")


class PlotPanel(QtWidgets.QScrollArea):
    """Coluna rolável com os gráficos selecionados."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        self.layout_ = QtWidgets.QVBoxLayout(inner)
        self.layout_.setContentsMargins(4, 4, 4, 4)
        self.layout_.setSpacing(6)
        self.placeholder = QtWidgets.QLabel("Selecione grandezas em “Visualizar”.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder.setStyleSheet("color:#868e96")
        self.layout_.addWidget(self.placeholder)
        self.layout_.addStretch(1)
        self.setWidget(inner)
        self.plots: dict[str, ObservablePlot] = {}

    def build(self, observables: list[Observable]):
        for p in self.plots.values():
            p.setParent(None)
            p.deleteLater()
        self.plots = {}
        for o in observables:
            plot = ObservablePlot(o)
            self.layout_.insertWidget(self.layout_.count() - 1, plot)
            self.plots[o.id] = plot
        self.placeholder.setVisible(not observables)

    def set_visible(self, visible_ids: set[str]):
        for oid, p in self.plots.items():
            p.setVisible(oid in visible_ids)
        self.placeholder.setVisible(not visible_ids)

    def visible_plots(self):
        return [(oid, p) for oid, p in self.plots.items() if p.isVisible()]
