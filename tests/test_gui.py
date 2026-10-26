"""Testes da interface didática: casos, geometrias e grandezas (sem abrir janela)."""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gui import geometry as geo  # noqa: E402
from gui import observables as obs  # noqa: E402
from gui import scenarios as sc  # noqa: E402
from gui.simulator import SimulatorRun, find_executable  # noqa: E402


def run_metadata(cfg: Path) -> tuple[dict, dict]:
    exe = find_executable(log=lambda *_: None)
    out = subprocess.run([str(exe), str(cfg)], capture_output=True, text=True, encoding="utf-8", check=True)
    lines = [json.loads(l) for l in out.stdout.splitlines()]
    return lines[0], lines[1]


class ScenarioTests(unittest.TestCase):
    def test_available_scenarios_produce_valid_configs(self):
        for s in sc.SCENARIOS:
            if not s.available:
                continue
            with self.subTest(s.id), tempfile.TemporaryDirectory() as d:
                vals = sc.default_values(s)
                vals["t_final"] = 0.0          # steps = 0: só a condição inicial
                vals["particles"] = 50
                vals["n_each"] = 25                  # caso de duas espécies
                cfg = sc.write_config(s, vals, Path(d))
                meta, frame = run_metadata(cfg)
                self.assertEqual(meta["particles"], 50)
                self.assertEqual(frame["step"], 0)

    def test_every_interaction_runs(self):
        for pot in ("wca", "lj", "coulomb", "none"):
            with self.subTest(pot), tempfile.TemporaryDirectory() as d:
                vals = sc.default_values(sc.EXPANSION)
                vals.update(potential=pot, particles=200, t_final=0.05, t_equil=0.5)
                cfg = sc.config_lines(sc.EXPANSION, vals, Path(d))
                self.assertEqual(cfg["min_distance"] > 0, pot in ("wca", "lj"))
                meta, frame = run_metadata(sc.write_config(sc.EXPANSION, vals, Path(d)))
                self.assertEqual(meta["potential"], pot)
                xs = [p[0] for p in frame["positions"]]
                self.assertLess(max(xs), 20.0)              # equilibrado só na metade esquerda
                self.assertAlmostEqual(frame["temperature"], 1.0, places=9)

    def test_channel_matches_original_example(self):
        with tempfile.TemporaryDirectory() as d:
            vals = sc.default_values(sc.CHANNEL)
            vals["opening"] = 4.0                  # canal do exemplo channel_box.vtk
            cfg = sc.config_lines(sc.CHANNEL, vals, Path(d))
            self.assertAlmostEqual(cfg["initial_x_max"], 0.475)
            gen = Path(cfg["geometry"]).read_text().split("LOOKUP_TABLE default\n")[1].split()
            ref = (ROOT / "examples" / "channel_box.vtk").read_text().split("LOOKUP_TABLE default\n")[1].split()
            self.assertEqual(gen, ref)

    def test_planned_scenarios_declare_requirements(self):
        self.assertTrue(all(s.requires for s in sc.SCENARIOS if not s.available))

    def test_new_cases_emit_expected_data(self):
        cases = {"conduction": lambda m, f: m["wall_temperatures"][:2] == [2.0, 0.5],
                 "heating": lambda m, f: all(t == 2.0 for t in m["wall_temperatures"]),
                 "h_theorem": lambda m, f: m["velocity_distribution"] == "mono",
                 "mixing": lambda m, f: m["particles_b"] == 40 and sum(m["species"]) == 40,
                 "piston": lambda m, f: f["piston"]["x"] == 40.0,
                 "ideal_gas": lambda m, f: f["pressure"] is None and f["area"] == 400.0}
        for sid, check in cases.items():
            with self.subTest(sid), tempfile.TemporaryDirectory() as d:
                s = sc.by_id(sid)
                vals = sc.default_values(s)
                vals.update(particles=40, n_each=40, t_final=0.0, t_equil=0.2)
                meta, frame = run_metadata(sc.write_config(s, vals, Path(d)))
                self.assertTrue(check(meta, frame), sid)

    def test_observables_referenced_by_scenarios_exist(self):
        ids = {o.id for o in obs.OBSERVABLES}
        for s in sc.SCENARIOS:
            self.assertTrue(set(s.observables) <= ids, s.id)


class ManualTests(unittest.TestCase):
    def test_manual_links_images_and_cases(self):
        import re
        manual = ROOT / "gui" / "manual" / "manual.html"
        html = manual.read_text(encoding="utf-8")
        names = set(re.findall(r'<a name="([^"]+)"', html))
        self.assertEqual(set(re.findall(r'href="#([^"]+)"', html)) - names, set(), "links internos quebrados")
        for src in re.findall(r'<img src="([^"]+)"', html):
            self.assertTrue((manual.parent / src).is_file(), src)
        for s in sc.SCENARIOS:
            self.assertIn(f"caso-{s.id}", names, f"caso sem seção no manual: {s.id}")


