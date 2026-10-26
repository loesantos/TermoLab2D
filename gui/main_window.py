"""Janela principal da interface didática."""
from __future__ import annotations

import queue
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import observables as obsmod
from . import scenarios as scmod
from .geometry import Domain
from .help_window import ManualWindow
from . import __version__
from .plots import ParticleView, PlotPanel
from .simulator import SimulatorRun, find_executable

BASE_FRAME_KEYS = {"type", "step", "time", "temperature", "kinetic", "potential", "positions", "velocities",
                   "pressure", "area", "wall_heat", "piston"}
SPEEDS = [("Lenta (10 quadros/s)", 10.0), ("Tempo real (30 quadros/s)", 30.0),
          ("Rápida (60 quadros/s)", 60.0), ("Máxima (sem limite)", None)]
COLOR_MODES = [("Módulo da velocidade", "speed"), ("Lado inicial (esquerda/direita)", "initial_side"),
               ("Espécie (A/B)", "species")]


# ---------------------------------------------------------------------------
class ParamForm(QtWidgets.QWidget):
    """Formulário gerado a partir de uma lista de `Param`."""
    changed = QtCore.Signal()

    def __init__(self, params: list[scmod.Param], parent=None):
        super().__init__(parent)
        self.params = params
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        form = self.form = QtWidgets.QFormLayout(self)
        form.setContentsMargins(6, 4, 6, 4)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        for p in params:
            w = self._make(p)
            label = QtWidgets.QLabel(p.label + (f" [{p.unit}]" if p.unit else ""))
            label.setToolTip(p.help)
            w.setToolTip(p.help)
            form.addRow(label, w)
            self.widgets[p.key] = w

    def _make(self, p: scmod.Param) -> QtWidgets.QWidget:
        if p.kind == "int":
            w = QtWidgets.QSpinBox()
            w.setRange(int(p.minimum if p.minimum is not None else -2**31 + 1),
                       int(p.maximum if p.maximum is not None else 2**31 - 1))
            w.setSingleStep(int(p.step or 1))
            w.setGroupSeparatorShown(True)
            w.valueChanged.connect(self.changed)
        elif p.kind == "float":
            w = QtWidgets.QDoubleSpinBox()
            w.setDecimals(p.decimals)
            w.setRange(p.minimum if p.minimum is not None else -1e12, p.maximum if p.maximum is not None else 1e12)
            w.setSingleStep(p.step or 0.1)
            w.valueChanged.connect(self.changed)
        elif p.kind == "bool":
            w = QtWidgets.QCheckBox()
            w.toggled.connect(self.changed)
        elif p.kind == "choice":
            w = QtWidgets.QComboBox()
            for label, value in p.choices or []:
                w.addItem(label, value)
            w.currentIndexChanged.connect(self.changed)
        elif p.kind == "file":
            w = QtWidgets.QWidget()
            lay = QtWidgets.QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            edit = QtWidgets.QLineEdit()
            btn = QtWidgets.QToolButton(text="…")
            lay.addWidget(edit, 1)
            lay.addWidget(btn)
            w.edit = edit  # type: ignore[attr-defined]

            def pick():
                path, _ = QtWidgets.QFileDialog.getOpenFileName(self, p.label, edit.text(), "VTK (*.vtk);;Todos (*)")
                if path:
                    edit.setText(path)
            btn.clicked.connect(pick)
            edit.textChanged.connect(self.changed)
        else:
            raise ValueError(f"Tipo de parâmetro desconhecido: {p.kind}")
        return w

    def apply_visibility(self, all_values: dict):
        for p in self.params:
            if p.show_if is not None:
                self.form.setRowVisible(self.widgets[p.key], p.visible(all_values))

    def values(self) -> dict:
        out = {}
        for p in self.params:
            w = self.widgets[p.key]
            if p.kind in ("int", "float"):
                out[p.key] = w.value()
            elif p.kind == "bool":
                out[p.key] = w.isChecked()
            elif p.kind == "choice":
                out[p.key] = w.currentData()
            elif p.kind == "file":
                out[p.key] = w.edit.text()
        return out

    def set_values(self, values: dict):
        for p in self.params:
            if p.key not in values:
                continue
            w, v = self.widgets[p.key], values[p.key]
            if p.kind in ("int", "float"):
                w.setValue(v)
            elif p.kind == "bool":
                w.setChecked(bool(v))
            elif p.kind == "choice":
                w.setCurrentIndex(max(0, w.findData(v)))
            elif p.kind == "file":
                w.edit.setText(str(v))


