import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vtk_export import VTKWriter
from create_geometry import write_geometry


class VTKExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vtk export test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.meta = {"type": "metadata", "spatial_dimension": 2, "dims": [2, 2],
                     "lower": [-1, 2], "spacing": [0.5, 2], "solid_indices": [1],
                     "particles": 2, "mass": 2}
        self.frame = {"type": "frame", "step": 0, "time": 0, "temperature": 13,
                      "kinetic": 26, "potential": 4,
                      "positions": [[-0.75, 3], [-0.25, 5]], "velocities": [[3, 4], [0, -1]]}

    def test_particle_attributes_and_geometry(self):
        writer = VTKWriter(self.root / "out")
        writer.write_metadata(self.meta)
        writer.write_frame(self.frame)
        lines = (writer.directory / "particles_000000000.vtk").read_text().splitlines()
        points = lines.index("POINTS 2 double")
        self.assertEqual([list(map(float, line.split())) for line in lines[points+1:points+3]],
                         [[-0.75, 3, 0], [-0.25, 5, 0]])
        v = lines.index("VECTORS velocity double")
        self.assertEqual([list(map(float, line.split())) for line in lines[v+1:v+3]], [[3, 4, 0], [0, -1, 0]])
        for name, expected in (("speed", [5, 1]), ("particle_kinetic_energy", [25, 1]), ("particle_id", [0, 1])):
            header = next(i for i, line in enumerate(lines) if line.startswith("SCALARS " + name + " "))
            self.assertEqual([float(v) for v in lines[header+2:header+4]], expected)
        geometry = (writer.directory / "geometry.vtk").read_text()
        self.assertIn("ORIGIN -1 2 0", geometry)
        self.assertIn("DIMENSIONS 3 3 1", geometry)
        self.assertTrue(geometry.endswith("1 0\n1 1\n"))

    def test_existing_directory_is_preserved(self):
        directory = self.root / "existing"
        directory.mkdir()
        original = directory / "particles.vtk.series"
        original.write_text("preserve me")
        with self.assertRaises(RuntimeError):
            VTKWriter(directory)
        self.assertEqual(original.read_text(), "preserve me")

    def test_invalid_frame_keeps_completed_series(self):
        writer = VTKWriter(self.root / "out")
        writer.write_metadata(self.meta)
        writer.write_frame(self.frame)
        for bad in (dict(self.frame), dict(self.frame, step=1, time=1, positions=[[math.nan, 3], [0, 0]])):
            with self.assertRaises(ValueError):
                writer.write_frame(bad)
        self.assertEqual(len(json.loads((writer.directory / "particles.vtk.series").read_text())["files"]), 1)
        self.assertEqual(len(list(writer.directory.glob("particles_*.vtk"))), 1)
        self.assertFalse(list(writer.directory.glob(".writing-*")))

    def test_live_export_all_frames_and_jsonl_conversion(self):
        geometry = self.root / "mask.vtk"
        write_geometry(geometry, (10, 8), 0.5)
        config = self.root / "test.cfg"
        config.write_text("geometry = mask.vtk\nparticles = 12\nthreads = 2\nsteps = 21\noutput_every = 10\n")
        output = self.root / "live"
        record = self.root / "frames.jsonl"
        command = [sys.executable, str(ROOT / "visualize.py"), str(config), "--headless", "--vtk-dir", str(output),
                   "--record", str(record)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        frames = [json.loads(line) for line in record.read_text().splitlines()][1:]
        entries = json.loads((output / "particles.vtk.series").read_text())["files"]
        self.assertEqual([item["time"] for item in entries], [f["time"] for f in frames])
        self.assertEqual([item["name"] for item in entries], [f"particles_{i:09d}.vtk" for i in (0, 10, 20, 21)])
        for entry, frame in zip(entries, frames):
            lines = (output / entry["name"]).read_text().splitlines()
            start = lines.index("POINTS 12 double") + 1
            actual = [list(map(float, s.split())) for s in lines[start:start+12]]
            self.assertEqual(actual, [p + [0] for p in frame["positions"]])
        converted = self.root / "converted"
        result = subprocess.run([sys.executable, str(ROOT / "vtk_export.py"), str(record), "--vtk-dir", str(converted)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in output.iterdir()), sorted(p.name for p in converted.iterdir()))
        for path in output.iterdir():
            self.assertEqual(path.read_bytes(), (converted / path.name).read_bytes())
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("já existe", result.stderr)

    def test_interrupt_preserves_exported_frames(self):
        from visualize import Stream
        import time
        geometry = self.root / "mask.vtk"
        write_geometry(geometry, (10, 8), 0.5)
        config = self.root / "test.cfg"
        config.write_text("geometry = mask.vtk\nparticles = 12\nthreads = 2\nsteps = 1000\noutput_every = 1\n")
        output = self.root / "interrupted"
        stream = Stream(ROOT / "build/simulator", config, None, fps=20, vtk_dir=output)
        try:
            self.assertTrue(stream.ready.wait(10))
            deadline = time.monotonic() + 10
            while len(stream.vtk.entries) < 2 and not stream.done.is_set() and time.monotonic() < deadline:
                stream.done.wait(0.01)
            self.assertGreaterEqual(len(stream.vtk.entries), 2)
        finally:
            stream.close()
        self.assertIsNone(stream.error)
        self.assertFalse(stream.reader_thread.is_alive())
        entries = json.loads((output / "particles.vtk.series").read_text())["files"]
        self.assertLess(len(entries), 1001)
        for entry in entries:
            self.assertTrue((output / entry["name"]).is_file())
        self.assertFalse(list(output.glob(".writing-*")))

    def test_reject_record_in_vtk_directory(self):
        output = self.root / "out"
        result = subprocess.run([sys.executable, str(ROOT / "visualize.py"), "--headless", "--vtk-dir", str(output),
                                 "--record", str(output / "particles.vtk.series")],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
