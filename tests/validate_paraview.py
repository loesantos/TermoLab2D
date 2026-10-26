"""Validação opcional com o leitor real do ParaView, sem abrir janela.

Uso: pvpython --no-mpi tests/validate_paraview.py PASTA_VTK TRAJETORIA_JSONL
"""
from pathlib import Path
import json
import math
import sys
from paraview.simple import OpenDataFile, Delete
from paraview import servermanager
from vtkmodules.vtkIOLegacy import vtkPolyDataReader, vtkStructuredPointsReader


def validate(directory, reference):
    data = [json.loads(line) for line in reference.read_text().splitlines() if line.strip()]
    meta, frames = data[0], data[1:]
    entries = json.loads((directory / "particles.vtk.series").read_text())["files"]
    assert len(entries) == len(frames)
    for entry, frame in zip(entries, frames):
        reader = vtkPolyDataReader()
        reader.SetFileName(str(directory / entry["name"]))
        reader.ReadAllScalarsOn()
        reader.ReadAllVectorsOn()
        reader.Update()
        assert reader.GetErrorCode() == 0
        points = reader.GetOutput()
        assert points.GetNumberOfPoints() == meta["particles"]
        assert points.GetNumberOfVerts() == meta["particles"]
        pd, fd = points.GetPointData(), points.GetFieldData()
        for name in ("particle_id", "speed", "velocity", "particle_kinetic_energy"):
            assert pd.GetArray(name) is not None, name
            assert pd.GetArray(name).GetNumberOfTuples() == meta["particles"]
        assert fd.GetArray("step").GetTuple1(0) == frame["step"]
        for field, expected in (("TIME", frame["time"]), ("temperature", frame["temperature"]),
                                ("kinetic_energy", frame["kinetic"]), ("potential_energy", frame["potential"]),
                                ("total_energy", frame["kinetic"] + frame["potential"])):
            assert math.isclose(fd.GetArray(field).GetTuple1(0), expected, rel_tol=1e-14, abs_tol=1e-14)
        for i, (p, v) in enumerate(zip(frame["positions"], frame["velocities"])):
            assert points.GetPoint(i) == tuple(p + [0])
            assert pd.GetArray("velocity").GetTuple(i) == tuple(v + [0])
            assert pd.GetArray("particle_id").GetTuple1(i) == i
            assert math.isclose(pd.GetArray("speed").GetTuple1(i), math.hypot(*v), rel_tol=1e-14, abs_tol=1e-14)
            assert math.isclose(pd.GetArray("particle_kinetic_energy").GetTuple1(i),
                                0.5 * meta["mass"] * sum(x*x for x in v), rel_tol=1e-14, abs_tol=1e-14)
    geometry = vtkStructuredPointsReader()
    geometry.SetFileName(str(directory / "geometry.vtk"))
    geometry.Update()
    assert geometry.GetErrorCode() == 0
    grid = geometry.GetOutput()
    nx, ny = meta["dims"]
    assert grid.GetDimensions() == (nx+1, ny+1, 1)
    assert grid.GetNumberOfCells() == nx * ny
    assert grid.GetOrigin() == tuple(meta["lower"] + [0])
    assert grid.GetSpacing() == tuple(meta["spacing"] + [1])
    fluid = grid.GetCellData().GetArray("fluid")
    assert {i for i in range(nx*ny) if fluid.GetTuple1(i) == 0} == set(meta["solid_indices"])
    # Testa também o índice temporal e o leitor de série, não apenas cada VTK.
    series = OpenDataFile(str(directory / "particles.vtk.series"))
    assert list(series.TimestepValues) == [f["time"] for f in frames]
    for frame in frames:
        series.UpdatePipeline(time=frame["time"])
        points = servermanager.Fetch(series)
        assert points.GetNumberOfPoints() == meta["particles"]
        assert points.GetPoint(0) == tuple(frame["positions"][0] + [0])
        for name in ("particle_id", "velocity", "speed", "particle_kinetic_energy"):
            assert points.GetPointData().GetArray(name) is not None, name
    Delete(series)
    print(f"ParaView: {len(frames)} quadros, tempos, geometria e todos os atributos validados.")


if __name__ == "__main__":
    validate(Path(sys.argv[1]), Path(sys.argv[2]))
