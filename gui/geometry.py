"""Geometrias 2D: geração de máscaras VTK e leitura da máscara pelos metadados.

A máscara segue a convenção do simulador: célula com valor 0 é sólida,
valor não nulo é livre; índice = x + nx*y (x varia mais rápido).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


def write_vtk_mask(path: Path, fluid: np.ndarray, spacing: float = 0.5,
                   origin: tuple[float, float] = (0.0, 0.0), title: str = "Mascara 2D") -> Path:
    """Grava `fluid[ny, nx]` (True = livre) como VTK legacy ASCII com CELL_DATA."""
    fluid = np.asarray(fluid, dtype=bool)
    if fluid.ndim != 2 or min(fluid.shape) < 1:
        raise ValueError("A máscara deve ser uma matriz 2D não vazia.")
    if not np.isfinite(spacing) or spacing <= 0:
        raise ValueError("O espaçamento deve ser positivo e finito.")
    if not fluid.any():
        raise ValueError("A geometria não tem área livre.")
    ny, nx = fluid.shape
    path = Path(path)
    with path.open("w", encoding="ascii", newline="\n") as out:
        out.write(f"# vtk DataFile Version 3.0\n{title} (0 solido, 1 livre)\nASCII\n")
        out.write(f"DATASET STRUCTURED_POINTS\nDIMENSIONS {nx + 1} {ny + 1} 1\n")
        out.write(f"ORIGIN {origin[0]} {origin[1]} 0\nSPACING {spacing} {spacing} 1\n")
        out.write(f"CELL_DATA {nx * ny}\nSCALARS fluid unsigned_char 1\nLOOKUP_TABLE default\n")
        for row in fluid:
            out.write(" ".join("1" if v else "0" for v in row) + "\n")
    return path


def box(width: float, height: float, spacing: float = 0.5) -> np.ndarray:
    """Caixa vazia (as paredes externas são impostas pelo simulador)."""
    nx, ny = _cells(width, spacing), _cells(height, spacing)
    return np.ones((ny, nx), dtype=bool)


def divided_box(width: float, height: float, wall_thickness: float, opening: float,
                spacing: float = 0.5) -> np.ndarray:
    """Caixa com parede vertical central e uma abertura centrada em y.

    `opening = 0` fecha a parede; `opening >= height` remove a parede.
    """
    fluid = box(width, height, spacing)
    ny, nx = fluid.shape
    t = max(1, _cells(wall_thickness, spacing))
    x0 = (nx - t) // 2
    fluid[:, x0:x0 + t] = False
    h = int(round(opening / spacing))
    if h > 0:
        y0 = max(0, (ny - h) // 2)
        fluid[y0:y0 + h, x0:x0 + t] = True
    return fluid


def box_with_obstacle(width: float, height: float, obstacle_fraction: float = 1 / 3,
                      spacing: float = 0.5) -> np.ndarray:
    """Caixa com obstáculo retangular central ocupando `obstacle_fraction` de cada lado."""
    fluid = box(width, height, spacing)
    ny, nx = fluid.shape
    fx, fy = int(round(nx * obstacle_fraction)), int(round(ny * obstacle_fraction))
    if fx > 0 and fy > 0:
        x0, y0 = (nx - fx) // 2, (ny - fy) // 2
        fluid[y0:y0 + fy, x0:x0 + fx] = False
    return fluid


def _cells(length: float, spacing: float) -> int:
    n = int(round(length / spacing))
    if n < 1:
        raise ValueError("Dimensão menor que uma célula.")
    return n


@dataclass
class Domain:
    """Domínio reconstruído a partir dos metadados emitidos pelo simulador."""
    nx: int
    ny: int
    lower: np.ndarray
    spacing: np.ndarray
    fluid: np.ndarray  # [ny, nx] booleano

    @classmethod
    def from_metadata(cls, meta: dict) -> "Domain":
        nx, ny = (int(v) for v in meta["dims"])
        fluid = np.ones(nx * ny, dtype=bool)
        fluid[np.asarray(meta.get("solid_indices", []), dtype=int)] = False
        return cls(nx, ny, np.asarray(meta["lower"], float), np.asarray(meta["spacing"], float),
                   fluid.reshape(ny, nx))

    @property
    def size(self) -> np.ndarray:
        return np.array([self.nx, self.ny]) * self.spacing

    @property
    def upper(self) -> np.ndarray:
        return self.lower + self.size

    @property
    def free_area(self) -> float:
        return float(self.fluid.sum() * self.spacing.prod())

    def free_area_grid(self, bx: int, by: int) -> np.ndarray:
        """Área livre em cada célula de uma grade grossa bx × by (retorna [by, bx])."""
        cx = np.minimum((np.arange(self.nx) * bx) // self.nx, bx - 1)
        cy = np.minimum((np.arange(self.ny) * by) // self.ny, by - 1)
        area = np.zeros((by, bx))
        np.add.at(area, (cy[:, None].repeat(self.nx, 1), cx[None, :].repeat(self.ny, 0)),
                  self.fluid.astype(float))
        return area * self.spacing.prod()

    def free_area_columns(self, bins: int) -> np.ndarray:
        return self.free_area_grid(bins, 1)[0]
