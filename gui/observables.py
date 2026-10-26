"""Grandezas calculadas a partir dos quadros do simulador.

Cada `Observable` declara o tipo de gráfico (série temporal, distribuição ou
perfil), as curvas que produz e — opcionalmente — as chaves que precisa no
quadro (`requires`). Grandezas cujas chaves o simulador ainda não emite
aparecem desabilitadas na interface. Para acrescentar uma grandeza, crie uma
subclasse e inclua-a em `OBSERVABLES`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geometry import Domain


@dataclass
class Context:
    meta: dict
    domain: Domain
    n: int
    kB: float
    mass: float
    initial_positions: np.ndarray | None = None
    initial: dict = field(default_factory=dict)   # valores em t=0 / estado por observável
    species: np.ndarray | None = None              # 0 = A, 1 = B (por partícula)
    masses: np.ndarray | None = None               # massa de cada partícula

    def __post_init__(self):
        if self.species is None:
            sp = self.meta.get("species")
            self.species = np.asarray(sp, dtype=int) if sp is not None else np.zeros(self.n, dtype=int)
        if self.masses is None:
            m = self.meta.get("masses", [self.mass, self.mass])
            self.masses = np.asarray(m, dtype=float)[self.species]

    @property
    def has_species(self) -> bool:
        return bool(self.species.any())


def _value(x) -> float:
    """Converte null (None) do JSON em NaN."""
    return float("nan") if x is None else float(x)


def local_temperature(vel: np.ndarray, masses: np.ndarray, kB: float) -> float:
    """T de um grupo de partículas, descontada a velocidade do centro de massa (2 graus de liberdade)."""
    n = len(vel)
    if n < 3:
        return float("nan")
    u = (masses[:, None] * vel).sum(0) / masses.sum()
    return float((masses * ((vel - u) ** 2).sum(1)).sum() / (2 * kB * (n - 1)))


class Smoother:
    """Média móvel exponencial no tempo (constante tau), guardada no contexto."""

    def __init__(self, tau: float):
        self.tau, self.value, self.t = tau, None, None

    def update(self, t: float, x: float) -> float:
        if not math.isfinite(x):
            return self.value if self.value is not None else float("nan")
        if self.value is None:
            self.value = x
        else:
            w = 1 - math.exp(-max(t - self.t, 0.0) / self.tau)
            self.value += w * (x - self.value)
        self.t = t
        return self.value


@dataclass
class Curve:
    name: str
    color: str
    style: str = "line"    # line | bars | dash


class Observable:
    id = ""
    title = ""
    kind = "series"        # series | distribution | profile
    xlabel = "t"
    ylabel = ""
    curves: list[Curve] = []
    requires: tuple[str, ...] = ()
    help = ""

    def available(self, frame_keys: set[str] | None) -> bool:
        return frame_keys is None or all(k in frame_keys for k in self.requires)

    def compute(self, frame: dict, pos: np.ndarray, vel: np.ndarray, ctx: Context):
        """Série: dict curva→valor. Distribuição/perfil: (x, dict curva→y)."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
class Temperature(Observable):
    id, title, ylabel = "temperature", "Temperatura", "T"
    curves = [Curve("T", "#d9480f")]
    help = "T = K/(N k_B), com dois graus de liberdade por partícula."

    def compute(self, frame, pos, vel, ctx):
        return {"T": frame["temperature"]}


class Energy(Observable):
    id, title, ylabel = "energy", "Energia por partícula", "E/N"
    curves = [Curve("cinética", "#d9480f"), Curve("potencial", "#1c7ed6"), Curve("total", "#212529")]
    help = "A energia total deve permanecer constante; desvios indicam dt grande demais."

    def compute(self, frame, pos, vel, ctx):
        k, u = frame["kinetic"] / ctx.n, frame["potential"] / ctx.n
        return {"cinética": k, "potencial": u, "total": k + u}


def _miller_madow(counts: np.ndarray, n: int) -> float:
    return (np.count_nonzero(counts) - 1) / (2.0 * n)


