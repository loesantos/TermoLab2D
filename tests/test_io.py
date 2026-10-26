import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from create_geometry import write_geometry


class IOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="md tests ")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.vtk = self.path / "geometry.vtk"
        write_geometry(self.vtk, (10, 8), 0.5)
        self.cfg = self.path / "simulation.cfg"
        self.cfg.write_text("geometry = geometry.vtk\nparticles = 40\ntemperature = 1\n"
                            "steps = 21\noutput_every = 10\nthreads = 2\nseed = 42\n", encoding="utf-8")

    def run_sim(self):
        return subprocess.run([str(ROOT / "build/simulator"), str(self.cfg)],
                              text=True, capture_output=True, timeout=30, cwd="/tmp")

    def test_frames_and_solid_mask(self):
        p = self.run_sim()
        self.assertEqual(p.returncode, 0, p.stderr)
        data = [json.loads(line) for line in p.stdout.splitlines()]
        meta, frames = data[0], data[1:]
        self.assertEqual(meta["spatial_dimension"], 2)
        self.assertEqual(meta["dims"], [10, 8])
        self.assertEqual([f["step"] for f in frames], [0, 10, 20, 21])
        solid = set(meta["solid_indices"])
        self.assertTrue(solid)
        import math
        for frame in frames:
            self.assertEqual(len(frame["positions"]), 40)
            self.assertEqual(len(frame["velocities"]), 40)
            self.assertAlmostEqual(frame["temperature"], frame["kinetic"] / (40 * meta["boltzmann"]))
            self.assertTrue(all(len(v) == 2 for v in frame["velocities"]))
            for pos in frame["positions"]:
                self.assertEqual(len(pos), 2)
                c = [math.floor((pos[a]-meta["lower"][a])/meta["spacing"][a]) for a in range(2)]
                self.assertTrue(all(0 <= c[a] < meta["dims"][a] for a in range(2)))
                self.assertNotIn(c[0] + meta["dims"][0]*c[1], solid)
        p2 = self.run_sim()
        second = [json.loads(line) for line in p2.stdout.splitlines()][1:]
        for f, g in zip(frames, second):
            self.assertEqual(f["positions"], g["positions"], "Semente fixa deve reproduzir a trajetória")
            self.assertEqual(f["velocities"], g["velocities"])
            self.assertAlmostEqual(f["kinetic"], g["kinetic"])
            self.assertAlmostEqual(f["potential"], g["potential"])

    def test_point_data_and_nonzero_values(self):
        self.vtk.write_text("# vtk DataFile Version 3.0\nPoint mask\nASCII\nDATASET STRUCTURED_POINTS\n"
                            "DIMENSIONS 2 2 1\nORIGIN 4 5 6\nSPACING 2 3 4\n"
                            "POINT_DATA 4\nSCALARS fluid int\nLOOKUP_TABLE default\n0 -2 1 1\n")
        p = self.run_sim()
        self.assertEqual(p.returncode, 0, p.stderr)
        meta = json.loads(p.stdout.splitlines()[0])
        self.assertEqual(meta["lower"], [3, 3.5])
        self.assertEqual(meta["dims"], [2, 2])
        self.assertEqual(meta["solid_indices"], [0])

    def test_reject_bad_config(self):
        for suffix in ("particles = -1", "cutoff = 0", "temperature = nan", "unknown = 3", "seed = -1"):
            with self.subTest(suffix=suffix):
                self.cfg.write_text("geometry = geometry.vtk\n"+suffix+"\n")
                p = self.run_sim()
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("Erro:", p.stderr)
                self.assertFalse(p.stdout)

    def test_reject_malformed_geometry(self):
        original = self.vtk.read_text()
        for content in (original.replace("DIMENSIONS 11 9 1", "DIMENSIONS 11 9 2"),
                        original.replace("ASCII", "BINARY"), original.replace("CELL_DATA 80", "CELL_DATA 79"),
                        original[:original.index("LOOKUP_TABLE")] + "LOOKUP_TABLE default\n1 0",
                        original.replace("SPACING 0.5 0.5 1", "SPACING 0 0.5 1"),
                        original[:original.index("LOOKUP_TABLE")] + "LOOKUP_TABLE default\n" + "0 "*80):
            with self.subTest(content=content[:80]):
                self.vtk.write_text(content)
                p = self.run_sim()
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("Erro:", p.stderr)

    def test_python_launch_record_and_render(self):
        snapshot, record = self.path / "result.png", self.path / "frames.jsonl"
        p = subprocess.run([sys.executable, str(ROOT / "visualize.py"), str(self.cfg), "--headless",
                            "--snapshot", str(snapshot), "--record", str(record)],
                           text=True, capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("passo 21", p.stdout)
        self.assertGreater(snapshot.stat().st_size, 10000)
        frames = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(frames[-1]["step"], 21)
        self.assertEqual(len(frames), 5)

    def test_live_stream_and_shutdown(self):
        from visualize import Stream
        stream = Stream(ROOT / "build/simulator", self.cfg, None, fps=10)
        try:
            self.assertTrue(stream.ready.wait(10))
            self.assertIsNone(stream.error)
            self.assertIsNotNone(stream.metadata)
            self.assertFalse(stream.done.is_set(), "Os quadros devem chegar durante a execução")
        finally:
            stream.close()
        self.assertIsNotNone(stream.process.poll())
        self.assertFalse(stream.reader_thread.is_alive())
        self.assertFalse(stream.stderr_thread.is_alive())
        self.assertIsNone(stream.error)

    def test_expansion_initial_region_and_release(self):
        write_geometry(self.vtk, (10, 8), 0.5, obstacle=False)
        self.cfg.write_text("geometry = geometry.vtk\nparticles = 80\ncharge = 0\n"
                            "temperature = 1\nthreads = 2\nsteps = 2000\ndt = 0.005\n"
                            "output_every = 2000\ninitial_x_min = 0\ninitial_x_max = 0.5\n")
        p = self.run_sim()
        self.assertEqual(p.returncode, 0, p.stderr)
        meta, initial, final = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(meta["solid_indices"], [])
        self.assertTrue(all(0 <= pos[0] < 2.5 for pos in initial["positions"]))
        self.assertTrue(any(pos[0] > 2.5 for pos in final["positions"]), "O corte inicial não pode funcionar como parede")
        self.assertTrue(all(0 <= x < 5 and 0 <= y < 4 for x, y in final["positions"]))
        self.assertAlmostEqual(initial["kinetic"], final["kinetic"], places=10)
        self.cfg.write_text(self.cfg.read_text().replace("initial_x_min = 0", "initial_x_min = 0.5")
                           .replace("initial_x_max = 0.5", "initial_x_max = 1").replace("steps = 2000", "steps = 0"))
        p = self.run_sim()
        self.assertEqual(p.returncode, 0, p.stderr)
        initial = json.loads(p.stdout.splitlines()[1])
        self.assertTrue(all(2.5 <= pos[0] < 5 for pos in initial["positions"]))

    def test_initial_region_partial_cells_uniform_area(self):
        self.vtk.write_text("# vtk DataFile Version 3.0\nMask\nASCII\nDATASET STRUCTURED_POINTS\n"
                            "DIMENSIONS 5 3 1\nORIGIN -3 2 0\nSPACING 1 0.5 1\n"
                            "CELL_DATA 8\nSCALARS fluid int\nLOOKUP_TABLE default\n1 1 1 1 1 1 1 1\n")
        self.cfg.write_text("geometry = geometry.vtk\nparticles = 30000\ncharge = 0\n"
                            "steps = 0\nthreads = 2\ninitial_x_min = 0\ninitial_x_max = 0.325\n")
        p = self.run_sim()
        self.assertEqual(p.returncode, 0, p.stderr)
        positions = json.loads(p.stdout.splitlines()[1])["positions"]
        self.assertTrue(all(-3 <= x < -1.7 and 2 <= y < 3 for x, y in positions))
        fraction = sum(x >= -2 for x, y in positions) / len(positions)
        self.assertAlmostEqual(fraction, 0.3 / 1.3, delta=0.015)
        self.assertAlmostEqual(sum(x for x, y in positions) / len(positions), -2.35, delta=0.015)

    def test_invalid_or_solid_initial_region(self):
        for limits in ((-0.1, 0.5), (0, 1.1), (0.5, 0.5), (0.7, 0.2)):
            with self.subTest(limits=limits):
                self.cfg.write_text(f"geometry = geometry.vtk\ninitial_x_min = {limits[0]}\ninitial_x_max = {limits[1]}\n")
                self.assertNotEqual(self.run_sim().returncode, 0)
        self.vtk.write_text("# vtk DataFile Version 3.0\nMask\nASCII\nDATASET STRUCTURED_POINTS\n"
                            "DIMENSIONS 3 2 1\nORIGIN 0 0 0\nSPACING 1 1 1\n"
                            "CELL_DATA 2\nSCALARS fluid int\nLOOKUP_TABLE default\n0 1\n")
        self.cfg.write_text("geometry = geometry.vtk\nthreads = 2\ninitial_x_max = 0.5\n")
        p = self.run_sim()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("não contém área livre", p.stderr)

    def test_python_propagates_errors(self):
        self.cfg.write_text("geometry = missing.vtk\n")
        p = subprocess.run([sys.executable, str(ROOT / "visualize.py"), str(self.cfg), "--headless"],
                           text=True, capture_output=True, timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("missing.vtk", p.stderr)


if __name__ == "__main__":
    unittest.main()
