#!/usr/bin/env python3
"""Exporta quadros 2D para VTK legacy ASCII e série temporal do ParaView."""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile


class VTKWriter:
    """Grava todos os quadros recebidos, independentemente da taxa de desenho."""
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        try:
            self.directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RuntimeError(f"A pasta VTK já existe: {self.directory}. Escolha uma nova pasta para esta execução.") from exc
        self.metadata = None
        self.entries = []
        self.last_step = -1

    def _write(self, name, callback):
        # Publica somente arquivos completos; a série anterior continua legível
        # se houver falha enquanto o quadro seguinte está sendo gravado.
        fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="ascii", newline="\n") as out:
                callback(out)
            os.replace(temporary, self.directory / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _series(self):
        def write(out):
            json.dump({"file-series-version": "1.0", "files": self.entries}, out,
                      indent=2, allow_nan=False)
            out.write("\n")
        self._write("particles.vtk.series", write)

    def write_metadata(self, metadata):
        if self.metadata is not None:
            raise ValueError("Metadados VTK repetidos.")
        if metadata.get("spatial_dimension") != 2:
            raise ValueError("A exportação requer metadados de uma simulação 2D.")
        nx, ny = metadata["dims"]
        x0, y0 = metadata["lower"]
        dx, dy = metadata["spacing"]
        if (not isinstance(nx, int) or not isinstance(ny, int) or min(nx, ny) < 1
                or not all(math.isfinite(x) for x in (x0, y0, dx, dy)) or min(dx, dy) <= 0):
            raise ValueError("Geometria inválida para exportação VTK.")
        if not math.isfinite(metadata["mass"]) or metadata["mass"] <= 0 or metadata["particles"] < 1:
            raise ValueError("Massa ou número de partículas inválido.")
        solid = set(metadata["solid_indices"])
        if any(not isinstance(i, int) or i < 0 or i >= nx * ny for i in solid):
            raise ValueError("Índice sólido inválido.")

        def write(out):
            out.write("# vtk DataFile Version 3.0\nSimulation geometry 2D: 0 solid, 1 fluid\nASCII\n")
            out.write(f"DATASET STRUCTURED_POINTS\nDIMENSIONS {nx+1} {ny+1} 1\n")
            out.write(f"ORIGIN {x0:.17g} {y0:.17g} 0\nSPACING {dx:.17g} {dy:.17g} 1\n")
            out.write(f"CELL_DATA {nx*ny}\nSCALARS fluid unsigned_char 1\nLOOKUP_TABLE default\n")
            for y in range(ny):
                out.write(" ".join("0" if x + nx*y in solid else "1" for x in range(nx)) + "\n")
        self._write("geometry.vtk", write)
        self.metadata = metadata
        self._series()

    def write_frame(self, frame):
        if self.metadata is None:
            raise ValueError("Quadro recebido antes dos metadados.")
        n = self.metadata["particles"]
        positions, velocities = frame["positions"], frame["velocities"]
        if len(positions) != n or len(velocities) != n:
            raise ValueError("Quantidade de partículas inconsistente no quadro.")
        if any(len(v) != 2 or not all(math.isfinite(c) for c in v) for v in positions + velocities):
            raise ValueError("Posições/velocidades devem ter duas componentes finitas.")
        step, time = frame["step"], frame["time"]
        if (not isinstance(step, int) or step <= self.last_step or not math.isfinite(time) or time < 0
                or (self.entries and time <= self.entries[-1]["time"])):
            raise ValueError("Passos e tempos devem ser finitos e estritamente crescentes.")
        diagnostics = [("TIME", time), ("temperature", frame["temperature"]),
                       ("kinetic_energy", frame["kinetic"]), ("potential_energy", frame["potential"]),
                       ("total_energy", frame["kinetic"] + frame["potential"])]
        speeds = [math.hypot(vx, vy) for vx, vy in velocities]
        energies = [0.5 * self.metadata["mass"] * v*v for v in speeds]
        if not all(math.isfinite(v) for _, v in diagnostics) or not all(math.isfinite(v) for v in speeds + energies):
            raise ValueError("Diagnósticos não finitos no quadro.")
        name = f"particles_{step:09d}.vtk"

        def write(out):
            out.write(f"# vtk DataFile Version 3.0\nParticles 2D - step {step}, time {time:.17g}\nASCII\nDATASET POLYDATA\n")
            out.write(f"POINTS {n} double\n")
            for x, y in positions:
                out.write(f"{x:.17g} {y:.17g} 0\n")
            out.write(f"VERTICES {n} {2*n}\n")
            for i in range(n):
                out.write(f"1 {i}\n")
            out.write(f"FIELD FieldData {len(diagnostics)+1}\n")
            out.write(f"step 1 1 int\n{step}\n")
            for field, value in diagnostics:
                out.write(f"{field} 1 1 double\n{value:.17g}\n")
            out.write(f"POINT_DATA {n}\nSCALARS particle_id int 1\nLOOKUP_TABLE default\n")
            for i in range(n):
                out.write(f"{i}\n")
            out.write("VECTORS velocity double\n")
            for vx, vy in velocities:
                out.write(f"{vx:.17g} {vy:.17g} 0\n")
            for field, values in (("speed", speeds), ("particle_kinetic_energy", energies)):
                out.write(f"SCALARS {field} double 1\nLOOKUP_TABLE default\n")
                for value in values:
                    out.write(f"{value:.17g}\n")
        self._write(name, write)
        self.entries.append({"name": name, "time": time})
        self._series()
        self.last_step = step


def main(argv=None):
    parser = argparse.ArgumentParser(description="Converte uma trajetória JSONL já gravada para arquivos VTK.")
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--vtk-dir", type=Path, required=True, help="Nova pasta de saída")
    args = parser.parse_args(argv)
    # Abre a entrada antes de criar a pasta para evitar diretórios em caso de erro de caminho.
    with args.trajectory.open(encoding="utf-8") as source:
        writer = VTKWriter(args.vtk_dir)
        for line in source:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("type") == "metadata":
                writer.write_metadata(item)
            elif item.get("type") == "frame":
                writer.write_frame(item)
            else:
                raise ValueError("Tipo de mensagem desconhecido na trajetória.")
        if not writer.entries:
            raise ValueError("A trajetória não contém quadros.")
    print(f"Exportados {len(writer.entries)} quadros: {writer.directory / 'particles.vtk.series'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nInterrompido; os quadros já gravados permanecem disponíveis.", file=sys.stderr)
        raise SystemExit(130)