class Collapsible(QtWidgets.QWidget):
    """Seção com título clicável (usada para “Avançado”)."""

    def __init__(self, title: str, content: QtWidgets.QWidget, expanded=False, parent=None):
        super().__init__(parent)
        self.button = QtWidgets.QToolButton(text=title, checkable=True, checked=expanded)
        self.button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.button.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self.button.setStyleSheet("QToolButton{border:none;font-weight:bold}")
        self.content = content
        content.setVisible(expanded)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.button)
        lay.addWidget(content)
        self.button.toggled.connect(self._toggle)

    def _toggle(self, on):
        self.button.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.content.setVisible(on)


# ---------------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TermoLab2D — termodinâmica partícula a partícula")
        self.resize(1400, 860)
        self.run: SimulatorRun | None = None
        self.store: obsmod.DataStore | None = None
        self.domain: Domain | None = None
        self.meta: dict | None = None
        self.scenario: scmod.Scenario | None = None
        self.values: dict = {}
        self.workdir: Path | None = None
        self.last_cfg: Path | None = None
        self.last_frame: dict | None = None
        self.frame_keys: set[str] = set(BASE_FRAME_KEYS)
        self.forms: dict[str, ParamForm] = {}
        self.started_at = 0.0

        self._build_ui()
        self._build_menu()
        self.timer = QtCore.QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self._select_first()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self._heading("1. Escolha o caso"))
        top.addStretch(1)
        self.btn_help = QtWidgets.QPushButton(self.style().standardIcon(QtWidgets.QStyle.SP_DialogHelpButton), " Manual")
        self.btn_help.setToolTip("Manual de uso, na seção do caso selecionado (F1)")
        self.btn_help.clicked.connect(lambda: self.show_manual())
        top.addWidget(self.btn_help)
        lv.addLayout(top)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(250)
        self.tree.setMaximumHeight(280)
        cats: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for s in scmod.SCENARIOS:
            cat = cats.get(s.category)
            if cat is None:
                cat = QtWidgets.QTreeWidgetItem([s.category])
                cat.setFlags(QtCore.Qt.ItemIsEnabled)
                f = cat.font(0)
                f.setBold(True)
                cat.setFont(0, f)
                self.tree.addTopLevelItem(cat)
                cats[s.category] = cat
            item = QtWidgets.QTreeWidgetItem([s.title + ("" if s.available else "  (em breve)")])
            item.setData(0, QtCore.Qt.UserRole, s.id)
            item.setToolTip(0, s.summary)
            if not s.available:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#adb5bd")))
                f = item.font(0)
                f.setItalic(True)
                item.setFont(0, f)
            cat.addChild(item)
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(self._on_tree)
        lv.addWidget(self.tree)

        self.description = QtWidgets.QTextBrowser()
        self.description.setOpenLinks(False)
        self.description.anchorClicked.connect(self._on_description_link)
        self.description.setMinimumHeight(150)
        lv.addWidget(self.description, 1)

        lv.addWidget(self._heading("2. Parâmetros"))
        self.params_host = QtWidgets.QWidget()
        self.params_layout = QtWidgets.QVBoxLayout(self.params_host)
        self.params_layout.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.params_host)

        lv.addWidget(self._heading("3. Visualizar"))
        vis = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(vis)
        grid.setContentsMargins(6, 0, 6, 0)
        self.obs_checks: dict[str, QtWidgets.QCheckBox] = {}
        for i, o in enumerate(obsmod.OBSERVABLES):
            cb = QtWidgets.QCheckBox(o.title)
            cb.setToolTip(o.help)
            cb.toggled.connect(self._update_plot_visibility)
            grid.addWidget(cb, i, 0, 1, 2)
            self.obs_checks[o.id] = cb
        row = len(obsmod.OBSERVABLES)
        grid.addWidget(QtWidgets.QLabel("Cor das partículas:"), row, 0)
        self.color_combo = QtWidgets.QComboBox()
        for label, mode in COLOR_MODES:
            self.color_combo.addItem(label, mode)
        self.color_combo.currentIndexChanged.connect(self._on_color_mode)
        grid.addWidget(self.color_combo, row, 1)
        grid.addWidget(QtWidgets.QLabel("Velocidade de exibição:"), row + 1, 0)
        self.speed_combo = QtWidgets.QComboBox()
        for label, fps in SPEEDS:
            self.speed_combo.addItem(label, fps)
        self.speed_combo.setCurrentIndex(1)
        grid.addWidget(self.speed_combo, row + 1, 1)
        grid.addWidget(QtWidgets.QLabel("Tamanho dos pontos:"), row + 2, 0)
        self.size_spin = QtWidgets.QSpinBox(minimum=1, maximum=30, value=6)
        self.size_spin.valueChanged.connect(lambda v: self.view.set_point_size(v))
        grid.addWidget(self.size_spin, row + 2, 1)
        lv.addWidget(vis)

        out = QtWidgets.QWidget()
        og = QtWidgets.QGridLayout(out)
        og.setContentsMargins(6, 0, 6, 0)
        self.rec_jsonl = QtWidgets.QCheckBox("Gravar trajetória (JSONL)")
        self.rec_vtk = QtWidgets.QCheckBox("Gravar VTK (ParaView)")
        self.out_dir = QtWidgets.QLineEdit(str(Path.home() / "TermoLab2D_resultados"))
        browse = QtWidgets.QToolButton(text="…")
        browse.clicked.connect(self._choose_out_dir)
        og.addWidget(self.rec_jsonl, 0, 0)
        og.addWidget(self.rec_vtk, 0, 1)
        og.addWidget(QtWidgets.QLabel("Pasta:"), 1, 0)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(self.out_dir, 1)
        h.addWidget(browse)
        og.addLayout(h, 1, 1)
        lv.addWidget(Collapsible("Gravação de resultados", out))

        buttons = QtWidgets.QHBoxLayout()
        style = self.style()
        self.btn_start = QtWidgets.QPushButton(style.standardIcon(QtWidgets.QStyle.SP_MediaPlay), " Iniciar")
        self.btn_pause = QtWidgets.QPushButton(style.standardIcon(QtWidgets.QStyle.SP_MediaPause), " Pausar")
        self.btn_stop = QtWidgets.QPushButton(style.standardIcon(QtWidgets.QStyle.SP_MediaStop), " Parar")
        self.btn_reset = QtWidgets.QPushButton("Padrões")
        self.btn_reset.setToolTip("Restaura os valores padrão do caso")
        self.btn_start.setStyleSheet("QPushButton{font-weight:bold;padding:6px}")
        for b in (self.btn_start, self.btn_pause, self.btn_stop, self.btn_reset):
            buttons.addWidget(b)
        self.btn_start.clicked.connect(self.start)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_reset.clicked.connect(self._reset_values)
        lv.addLayout(buttons)

        scroll = self.controls_scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("painel_controles")
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(440)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        self.view = ParticleView()
        self.plots = PlotPanel()
        self.plots.build(obsmod.OBSERVABLES)
        right = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        right.addWidget(self.view)
        right.addWidget(self.plots)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        right.setSizes([620, 420])

        main = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        main.addWidget(scroll)
        main.addWidget(right)
        main.setStretchFactor(1, 1)
        main.setSizes([450, 990])
        self.setCentralWidget(main)

        self.status_label = QtWidgets.QLabel("Pronto.")
        self.progress = QtWidgets.QProgressBar(maximumWidth=220, textVisible=True)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self._set_running(False)

    @staticmethod
    def _heading(text):
        lab = QtWidgets.QLabel(text)
        lab.setStyleSheet("font-weight:bold;font-size:11pt;color:#1c3d5a;margin-top:6px")
        return lab

    def _build_menu(self):
        m = self.menuBar().addMenu("&Arquivo")
        m.addAction("Salvar imagem das partículas…", self.save_particles_png, QtGui.QKeySequence("Ctrl+S"))
        m.addAction("Salvar imagem da janela…", self.save_window_png)
        m.addAction("Exportar séries temporais (CSV)…", self.save_csv)
        m.addAction("Salvar configuração do caso (.cfg)…", self.save_cfg)
        m.addSeparator()
        m.addAction("Sair", self.close, QtGui.QKeySequence.Quit)
        h = self.menuBar().addMenu("A&juda")
        h.addAction("Manual de uso", lambda: self.show_manual(), QtGui.QKeySequence.HelpContents)
        h.addAction("Manual: índice", lambda: self.show_manual("topo"))
        h.addAction("Manual: primeira simulação", lambda: self.show_manual("primeira"))
        h.addAction("Manual: problemas comuns", lambda: self.show_manual("problemas"))
        h.addSeparator()
        h.addAction("Sobre o modelo", self.about_model)
        h.addAction("Sobre", lambda: QtWidgets.QMessageBox.about(
            self, "Sobre o TermoLab2D", f"<h3>TermoLab2D {__version__}</h3>"
            "<p>Termodinâmica partícula a partícula: laboratório didático de termodinâmica e "
            "mecânica estatística com um gás bidimensional simulado por dinâmica molecular.</p>"
            "<p>Simulação em C++/OpenMP; interface em Python (PySide6 + pyqtgraph).</p>"
            "<p>Software livre sob a licença MIT.</p>"))

    # ------------------------------------------------------------ casos
    def _select_first(self):
        first = self.tree.topLevelItem(0).child(0)
        self.tree.setCurrentItem(first)

    def _on_tree(self, item, _prev):
        sid = item.data(0, QtCore.Qt.UserRole) if item else None
        if sid is None:
            return
        if self.run is not None:
            self.stop()
        self.load_scenario(scmod.by_id(sid))

    def load_scenario(self, s: scmod.Scenario):
        self.scenario = s
        html = f"<h3 style='margin:0'>{s.title}</h3><p><i>{s.summary}</i></p>{s.description}"
        if not s.available:
            html += (f"<p style='color:#c92a2a'><b>Ainda não disponível.</b> Requer: {s.requires}. "
                     "O caso já está previsto na interface e será habilitado quando o simulador for estendido.</p>")
        html += (f"<p style='margin-top:10px'><a href='manual:{self._scenario_anchor()}'>"
                 "Mais detalhes, atividades sugeridas e explicações no manual →</a></p>")
        self.description.setHtml(html)
        while self.params_layout.count():
            w = self.params_layout.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.forms = {}
        groups: dict[str, list[scmod.Param]] = {}
        for p in s.all_params():
            groups.setdefault(p.group, []).append(p)
        if not s.available:
            groups = {}
        titles = {"Caso": "Geometria e condição inicial", "Gás": "Gás", "Avançado": "Avançado"}
        for g in ("Caso", "Gás", "Avançado"):
            if not groups.get(g):
                continue
            form = ParamForm(groups[g])
            form.changed.connect(self._update_param_visibility)
            self.forms[g] = form
            if g == "Avançado":
                self.params_layout.addWidget(Collapsible(titles[g], form))
            else:
                box = QtWidgets.QGroupBox(titles[g])
                bl = QtWidgets.QVBoxLayout(box)
                bl.setContentsMargins(2, 2, 2, 2)
                bl.addWidget(form)
                self.params_layout.addWidget(box)
        self._reset_values()
        self._update_param_visibility()
        QtCore.QTimer.singleShot(0, self._fit_controls_width)
        for oid, cb in self.obs_checks.items():
            cb.blockSignals(True)
            cb.setChecked(oid in s.observables and self._obs_available(oid))
            cb.blockSignals(False)
        self._refresh_obs_enabled()
        self.color_combo.setCurrentIndex(max(0, self.color_combo.findData(s.color_mode)))
        self._update_plot_visibility()
        self.btn_start.setEnabled(s.available)
        for p in self.plots.plots.values():
            p.clear_data()
            p.set_references([])

    def _fit_controls_width(self):
        """Alarga a coluna da esquerda o suficiente para o formulário do caso (sem cortar campos)."""
        scroll = getattr(self, "controls_scroll", None)
        if scroll is None:
            return
        need = scroll.widget().minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 2 * scroll.frameWidth() + 6
        scroll.setMinimumWidth(max(440, need))

    def _reset_values(self):
        if not self.scenario:
            return
        vals = scmod.default_values(self.scenario)
        for f in self.forms.values():
            f.set_values(vals)

    def _update_param_visibility(self):
        if not self.scenario or not self.forms:
            return
        vals = self._form_values()
        for f in self.forms.values():
            f.apply_visibility(vals)

    def _form_values(self) -> dict:
        vals = scmod.default_values(self.scenario)
        for f in self.forms.values():
            vals.update(f.values())
        return vals

    # ------------------------------------------------------- observáveis
    def _obs_available(self, oid: str) -> bool:
        return obsmod.by_id(oid).available(self.frame_keys)

    def _refresh_obs_enabled(self):
        for oid, cb in self.obs_checks.items():
            o = obsmod.by_id(oid)
            ok = o.available(self.frame_keys)
            cb.setEnabled(ok)
            cb.setToolTip(o.help if ok else o.help + "\n(Ainda não fornecido pelo simulador.)")
            if not ok:
                cb.setChecked(False)

    def _update_plot_visibility(self):
        self.plots.set_visible({oid for oid, cb in self.obs_checks.items() if cb.isChecked()})
        self._redraw_plots()

    def _on_color_mode(self):
        self.view.set_mode(self.color_combo.currentData())
        if self.last_frame is not None:
            self._draw_particles(self.last_frame)

    # ------------------------------------------------------------ execução
    def _set_running(self, running: bool, paused: bool = False):
        self.params_host.setEnabled(not running)
        self.tree.setEnabled(True)
        self.btn_start.setEnabled(not running and (self.scenario is None or self.scenario.available))
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        self.btn_reset.setEnabled(not running)
        self.speed_combo.setEnabled(not running)
        self.btn_pause.setText(" Continuar" if paused else " Pausar")
        self.btn_pause.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.SP_MediaPlay if paused else QtWidgets.QStyle.SP_MediaPause))

    def start(self):
        if self.run is not None or not self.scenario or not self.scenario.available:
            return
        try:
            self.values = self._form_values()
            if self.values["t_final"] / self.values["dt"] > 2**31 - 2:
                raise RuntimeError("Tempo de simulação / dt excede o número máximo de passos.")
            self.workdir = Path(tempfile.mkdtemp(prefix="termolab2d_"))
            self.last_cfg = scmod.write_config(self.scenario, self.values, self.workdir)
            exe = find_executable(log=self._status)
            record = vtk_dir = None
            if self.rec_jsonl.isChecked() or self.rec_vtk.isChecked():
                stamp = time.strftime("%Y%m%d_%H%M%S")
                base = Path(self.out_dir.text()).expanduser() / f"{self.scenario.id}_{stamp}"
                base.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.last_cfg, base / "simulacao.cfg")
                if self.rec_jsonl.isChecked():
                    record = base / "trajetoria.jsonl"
                if self.rec_vtk.isChecked():
                    vtk_dir = base / "vtk"
                self._status(f"Gravando em {base}")
            self.run = SimulatorRun(exe, self.last_cfg, fps=self.speed_combo.currentData(),
                                    record=record, vtk_dir=vtk_dir)
        except Exception as exc:  # noqa: BLE001
            self.run = None
            QtWidgets.QMessageBox.critical(self, "Não foi possível iniciar", str(exc))
            return
        self.meta = None
        self.store = None
        self.last_frame = None
        self.started_at = time.monotonic()
        for p in self.plots.plots.values():
            p.clear_data()
        refs = dict(self.scenario.references(self.values)) if self.scenario.references else {}
        refs.setdefault("temperature", [scmod.Reference(self.values["temperature"], "T inicial")])
        for oid, p in self.plots.plots.items():
            p.set_references(refs.get(oid, []))
        self.progress.setValue(0)
        self._set_running(True)
        self._status("Equilibrando o gás na condição inicial…" if self.values.get("t_equil", 0) > 0
                     else "Iniciando o simulador…")
        self.timer.start()

    def toggle_pause(self):
        if not self.run:
            return
        if self.run.paused:
            self.run.resume()
            self._set_running(True, paused=False)
        else:
            self.run.pause()
            self._set_running(True, paused=True)
            self._status("Pausado.", keep=True)

    def stop(self):
        if not self.run:
            return
        self.timer.stop()
        run, self.run = self.run, None
        for item in run.drain():
            self._handle(item)
        run.stop()
        self._redraw_plots()
        self._set_running(False)
        self._status("Interrompido pelo usuário.", keep=True)

    def _tick(self):
        run = self.run
        if run is None:
            return
        deadline = time.monotonic() + 0.025
        newest = None
        while time.monotonic() < deadline:
            try:
                item = run.items.get_nowait()
            except queue.Empty:
                break
            if self._handle(item):
                newest = item
        if newest is not None:
            self._draw_particles(newest)
            self._redraw_plots()
            self._update_status(newest)
        if run.finished.is_set() and run.items.empty():
            self.timer.stop()
            self.run = None
            run.stop()
            self._set_running(False)
            if run.error:
                self._status("Erro na simulação.", keep=True)
                QtWidgets.QMessageBox.critical(self, "Erro na simulação", run.error)
            else:
                elapsed = time.monotonic() - self.started_at
                self.progress.setValue(100)
                self._status(f"Concluída em {elapsed:.1f} s. " + self._summary(), keep=True)

    def _handle(self, item: dict) -> bool:
        if item.get("type") == "metadata":
            self.meta = item
            self.domain = Domain.from_metadata(item)
            self.view.set_domain(self.domain, item["target_temperature"], item["boltzmann"], item["mass"], item)
            self.view.set_mode(self.color_combo.currentData())
            self.view.set_point_size(self.size_spin.value())
            return False
        if item.get("type") != "frame" or self.meta is None:
            return False
        if self.store is None:
            keys = set(item.keys())
            if keys != self.frame_keys:
                self.frame_keys = keys | BASE_FRAME_KEYS
                self._refresh_obs_enabled()
            ctx = obsmod.Context(meta=self.meta, domain=self.domain, n=int(self.meta["particles"]),
                                 kB=float(self.meta["boltzmann"]), mass=float(self.meta["mass"]))
            self.store = obsmod.DataStore(ctx, self.frame_keys)
        pos, _ = self.store.add(item)
        if self.last_frame is None:
            self.view.set_initial(pos)
        self.last_frame = item
        return True

    # ------------------------------------------------------------ desenho
    def _draw_particles(self, frame):
        pos = np.asarray(frame["positions"], float).reshape(-1, 2)
        vel = np.asarray(frame["velocities"], float).reshape(-1, 2)
        self.view.update_particles(pos, vel)
        piston = frame.get("piston")
        if piston:
            self.view.update_piston(piston.get("x"))

    def _redraw_plots(self):
        if self.store is None:
            return
        for oid, plot in self.plots.visible_plots():
            o = plot.obs
            if o.kind == "series" and oid in self.store.series:
                plot.update_series(self.store.time, self.store.series[oid])
            elif oid in self.store.latest:
                x, data = self.store.latest[oid]
                plot.update_distribution(x, data)

    def _update_status(self, frame):
        steps = max(1, int(self.meta["steps"]))
        self.progress.setValue(int(100 * frame["step"] / steps))
        n = self.meta["particles"]
        e = (frame["kinetic"] + frame["potential"]) / n
        self.status_label.setText(f"t = {frame['time']:.3f}   •   passo {frame['step']:,}/{steps:,}   •   "
                                  f"T = {frame['temperature']:.4f}   •   E/N = {e:.5f}   •   N = {n:,}".replace(",", "."))

    def _summary(self) -> str:
        if not self.store or not self.store.time:
            return ""
        law = self.store.series.get("first_law", {})
        q, w = law.get("Q (calor das paredes)", [0.0]), law.get("W (trabalho do pistão)", [0.0])
        if law and (abs(q[-1]) > 1e-12 or abs(w[-1]) > 1e-12):
            de, qw = law["ΔE (energia interna)"][-1], law["Q + W"][-1]
            return (f"Sistema aberto — primeira lei: ΔE/N = {de:.4f}, (Q + W)/N = {qw:.4f} "
                    f"(diferença {abs(de - qw):.1e}).")
        e = self.store.series.get("energy", {}).get("total", [])
        if len(e) > 1 and e[0] != 0:
            return f"Variação relativa da energia total: {abs(e[-1] - e[0]) / abs(e[0]):.2e}."
        return ""

    def _status(self, text, keep=False):
        self.status_label.setText(text)
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)

    # ---------------------------------------------------------- exportação
    def _ask_save(self, title, name, filt):
        start = str(Path(self.out_dir.text()).expanduser() / name)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, start, filt)
        return path

    def save_particles_png(self):
        path = self._ask_save("Salvar imagem", "particulas.png", "PNG (*.png)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.view.export_png(path)

    def save_window_png(self):
        path = self._ask_save("Salvar imagem da janela", "janela.png", "PNG (*.png)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.grab().save(path)

    def save_csv(self):
        if not self.store or not self.store.time:
            QtWidgets.QMessageBox.information(self, "Sem dados", "Rode uma simulação primeiro.")
            return
        path = self._ask_save("Exportar séries", "series.csv", "CSV (*.csv)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.store.to_csv(path)

    def save_cfg(self):
        if not self.scenario or not self.scenario.available:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Pasta para a configuração",
                                                            str(Path(self.out_dir.text()).expanduser()))
        if not folder:
            return
        try:
            folder = Path(folder)
            cfg = scmod.config_lines(self.scenario, self._form_values(), folder)
            geom = Path(cfg["geometry"])
            if geom.parent.resolve() != folder.resolve():
                shutil.copy2(geom, folder / geom.name)
            cfg["geometry"] = geom.name
            with (folder / f"{self.scenario.id}.cfg").open("w", encoding="utf-8", newline="\n") as out:
                out.write(f"# {self.scenario.title}\n")
                for k, v in cfg.items():
                    out.write(f"{k} = {v}\n")
            self._status(f"Configuração salva em {folder / (self.scenario.id + '.cfg')}", keep=True)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Erro", str(exc))

    def _choose_out_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Pasta de resultados", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    # ------------------------------------------------------------- manual
    def _scenario_anchor(self) -> str:
        return f"caso-{self.scenario.id}" if self.scenario else "topo"

    def show_manual(self, anchor: str | None = None):
        if getattr(self, "manual", None) is None:
            self.manual = ManualWindow(self)
        self.manual.show_section(anchor if anchor is not None else self._scenario_anchor())

    def _on_description_link(self, url: QtCore.QUrl):
        if url.scheme() == "manual":
            self.show_manual(url.path() or url.toString().split(":", 1)[1])
        else:
            QtGui.QDesktopServices.openUrl(url)

    def about_model(self):
        QtWidgets.QMessageBox.information(self, "Sobre o modelo", (
            "Partículas em 2D, integradas por velocity Verlet.\n\n"
            "Interação entre pares (escolha em “Interação”):\n"
            "• WCA: 4ε[(σ/r)¹² − (σ/r)⁶] + ε, cortado em 2^(1/6)σ — só repulsão (discos macios).\n"
            "• Lennard-Jones: 4ε[(σ/r)¹² − (σ/r)⁶], cortado em 2,5σ e deslocado — repulsão + atração.\n"
            "• Coulomb: q²/r com raio de corte e suavização — repulsão de longo alcance.\n"
            "• Sem interação: as partículas só colidem com as paredes.\n\n"
            "Condição inicial: posições sorteadas sem sobreposição (distância mínima 2^(1/6)σ no WCA/LJ) "
            "e equilibração antes de t = 0, com paredes temporárias na região inicial e temperatura fixa.\n"
            "Depois de t = 0 não há termostato: a energia total se conserva.\n"
            "Paredes e sólidos: reflexão especular; paredes térmicas devolvem as partículas com "
            "velocidades sorteadas na temperatura da parede. Pistão: colisão elástica no referencial "
            "da parede móvel. Unidades reduzidas: m = k_B = 1.\n\n"
            "Pressão: impulso transferido às paredes por unidade de comprimento e de tempo.\n"
            "Temperatura: T = K/(N k_B), com 2 graus de liberdade por partícula.\n"
            "Entropia: estimativa de Boltzmann em grade grossa (posições e velocidades), "
            "mostrada como variação em relação ao instante inicial."))

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._fit_controls_width)

    def closeEvent(self, event):
        if self.run is not None:
            self.stop()
        super().closeEvent(event)