def coarse_bins(n: int, domain: Domain) -> tuple[int, int]:
    """Grade grossa com cerca de 20 partículas por célula."""
    target = max(4, n // 20)
    aspect = domain.size[0] / domain.size[1]
    bx = max(1, min(domain.nx, int(round(math.sqrt(target * aspect)))))
    by = max(1, min(domain.ny, int(round(target / bx))))
    return bx, by


def configurational_entropy(pos: np.ndarray, domain: Domain, bins: tuple[int, int] | None = None) -> float:
    """S_conf/(N k) = −Σ p_i ln(p_i / A_i) numa grade grossa (com correção de Miller–Madow).

    Para distribuição uniforme numa área A o resultado tende a ln A; restringir o gás
    a uma fração f da área reduz o valor em ln(1/f).
    """
    n = len(pos)
    bx, by = bins if bins is not None else coarse_bins(n, domain)
    area = domain.free_area_grid(bx, by)
    cells = np.floor((pos - domain.lower) / domain.spacing).astype(int)
    cx = np.clip(cells[:, 0], 0, domain.nx - 1) * bx // domain.nx
    cy = np.clip(cells[:, 1], 0, domain.ny - 1) * by // domain.ny
    counts = np.zeros((by, bx))
    np.add.at(counts, (cy, cx), 1)
    ok = counts > 0
    p = counts[ok] / n
    return float(-(p * np.log(p / area[ok])).sum() + _miller_madow(counts, n))


def velocity_entropy(vel: np.ndarray, nbins: int | None = None) -> float:
    """S_vel/(N k) = −∫ f ln f d²v estimada por histograma 2D.

    Para Maxwell–Boltzmann 2D o valor exato é 1 + ln(2π k T / m).
    """
    n = len(vel)
    if nbins is None:
        nbins = int(np.clip(math.sqrt(n / 5), 4, 30))
    sigma = float(np.sqrt((vel ** 2).mean() / 2)) or 1.0
    lim = 4.5 * sigma
    counts, ex, ey = np.histogram2d(vel[:, 0], vel[:, 1], bins=nbins, range=[[-lim, lim], [-lim, lim]])
    outside = n - counts.sum()
    h2 = (ex[1] - ex[0]) * (ey[1] - ey[0])
    ok = counts > 0
    p = counts[ok] / n
    s = -(p * np.log(p / h2)).sum() + _miller_madow(counts, n)
    if outside > 0:  # raro: partículas fora de ±4,5σ contam como uma célula extra
        q = outside / n
        s -= q * np.log(q / h2)
    return float(s)


class Entropy(Observable):
    id, title, ylabel = "entropy", "Variação de entropia por partícula", "ΔS/(N k)"
    curves = [Curve("configuracional", "#1c7ed6"), Curve("velocidades", "#d9480f"),
              Curve("total", "#212529")]
    help = ("Estimativa de Boltzmann em grade grossa: S = −k Σ p ln p (posições) + "
            "−k ∫ f ln f (velocidades), relativa ao instante inicial.")

    def compute(self, frame, pos, vel, ctx):
        sc = configurational_entropy(pos, ctx.domain)
        sv = velocity_entropy(vel)
        s0 = ctx.initial.setdefault(self.id, (sc, sv))
        dc, dv = sc - s0[0], sv - s0[1]
        return {"configuracional": dc, "velocidades": dv, "total": dc + dv}


class RightFraction(Observable):
    id, title, ylabel = "right_fraction", "Fração de partículas na metade direita", "N_dir/N"
    curves = [Curve("N_dir/N", "#2f9e44")]
    help = "Fração das partículas com x maior que o centro da caixa."

    def compute(self, frame, pos, vel, ctx):
        xc = ctx.domain.lower[0] + 0.5 * ctx.domain.size[0]
        return {"N_dir/N": float((pos[:, 0] > xc).mean())}


class TemperatureHalves(Observable):
    id, title, ylabel = "temperature_halves", "Temperatura em cada metade", "T"
    curves = [Curve("esquerda", "#1c7ed6"), Curve("direita", "#f76707")]
    help = ("Temperatura das partículas com x menor e maior que o centro da caixa, "
            "descontada a velocidade média (fluxo) de cada metade.")

    def compute(self, frame, pos, vel, ctx):
        xc = ctx.domain.lower[0] + 0.5 * ctx.domain.size[0]
        out = {}
        for name, mask in (("esquerda", pos[:, 0] <= xc), ("direita", pos[:, 0] > xc)):
            out[name] = local_temperature(vel[mask], ctx.masses[mask], ctx.kB)
        return out


def _running_profile(ctx: Context, key: str, y: np.ndarray, alpha: float = 0.15) -> np.ndarray:
    """Média móvel exponencial de um perfil, quadro a quadro (≈ últimos 1/alpha quadros)."""
    prev = ctx.initial.get(key)
    if prev is None or prev.shape != y.shape:
        avg = y.copy()
    else:
        avg = np.where(np.isfinite(prev), np.where(np.isfinite(y), prev + alpha * (y - prev), prev), y)
    ctx.initial[key] = avg
    return avg


def _column_bins(ctx: Context) -> int:
    return int(np.clip(min(ctx.domain.nx, ctx.n // 30), 4, 60))


def _column_index(pos: np.ndarray, domain: Domain, bins: int) -> np.ndarray:
    cells = np.clip(np.floor((pos[:, 0] - domain.lower[0]) / domain.spacing[0]).astype(int), 0, domain.nx - 1)
    return cells * bins // domain.nx


def _column_centers(domain: Domain, bins: int) -> np.ndarray:
    edges = domain.lower[0] + domain.spacing[0] * np.ceil(np.arange(bins + 1) * domain.nx / bins)
    edges[-1] = domain.upper[0]
    return 0.5 * (edges[1:] + edges[:-1])


class SpeedHistogram(Observable):
    id, title, kind = "speed_hist", "Distribuição de velocidades", "distribution"
    xlabel, ylabel = "|v|", "f(|v|)"
    curves = [Curve("simulação", "#74c0fc", "bars"), Curve("Maxwell–Boltzmann (T atual)", "#d9480f"),
              Curve("Maxwell–Boltzmann (T inicial)", "#868e96", "dash")]
    help = "Histograma de |v| comparado com f(v) = (v/σ²) exp(−v²/2σ²), σ² = kT/m."

    def compute(self, frame, pos, vel, ctx):
        speed = np.hypot(vel[:, 0], vel[:, 1])
        t_now = frame["temperature"]
        t0 = ctx.initial.setdefault(self.id, t_now)
        m_min = float(ctx.masses.min())
        s_max = 4.0 * math.sqrt(ctx.kB * max(t_now, t0) / m_min)
        if s_max <= 0:
            s_max = max(float(speed.max()), 1.0)
        nb = int(np.clip(math.sqrt(ctx.n), 10, 50))
        hist, edges = np.histogram(speed, bins=nb, range=(0, s_max), density=False)
        width = edges[1] - edges[0]
        x = 0.5 * (edges[1:] + edges[:-1])

        def rayleigh(t):
            out = np.zeros_like(x)
            for m in np.unique(ctx.masses):                   # mistura: soma ponderada por espécie
                s2 = ctx.kB * t / m
                if s2 > 0:
                    out += (ctx.masses == m).mean() * x / s2 * np.exp(-x ** 2 / (2 * s2))
            return out

        return x, {"simulação": hist / (ctx.n * width), "Maxwell–Boltzmann (T atual)": rayleigh(t_now),
                   "Maxwell–Boltzmann (T inicial)": rayleigh(t0)}


class DensityProfile(Observable):
    id, title, kind = "density_x", "Perfil de densidade", "profile"
    xlabel, ylabel = "x", "n(x)/n̄"
    curves = [Curve("instantâneo", "#a5d8ff", "bars"), Curve("média recente", "#1864ab")]
    help = ("Densidade em faixas verticais, normalizada pela densidade média N/A: valor do quadro "
            "atual e média móvel dos últimos ~7 quadros.")

    def compute(self, frame, pos, vel, ctx):
        bins = _column_bins(ctx)
        idx = _column_index(pos, ctx.domain, bins)
        counts = np.bincount(idx, minlength=bins).astype(float)
        area = ctx.domain.free_area_columns(bins)
        mean = ctx.n / ctx.domain.free_area
        with np.errstate(invalid="ignore", divide="ignore"):
            dens = np.where(area > 0, counts / area / mean, np.nan)
        return _column_centers(ctx.domain, bins), {"instantâneo": dens,
                                                   "média recente": _running_profile(ctx, self.id, dens)}


class TemperatureProfile(Observable):
    id, title, kind = "temperature_x", "Perfil de temperatura", "profile"
    xlabel, ylabel = "x", "T(x)"
    curves = [Curve("instantâneo", "#ffc9c9"), Curve("média recente", "#c92a2a")]
    help = ("Temperatura local em faixas verticais, descontada a velocidade média local: valor do "
            "quadro atual e média móvel dos últimos ~7 quadros.")

    def compute(self, frame, pos, vel, ctx):
        bins = _column_bins(ctx)
        idx = _column_index(pos, ctx.domain, bins)
        m = ctx.masses
        n = np.bincount(idx, minlength=bins).astype(float)
        mt = np.bincount(idx, m, bins)
        px = np.bincount(idx, m * vel[:, 0], bins)
        py = np.bincount(idx, m * vel[:, 1], bins)
        e2 = np.bincount(idx, m * (vel ** 2).sum(1), bins)
        with np.errstate(invalid="ignore", divide="ignore"):
            internal = e2 - (px ** 2 + py ** 2) / mt          # Σ m |v − u|²
            t = np.where(n >= 3, internal / (2 * ctx.kB * (n - 1)), np.nan)
        return _column_centers(ctx.domain, bins), {"instantâneo": t,
                                                   "média recente": _running_profile(ctx, self.id, t)}


def _gas_area(frame, ctx) -> float:
    return float(frame.get("area") or ctx.domain.free_area)


class Pressure(Observable):
    id, title, ylabel = "pressure", "Pressão", "P"
    curves = [Curve("P (média móvel)", "#7048e8"), Curve("P média acumulada", "#212529"),
              Curve("N k T / A", "#868e96", "dash")]
    requires = ("pressure",)
    help = ("Pressão mecânica: impulso transferido às paredes (ou ao pistão) por unidade de "
            "comprimento e de tempo. Comparada com o gás ideal, P = N k T / A.")

    def compute(self, frame, pos, vel, ctx):
        st = ctx.initial.setdefault(self.id, {"ema": Smoother(1.0), "sum": 0.0, "count": 0})
        p = _value(frame["pressure"])
        if math.isfinite(p):
            st["sum"] += p
            st["count"] += 1
        return {"P (média móvel)": st["ema"].update(frame["time"], p),
                "P média acumulada": st["sum"] / st["count"] if st["count"] else float("nan"),
                "N k T / A": ctx.n * ctx.kB * frame["temperature"] / _gas_area(frame, ctx)}


class Compressibility(Observable):
    id, title, ylabel = "compressibility", "Fator de compressibilidade", "Z = PA/(NkT)"
    curves = [Curve("Z", "#7048e8")]
    requires = ("pressure",)
    help = ("Z = ⟨P⟩A/(N k ⟨T⟩), com médias acumuladas. Z = 1 para o gás ideal; "
            "Z > 1 quando a repulsão (volume excluído) domina, Z < 1 quando a atração domina.")

    def compute(self, frame, pos, vel, ctx):
        st = ctx.initial.setdefault(self.id, {"p": 0.0, "t": 0.0, "n": 0})
        p = _value(frame["pressure"])
        if math.isfinite(p):
            st["p"] += p
            st["t"] += frame["temperature"]
            st["n"] += 1
        if not st["n"]:
            return {"Z": float("nan")}
        return {"Z": (st["p"] / st["n"]) * _gas_area(frame, ctx) / (ctx.n * ctx.kB * st["t"] / st["n"])}


class EnergyBalance(Observable):
    id, title, ylabel = "first_law", "Primeira lei: ΔE = Q + W", "energia / N"
    curves = [Curve("ΔE (energia interna)", "#212529"), Curve("Q (calor das paredes)", "#d9480f"),
              Curve("W (trabalho do pistão)", "#1c7ed6"), Curve("Q + W", "#868e96", "dash")]
    requires = ("wall_heat",)
    help = ("Variação da energia do gás comparada com o calor recebido das paredes térmicas "
            "e com o trabalho realizado pelo pistão, por partícula.")

    def compute(self, frame, pos, vel, ctx):
        e = (frame["kinetic"] + frame["potential"]) / ctx.n
        e0 = ctx.initial.setdefault(self.id, e)
        q = sum(frame.get("wall_heat") or [0.0]) / ctx.n
        piston = frame.get("piston")
        w = (piston or {}).get("work", 0.0) / ctx.n
        return {"ΔE (energia interna)": e - e0, "Q (calor das paredes)": q, "W (trabalho do pistão)": w,
                "Q + W": q + w}


class WallHeat(Observable):
    id, title, ylabel = "wall_heat", "Calor recebido de cada parede", "Q / N"
    curves = [Curve("esquerda", "#e03131"), Curve("direita", "#1971c2"),
              Curve("inferior", "#f08c00"), Curve("superior", "#2f9e44")]
    requires = ("wall_heat",)
    help = ("Energia acumulada que cada parede térmica entregou ao gás (negativa = o gás perdeu calor). "
            "No estado estacionário a parede quente entrega o que a fria retira.")

    def compute(self, frame, pos, vel, ctx):
        q = frame.get("wall_heat") or [0.0] * 4
        return {name: q[i] / ctx.n for i, name in enumerate(("esquerda", "direita", "inferior", "superior"))}


class BoltzmannH(Observable):
    id, title, ylabel = "h_function", "Função H de Boltzmann", "H = ∫ f ln f d²v"
    curves = [Curve("H", "#7048e8"), Curve("equilíbrio (Maxwell)", "#868e96", "dash")]
    help = ("H(t) = ∫ f ln f d²v, estimada pelo histograma 2D das velocidades. Pelo teorema H, "
            "H nunca cresce e tende a −[1 + ln(2π k T/m)] (distribuição de Maxwell–Boltzmann).")

    def compute(self, frame, pos, vel, ctx):
        h = -velocity_entropy(vel)
        t = frame["temperature"]
        m = float(ctx.masses.mean())
        eq = -(1 + math.log(2 * math.pi * ctx.kB * t / m)) if t > 0 else float("nan")
        return {"H": h, "equilíbrio (Maxwell)": eq}


class MixingEntropy(Observable):
    id, title, ylabel = "mixing_entropy", "Entropia de mistura", "ΔS/(N k)"
    curves = [Curve("distinguindo as espécies", "#e8590c"), Curve("sem distinguir (só posições)", "#1c7ed6"),
              Curve("mistura ideal: −Σ xᵢ ln xᵢ", "#868e96", "dash")]
    help = ("Entropia configuracional em grade grossa, contando as espécies separadamente (cores) "
            "ou não. A diferença final é a entropia de mistura; para espécies idênticas, ela "
            "é o “paradoxo de Gibbs”.")

    def compute(self, frame, pos, vel, ctx):
        bins = coarse_bins(len(pos), ctx.domain)
        both = configurational_entropy(pos, ctx.domain, bins)
        colored = 0.0
        n = len(pos)
        x_mix = 0.0
        for s in np.unique(ctx.species):
            mask = ctx.species == s
            x = mask.mean()
            # S_cor = Σ_s x_s [S_conf(espécie s) − ln x_s]
            colored += x * (configurational_entropy(pos[mask], ctx.domain, bins) - math.log(x))
            x_mix -= x * math.log(x)
        s0 = ctx.initial.setdefault(self.id, (colored, both))
        return {"distinguindo as espécies": colored - s0[0], "sem distinguir (só posições)": both - s0[1],
                "mistura ideal: −Σ xᵢ ln xᵢ": x_mix}


class SpeciesFractions(Observable):
    id, title, ylabel = "species_fractions", "Espécies do outro lado", "fração"
    curves = [Curve("A na metade direita", "#1c7ed6"), Curve("B na metade esquerda", "#f76707")]
    help = "Fração de cada espécie que atravessou para a metade oposta da caixa (½ = mistura completa)."

    def compute(self, frame, pos, vel, ctx):
        xc = ctx.domain.lower[0] + 0.5 * ctx.domain.size[0]
        a, b = ctx.species == 0, ctx.species == 1
        return {"A na metade direita": float((pos[a, 0] > xc).mean()) if a.any() else float("nan"),
                "B na metade esquerda": float((pos[b, 0] <= xc).mean()) if b.any() else float("nan")}


class CompressionTemperature(Observable):
    id, title, ylabel = "compression_T", "Temperatura na compressão", "T"
    curves = [Curve("T", "#d9480f"), Curve("adiabática ideal: T₀A₀/A", "#1c7ed6", "dash"),
              Curve("isotérmica: T₀", "#868e96", "dash")]
    requires = ("piston",)
    help = ("Temperatura do gás comparada com a adiabática reversível de um gás ideal monoatômico "
            "em 2D (γ = 2: T A = constante) e com a isotérmica.")

    def compute(self, frame, pos, vel, ctx):
        a = _gas_area(frame, ctx)
        t0, a0 = ctx.initial.setdefault(self.id, (frame["temperature"], a))
        return {"T": frame["temperature"], "adiabática ideal: T₀A₀/A": t0 * a0 / a, "isotérmica: T₀": t0}


class PVDiagram(Observable):
    id, title, kind = "pv_diagram", "Diagrama P × A", "distribution"
    xlabel, ylabel = "área A", "P"
    curves = [Curve("simulação", "#7048e8"), Curve("adiabática ideal: P A² = cte", "#1c7ed6", "dash"),
              Curve("isotérmica ideal: P A = cte", "#868e96", "dash")]
    requires = ("pressure", "piston")
    help = ("Caminho percorrido no plano pressão × área (o “diagrama PV” em 2D), com a pressão medida "
            "no pistão (média móvel). Curvas de referência partem do estado inicial ideal, P₀ = N k T₀/A₀.")

    def compute(self, frame, pos, vel, ctx):
        if self.id not in ctx.initial:
            piston = ctx.meta.get("piston") or {}
            duration = abs(piston.get("x1", 0) - piston.get("x0", 0)) / piston["speed"] if piston.get("speed") else 20.0
            ctx.initial[self.id] = {"ema": Smoother(float(np.clip(0.04 * duration, 1.0, 10.0))), "a": [], "p": []}
        st = ctx.initial[self.id]
        a = _gas_area(frame, ctx)
        if "a0" not in st:
            st["a0"], st["p0"] = a, ctx.n * ctx.kB * frame["temperature"] / a
        p = st["ema"].update(frame["time"], _value(frame["pressure"]))
        if math.isfinite(p):
            st["a"].append(a)
            st["p"].append(p)
        x = np.asarray(st["a"]) if st["a"] else np.array([a])
        y = np.asarray(st["p"]) if st["p"] else np.array([float("nan")])
        a0, p0 = st["a0"], st["p0"]
        return x, {"simulação": y, "adiabática ideal: P A² = cte": p0 * (a0 / x) ** 2,
                   "isotérmica ideal: P A = cte": p0 * a0 / x}


OBSERVABLES: list[Observable] = [
    Temperature(), TemperatureHalves(), Energy(), Entropy(), RightFraction(),
    SpeedHistogram(), DensityProfile(), TemperatureProfile(), Pressure(), Compressibility(),
    EnergyBalance(), WallHeat(), BoltzmannH(), MixingEntropy(), SpeciesFractions(),
    CompressionTemperature(), PVDiagram(),
]


def by_id(oid: str) -> Observable:
    for o in OBSERVABLES:
        if o.id == oid:
            return o
    raise KeyError(oid)


class DataStore:
    """Guarda as séries temporais e o último valor das distribuições/perfis."""

    def __init__(self, ctx: Context, frame_keys: set[str]):
        self.ctx = ctx
        self.active = [o for o in OBSERVABLES if o.available(frame_keys)]
        self.time: list[float] = []
        self.series: dict[str, dict[str, list[float]]] = {
            o.id: {c.name: [] for c in o.curves} for o in self.active if o.kind == "series"}
        self.latest: dict[str, tuple] = {}

    def add(self, frame: dict):
        pos = np.asarray(frame["positions"], dtype=float).reshape(-1, 2)
        vel = np.asarray(frame["velocities"], dtype=float).reshape(-1, 2)
        if self.ctx.initial_positions is None:
            self.ctx.initial_positions = pos.copy()
        self.time.append(frame["time"])
        for o in self.active:
            result = o.compute(frame, pos, vel, self.ctx)
            if o.kind == "series":
                for name, value in result.items():
                    self.series[o.id][name].append(value)
            else:
                self.latest[o.id] = result
        return pos, vel

    def to_csv(self, path):
        cols, header = [self.time], ["t"]
        for oid, curves in self.series.items():
            for name, values in curves.items():
                cols.append(values)
                header.append(f"{oid}:{name}")
        with open(path, "w", encoding="utf-8", newline="\n") as out:
            out.write(",".join(header) + "\n")
            for row in zip(*cols):
                out.write(",".join(f"{float(v):.10g}" for v in row) + "\n")