class ObservableTests(unittest.TestCase):
    def setUp(self):
        fluid = geo.box(40, 20)
        meta = {"dims": [fluid.shape[1], fluid.shape[0]], "lower": [0, 0], "spacing": [0.5, 0.5], "solid_indices": []}
        self.domain = geo.Domain.from_metadata(meta)
        self.rng = np.random.default_rng(1)

    def test_configurational_entropy_doubling_area_gives_ln2(self):
        n = 20000
        full = self.rng.uniform([0, 0], [40, 20], size=(n, 2))
        half = self.rng.uniform([0, 0], [20, 20], size=(n, 2))
        ds = obs.configurational_entropy(full, self.domain) - obs.configurational_entropy(half, self.domain)
        self.assertAlmostEqual(ds, math.log(2), delta=0.01)
        self.assertAlmostEqual(obs.configurational_entropy(full, self.domain), math.log(800), delta=0.01)

    def test_velocity_entropy_of_maxwellian(self):
        for t in (0.5, 2.0):
            v = self.rng.normal(0, math.sqrt(t), size=(50000, 2))
            self.assertAlmostEqual(obs.velocity_entropy(v), 1 + math.log(2 * math.pi * t), delta=0.03)

    def test_speed_histogram_is_normalized(self):
        ctx = obs.Context(meta={}, domain=self.domain, n=20000, kB=1.0, mass=1.0)
        v = self.rng.normal(0, 1, size=(20000, 2))
        x, data = obs.SpeedHistogram().compute({"temperature": 1.0}, None, v, ctx)
        width = x[1] - x[0]
        self.assertAlmostEqual(data["simulação"].sum() * width, 1.0, delta=0.01)
        self.assertLess(np.abs(data["simulação"] - data["Maxwell–Boltzmann (T atual)"]).max(), 0.05)

    def test_density_profile_uniform(self):
        ctx = obs.Context(meta={}, domain=self.domain, n=40000, kB=1.0, mass=1.0)
        pos = self.rng.uniform([0, 0], [40, 20], size=(40000, 2))
        _, data = obs.DensityProfile().compute({}, pos, None, ctx)
        self.assertAlmostEqual(float(np.nanmean(data["instantâneo"])), 1.0, delta=0.02)

    def test_pressure_unavailable_until_simulator_emits_it(self):
        base = {"type", "step", "time", "temperature", "kinetic", "potential", "positions", "velocities"}
        self.assertFalse(obs.Pressure().available(base))
        self.assertTrue(obs.Pressure().available(base | {"pressure"}))

    def test_mixing_entropy_of_fully_mixed_state(self):
        n = 20000
        meta = {"species": [0] * (n // 2) + [1] * (n // 2), "masses": [1.0, 1.0]}
        ctx = obs.Context(meta=meta, domain=self.domain, n=n, kB=1.0, mass=1.0)
        left = np.r_[self.rng.uniform([0, 0], [20, 20], size=(n // 2, 2)),
                     self.rng.uniform([20, 0], [40, 20], size=(n // 2, 2))]
        mixed = self.rng.uniform([0, 0], [40, 20], size=(n, 2))
        o = obs.MixingEntropy()
        o.compute({}, left, None, ctx)
        out = o.compute({}, mixed, None, ctx)
        self.assertAlmostEqual(out["distinguindo as espécies"], math.log(2), delta=0.02)
        self.assertAlmostEqual(out["sem distinguir (só posições)"], 0.0, delta=0.02)

    def test_boltzmann_h_of_maxwellian(self):
        ctx = obs.Context(meta={}, domain=self.domain, n=50000, kB=1.0, mass=1.0)
        v = self.rng.normal(0, 1, size=(50000, 2))
        out = obs.BoltzmannH().compute({"temperature": 1.0}, None, v, ctx)
        self.assertAlmostEqual(out["H"], out["equilíbrio (Maxwell)"], delta=0.03)


class RunnerTests(unittest.TestCase):
    def test_pause_blocks_simulator_and_resume_finishes(self):
        with tempfile.TemporaryDirectory() as d:
            vals = sc.default_values(sc.EQUILIBRIUM)
            vals.update(particles=200, t_final=2.0, output_every=10)
            cfg = sc.write_config(sc.EQUILIBRIUM, vals, Path(d))
            run = SimulatorRun(find_executable(log=lambda *_: None), cfg, queue_size=4)
            run.pause()
            import time
            time.sleep(0.5)
            run.drain()
            time.sleep(0.5)
            self.assertLessEqual(len(run.drain()), 1)   # pausado: nada (ou um item já lido) chega
            self.assertFalse(run.finished.is_set())
            run.resume()
            items = []
            while not (run.finished.is_set() and run.items.empty()):
                items += run.drain()
                time.sleep(0.01)
            run.stop()
            self.assertIsNone(run.error)
            self.assertEqual([i for i in items if i["type"] == "frame"][-1]["step"], 2000)


def _qt_available() -> bool:
    try:
        import PySide6  # noqa: F401
        import pyqtgraph  # noqa: F401
    except ImportError:
        return False
    return os.environ.get("QT_QPA_PLATFORM") == "offscreen"


@unittest.skipUnless(_qt_available(), "requer PySide6/pyqtgraph e QT_QPA_PLATFORM=offscreen")
class WindowTests(unittest.TestCase):
    def test_window_runs_expansion(self):
        import time
        from PySide6 import QtWidgets
        from gui.main_window import MainWindow
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        w = MainWindow()
        w.forms["Gás"].widgets["particles"].setValue(300)
        w.forms["Gás"].widgets["t_final"].setValue(1.0)
        w.speed_combo.setCurrentIndex(3)
        w.start()
        t0 = time.time()
        while w.run is not None and time.time() - t0 < 60:
            app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(w.run)
        self.assertAlmostEqual(w.store.time[-1], 1.0)
        w.close()


if __name__ == "__main__":
    unittest.main()
