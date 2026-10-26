#!/usr/bin/env python3
"""Gera uma máscara VTK ASCII 2D no plano xy: caixa livre ou obstáculo central."""
import argparse
from pathlib import Path
import math


def write_geometry(path, dims=(40, 32), spacing=0.5, obstacle=True):
    if len(dims) != 2 or min(dims) < 1 or not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("Informe duas dimensões positivas e espaçamento positivo e finito.")
    nx, ny = dims
    with Path(path).open("w", encoding="ascii") as out:
        out.write("# vtk DataFile Version 3.0\nMascara 2D: 0 solido, 1 fluido\nASCII\n")
        out.write(f"DATASET STRUCTURED_POINTS\nDIMENSIONS {nx+1} {ny+1} 1\n")
        out.write(f"ORIGIN 0 0 0\nSPACING {spacing} {spacing} 1\n")
        out.write(f"CELL_DATA {nx*ny}\nSCALARS fluid unsigned_char 1\nLOOKUP_TABLE default\n")
        for y in range(ny):
            row = []
            for x in range(nx):
                solid = obstacle and nx//3 <= x < 2*nx//3 and ny//3 <= y < 2*ny//3
                row.append("0" if solid else "1")
            out.write(" ".join(row) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--dims", nargs=2, type=int, default=(40, 32), metavar=("NX", "NY"))
    p.add_argument("--spacing", type=float, default=0.5)
    p.add_argument("--empty", action="store_true", help="Caixa sem obstáculo interno")
    args = p.parse_args()
    try:
        write_geometry(args.output, args.dims, args.spacing, not args.empty)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    print(f"Geometria 2D criada: {args.output}")


if __name__ == "__main__":
    main()
