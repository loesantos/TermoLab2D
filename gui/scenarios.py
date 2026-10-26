"""Catálogo de casos didáticos.

Para criar um caso novo basta acrescentar um `Scenario` à lista `SCENARIOS`:

* `params`  — parâmetros próprios do caso (aparecem no formulário "Caso");
* `defaults` — valores padrão dos parâmetros comuns (partículas, T, tempo…);
* `build(values, workdir)` — gera a geometria e devolve as chaves do .cfg;
* `references(values)` — valores teóricos desenhados como linhas tracejadas;
* `observables` — gráficos marcados ao escolher o caso;
* `available=False` + `requires` — caso planejado, mostrado desabilitado.

A interface monta o formulário e o arquivo .cfg automaticamente.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import geometry as geo

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


@dataclass
class Param:
    key: str
    label: str
    kind: str = "float"          # float | int | bool | choice
    default: Any = 0.0
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    decimals: int = 3
    unit: str = ""
    help: str = ""
    choices: list[tuple[str, Any]] | None = None  # (rótulo, valor)
    group: str = "Caso"
    # Mostra o campo só quando outro parâmetro tem um dos valores dados: ("potential", ("wca", "lj"))
    show_if: tuple[str, tuple] | None = None

    def visible(self, values: dict) -> bool:
        return self.show_if is None or values.get(self.show_if[0]) in self.show_if[1]


@dataclass
class Reference:
    """Valor teórico de um observável (linha horizontal tracejada)."""
    value: float
    label: str


@dataclass
class Scenario:
    id: str
    title: str
    category: str
    summary: str
    description: str = ""
    params: list[Param] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    observables: list[str] = field(default_factory=lambda: ["temperature", "energy"])
    color_mode: str = "speed"
    build: Callable[[dict, Path], dict] | None = None
    references: Callable[[dict], dict[str, list[Reference]]] | None = None
    available: bool = True
    requires: str = ""
    hidden: tuple[str, ...] = ()   # parâmetros comuns que o caso define sozinho (não aparecem no formulário)

    def all_params(self) -> list[Param]:
        return self.params + [p for p in COMMON_PARAMS if p.key not in self.hidden]


# ---------------------------------------------------------------------------
# Parâmetros comuns a todos os casos
# ---------------------------------------------------------------------------
POTENTIALS = [
    ("Discos macios (WCA) — gás quase ideal", "wca"),
    ("Lennard-Jones — repulsão + atração (gás real)", "lj"),
    ("Repulsão coulombiana (1/r, longo alcance)", "coulomb"),
    ("Sem interação — gás ideal sem colisões", "none"),
]
SHORT_RANGE = ("wca", "lj")

COMMON_PARAMS: list[Param] = [
    Param("particles", "Número de partículas", "int", 1500, 1, 200000, 50,
          help="Quantidade de partículas do gás.", group="Gás"),
    Param("temperature", "Temperatura inicial", "float", 1.0, 0.0, 100.0, 0.1, 3,
          help="Temperatura do gás em t = 0 (unidades reduzidas). Não há termostato depois disso.", group="Gás"),
    Param("potential", "Interação", "choice", "wca", choices=POTENTIALS, group="Gás",
          help="WCA: só repulsão de curto alcance (discos macios).\n"
               "Lennard-Jones: repulsão de curto alcance + atração.\n"
               "Coulomb: repulsão de longo alcance.\n"
               "Sem interação: as partículas só colidem com as paredes."),
    Param("sigma", "Diâmetro σ", "float", 0.2, 0.01, 5.0, 0.05, 3, group="Gás", show_if=("potential", SHORT_RANGE),
          help="Diâmetro efetivo das partículas (parâmetro σ do Lennard-Jones)."),
    Param("epsilon", "Energia ε", "float", 1.0, 0.0, 100.0, 0.1, 3, group="Gás", show_if=("potential", SHORT_RANGE),
          help="Escala de energia da interação; no Lennard-Jones é a profundidade do poço atrativo."),
    Param("charge", "Carga", "float", 1.0, 0.0, 10.0, 0.1, 3, group="Gás", show_if=("potential", ("coulomb",)),
          help="Carga de cada partícula (todas iguais: repulsão)."),
    Param("t_final", "Tempo de simulação", "float", 20.0, 0.001, 1e6, 1.0, 3,
          help="Tempo físico total a partir de t = 0 (unidades reduzidas). Passos = tempo / dt.", group="Gás"),
    Param("t_equil", "Tempo de equilibração inicial", "float", 5.0, 0.0, 1e4, 1.0, 2, group="Avançado",
          help="Antes de t = 0 o gás é equilibrado na região inicial (paredes temporárias e temperatura fixa).\n"
               "Isso elimina o transiente causado pelo sorteio das posições. 0 = sem equilibração."),
    Param("dt", "Passo de tempo dt", "float", 0.001, 1e-6, 0.1, 0.0005, 5, group="Avançado"),
    Param("output_every", "Passos entre quadros", "int", 40, 1, 100000, 10, group="Avançado",
          help="Um quadro é enviado à interface a cada N passos."),
    Param("lj_cutoff", "Corte do Lennard-Jones (× σ)", "float", 2.5, 1.2, 10.0, 0.5, 2, group="Avançado",
          show_if=("potential", ("lj",))),
    Param("cutoff", "Raio de corte (Coulomb)", "float", 3.0, 0.01, 100.0, 0.5, 3, group="Avançado",
          show_if=("potential", ("coulomb",))),
    Param("softening", "Suavização (Coulomb)", "float", 0.05, 0.0, 10.0, 0.01, 3, group="Avançado",
          show_if=("potential", ("coulomb",))),
    Param("mass", "Massa", "float", 1.0, 1e-6, 1e6, 0.1, 3, group="Avançado"),
    Param("seed", "Semente aleatória", "int", 42, 0, 2**31 - 1, 1, group="Avançado"),
    Param("threads", "Threads OpenMP (0 = auto)", "int", 0, 0, 256, 1, group="Avançado"),
]

FIXED_KEYS = {"boltzmann": 1.0, "coulomb_constant": 1.0}


def config_lines(scenario: Scenario, values: dict, workdir: Path) -> dict[str, Any]:
    """Monta o dicionário completo do .cfg a partir dos valores do formulário."""
    cfg: dict[str, Any] = dict(FIXED_KEYS)
    for key in ("particles", "temperature", "potential", "sigma", "epsilon", "lj_cutoff", "charge",
                "dt", "output_every", "cutoff", "softening", "mass", "seed", "threads"):
        cfg[key] = values[key]
    cfg["steps"] = max(0, int(round(values["t_final"] / values["dt"])))
    cfg["equilibration_steps"] = max(0, int(round(values["t_equil"] / values["dt"])))
    # Com potenciais de curto alcance, as partículas não começam sobrepostas:
    # distância mínima no mínimo do potencial WCA/LJ, 2^(1/6) σ.
    cfg["min_distance"] = 2 ** (1 / 6) * values["sigma"] if values["potential"] in SHORT_RANGE else 0.0
    if scenario.build is None:
        raise RuntimeError("Caso sem função de montagem.")
    cfg.update(scenario.build(values, workdir))
    return cfg


def write_config(scenario: Scenario, values: dict, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = config_lines(scenario, values, workdir)
    path = workdir / "simulacao.cfg"
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# Gerado pela interface — caso: {scenario.title}\n")
        for k, v in cfg.items():
            if k == "geometry":
                v = f'"{Path(v).as_posix()}"'
            out.write(f"{k} = {v}\n")
    return path


def default_values(scenario: Scenario) -> dict[str, Any]:
    vals = {p.key: p.default for p in scenario.params + COMMON_PARAMS}
    vals.update(scenario.defaults)
    return vals


# ---------------------------------------------------------------------------
# Casos disponíveis
# ---------------------------------------------------------------------------
def _box_params(width=40.0, height=20.0) -> list[Param]:
    return [
        Param("width", "Largura da caixa", "float", width, 2.0, 400.0, 1.0, 1),
        Param("height", "Altura da caixa", "float", height, 2.0, 400.0, 1.0, 1),
    ]


# 1. Expansão livre ----------------------------------------------------------
def _expansion_build(v: dict, wd: Path) -> dict:
    path = geo.write_vtk_mask(wd / "geometria.vtk", geo.box(v["width"], v["height"]), title="Expansao livre")
    return {"geometry": path, "initial_x_min": 0.0, "initial_x_max": v["fraction"]}


def _expansion_refs(v: dict) -> dict[str, list[Reference]]:
    f = v["fraction"]
    note = {"wca": "gás quase ideal: T ≈ constante", "none": "gás ideal: T constante",
            "lj": "a atração faz o gás esfriar", "coulomb": "a repulsão faz o gás esquentar"}[v["potential"]]
    return {
        "entropy": [Reference(math.log(1 / f), f"ΔS/Nk = ln(1/{f:g}) (gás ideal)")],
        "right_fraction": [Reference(0.5, "equilíbrio: 1/2")],
        "temperature": [Reference(v["temperature"], f"T inicial — {note}")],
    }


EXPANSION = Scenario(
    id="expansion",
    title="Expansão livre (Joule)",
    category="Processos irreversíveis",
    summary="O gás começa confinado em parte da caixa e se expande para o vácuo.",
    description="""
<p>O gás é equilibrado numa faixa à esquerda da caixa (fração <i>f</i> da
largura), contido por uma parede temporária. Em <i>t</i> = 0 a parede é
retirada e o gás se expande para o vácuo, sem realizar trabalho e sem trocar
calor: a energia interna se conserva.</p>
<p><b>O que observar</b></p>
<ul>
<li>A entropia configuracional cresce e se aproxima de
<i>ΔS/Nk</i> = ln(1/<i>f</i>) — para <i>f</i> = ½, ln 2 ≈ 0,693.</li>
<li>A temperatura depende da interação (troque em “Interação” e compare):
<ul>
<li><b>WCA</b> ou <b>sem interação</b>: <i>T</i> praticamente constante — gás ideal.</li>
<li><b>Lennard-Jones</b>: o gás <b>esfria</b>; afastar as partículas contra a
atração consome energia cinética.</li>
<li><b>Coulomb</b>: o gás <b>esquenta</b>; a repulsão acumulada vira energia cinética.</li>
</ul>
É o sinal de (∂<i>T</i>/∂<i>V</i>)<sub><i>U</i></sub> para gases reais.</li>
<li>O processo nunca se inverte espontaneamente: ilustração da segunda lei.</li>
</ul>""",
    params=_box_params() + [
        Param("fraction", "Fração inicialmente ocupada", "float", 0.5, 0.05, 1.0, 0.05, 2,
              help="Fração da largura da caixa ocupada em t = 0 (a partir da esquerda)."),
    ],
    defaults={"t_final": 50.0},
    observables=["temperature", "temperature_halves", "entropy", "right_fraction"],
    color_mode="initial_side",
    build=_expansion_build,
    references=_expansion_refs,
)


# 2. Efusão por um canal -----------------------------------------------------
def _channel_build(v: dict, wd: Path) -> dict:
    fluid = geo.divided_box(v["width"], v["height"], v["wall"], v["opening"])
    path = geo.write_vtk_mask(wd / "geometria.vtk", fluid, title="Caixa com canal")
    nx = fluid.shape[1]
    wall_start = (nx - max(1, round(v["wall"] / 0.5))) // 2
    return {"geometry": path, "initial_x_min": 0.0, "initial_x_max": wall_start / nx}


CHANNEL = Scenario(
    id="channel",
    title="Efusão através de um canal",
    category="Processos irreversíveis",
    summary="Duas câmaras ligadas por uma abertura; o gás começa todo à esquerda.",
    description="""
<p>Uma parede central separa a caixa em duas câmaras; a única passagem é um
canal de altura ajustável. Todas as partículas começam na câmara esquerda.</p>
<p><b>O que observar</b></p>
<ul>
<li>Há duas escalas de tempo. Primeiro a <b>pressão</b> se equilibra (rápido):
o gás da esquerda se expande e <b>esfria</b>; o jato que entra na direita é
freado e a câmara direita <b>esquenta</b>. Com <i>n k T</i> igual dos dois
lados, a câmara quente fica com menos partículas.</li>
<li>Depois a <b>temperatura</b> se iguala devagar, por condução de calor
através do canal; só então <i>N</i><sub>dir</sub>/<i>N</i> → ½ e a entropia
configuracional → ln 2. Aumente o tempo de simulação para acompanhar.</li>
<li>Sem interação (sem colisões) é a efusão de Knudsen: as partículas mais
rápidas atravessam primeiro, e a câmara direita também começa mais quente.</li>
<li>Compare canais de alturas diferentes: o tempo característico cresce quando
o canal diminui.</li>
</ul>""",
    params=_box_params() + [
        Param("opening", "Altura do canal", "float", 6.0, 0.0, 400.0, 0.5, 1,
              help="0 fecha a passagem; múltiplos de 0,5."),
        Param("wall", "Espessura da parede", "float", 2.0, 0.5, 50.0, 0.5, 1),
    ],
    defaults={"t_final": 150.0, "output_every": 100},
    observables=["right_fraction", "temperature_halves", "entropy", "density_x"],
    color_mode="initial_side",
    build=_channel_build,
    references=lambda v: {"right_fraction": [Reference(0.5, "equilíbrio final: 1/2")],
                          "temperature_halves": [Reference(v["temperature"], "T inicial")],
                          "entropy": [Reference(math.log(2), "ln 2")]},
)


# 3. Gás em equilíbrio numa caixa com obstáculo --------------------------------
def _obstacle_build(v: dict, wd: Path) -> dict:
    fluid = geo.box_with_obstacle(v["width"], v["height"], v["obstacle"])
    path = geo.write_vtk_mask(wd / "geometria.vtk", fluid, title="Caixa com obstaculo")
    return {"geometry": path, "initial_x_min": 0.0, "initial_x_max": 1.0}


EQUILIBRIUM = Scenario(
    id="equilibrium",
    title="Gás em equilíbrio",
    category="Equilíbrio",
    summary="Gás numa caixa (com obstáculo opcional) — distribuição de velocidades.",
    description="""
<p>O gás é distribuído uniformemente em toda a área livre, com velocidades
sorteadas da distribuição de Maxwell–Boltzmann.</p>
<p><b>O que observar</b></p>
<ul>
<li>O histograma de |<b>v</b>| segue a distribuição de Maxwell–Boltzmann 2D,
<i>f</i>(<i>v</i>) = (<i>v</i>/σ²) exp(−<i>v</i>²/2σ²), com σ² = <i>kT/m</i>.</li>
<li>Com “sem interação”, as partículas nunca colidem entre si: cada uma
conserva sua velocidade e a distribuição inicial nunca muda.</li>
<li>No equilíbrio, a temperatura flutua em torno de um valor constante; as
flutuações diminuem com o número de partículas (∝ 1/√N).</li>
<li>A energia total deve se conservar: use isso para escolher <i>dt</i>.</li>
</ul>""",
    params=_box_params(20.0, 16.0) + [
        Param("obstacle", "Tamanho do obstáculo", "float", 1 / 3, 0.0, 0.9, 0.05, 2,
              help="Fração de cada lado da caixa ocupada pelo obstáculo central (0 = sem obstáculo)."),
    ],
    defaults={"particles": 400, "t_final": 10.0, "output_every": 20},
    observables=["speed_hist", "temperature", "energy"],
    build=_obstacle_build,
)


# 4. Personalizado -----------------------------------------------------------
def _custom_build(v: dict, wd: Path) -> dict:
    path = Path(v["geometry_file"]).expanduser()
    if not path.is_file():
        raise RuntimeError(f"Arquivo de geometria não encontrado: {path}")
    if not v["x_min"] < v["x_max"]:
        raise RuntimeError("A faixa inicial requer início < fim.")
    return {"geometry": path.resolve(), "initial_x_min": v["x_min"], "initial_x_max": v["x_max"]}


CUSTOM = Scenario(
    id="custom",
    title="Personalizado (geometria VTK)",
    category="Livre",
    summary="Escolha qualquer máscara VTK 2D e a faixa inicial ocupada.",
    description="""
<p>Use uma geometria VTK legacy ASCII (STRUCTURED_POINTS, 0 = sólido,
≠ 0 = livre) e escolha a faixa da caixa ocupada em <i>t</i> = 0, como fração
da largura.</p>""",
    params=[
        Param("geometry_file", "Geometria (.vtk)", "file", str(EXAMPLES / "geometry.vtk")),
        Param("x_min", "Faixa inicial: início", "float", 0.0, 0.0, 1.0, 0.05, 3),
        Param("x_max", "Faixa inicial: fim", "float", 1.0, 0.0, 1.0, 0.05, 3),
    ],
    observables=["temperature", "energy", "speed_hist"],
    build=_custom_build,
)


# 5. Condução de calor entre paredes a temperaturas diferentes ---------------
def _box_build(v: dict, wd: Path, title: str) -> dict:
    path = geo.write_vtk_mask(wd / "geometria.vtk", geo.box(v["width"], v["height"]), title=title)
    return {"geometry": path, "initial_x_min": 0.0, "initial_x_max": 1.0}


def _conduction_build(v: dict, wd: Path) -> dict:
    cfg = _box_build(v, wd, "Conducao de calor")
    cfg.update(wall_temperature_left=v["t_hot"], wall_temperature_right=v["t_cold"])
    return cfg


CONDUCTION = Scenario(
    id="conduction",
    title="Condução de calor entre paredes",
    category="Transporte de calor",
    summary="Parede esquerda quente, direita fria; perfil T(x) e fluxo de calor.",
    description="""
<p>As paredes esquerda e direita são <b>térmicas</b>: uma partícula que as atinge
volta com velocidade sorteada na temperatura da parede (parede difusiva). As
paredes de cima e de baixo são isolantes (reflexão especular).</p>
<p><b>O que observar</b></p>
<ul>
<li>O perfil <i>T</i>(<i>x</i>) evolui até um estado estacionário com gradiente
de temperatura entre as paredes; perto de cada parede há um “salto” de
temperatura (efeito de rarefação).</li>
<li>No estado estacionário, o calor que entra pela parede quente é igual ao que sai
pela fria: as curvas de calor acumulado ficam paralelas e opostas; a inclinação é
o fluxo de calor.</li>
<li>A densidade fica maior do lado frio: a pressão (∝ <i>n T</i>) é uniforme.</li>
<li>Com “sem interação” não há colisões entre partículas e o calor passa direto de
uma parede à outra (regime balístico): compare o perfil.</li>
</ul>""",
    params=_box_params() + [
        Param("t_hot", "Temperatura da parede esquerda", "float", 2.0, 0.01, 100.0, 0.1, 3),
        Param("t_cold", "Temperatura da parede direita", "float", 0.5, 0.01, 100.0, 0.1, 3),
    ],
    defaults={"t_final": 200.0, "output_every": 200},
    observables=["temperature_x", "wall_heat", "density_x", "temperature_halves"],
    build=_conduction_build,
    references=lambda v: {"temperature_x": [Reference(v["t_hot"], "parede quente"),
                                            Reference(v["t_cold"], "parede fria")],
                          "temperature_halves": [Reference(v["t_hot"], "parede quente"),
                                                 Reference(v["t_cold"], "parede fria")]},
)


# 6. Gás frio aquecido pelas paredes -------------------------------------------
def _heating_build(v: dict, wd: Path) -> dict:
    cfg = _box_build(v, wd, "Aquecimento pelas paredes")
    for side in ("left", "right", "bottom", "top"):
        cfg[f"wall_temperature_{side}"] = v["t_wall"]
    return cfg


HEATING = Scenario(
    id="heating",
    title="Aquecimento de um gás pelas paredes",
    category="Transporte de calor",
    summary="Gás frio numa caixa cujas quatro paredes estão quentes.",
    description="""
<p>As quatro paredes são térmicas, à temperatura <i>T</i><sub>p</sub>; o gás
começa mais frio (ou mais quente, se preferir). Não há trabalho: toda a energia
trocada é calor.</p>
<p><b>O que observar</b></p>
<ul>
<li>A temperatura do gás se aproxima de <i>T</i><sub>p</sub> aproximadamente
de forma exponencial (lei do resfriamento de Newton).</li>
<li>O perfil <i>T</i>(<i>x</i>) mostra que o gás esquenta primeiro junto às
paredes; o calor se difunde para o centro.</li>
<li>Primeira lei: a variação de energia do gás é igual ao calor recebido
(Δ<i>E</i> = <i>Q</i>).</li>
</ul>""",
    params=_box_params() + [
        Param("t_wall", "Temperatura das paredes", "float", 2.0, 0.01, 100.0, 0.1, 3),
    ],
    defaults={"temperature": 0.3, "t_final": 60.0, "output_every": 50},
    observables=["temperature", "temperature_x", "first_law"],
    build=_heating_build,
    references=lambda v: {"temperature": [Reference(v["t_wall"], "temperatura das paredes")],
                          "temperature_x": [Reference(v["t_wall"], "paredes")]},
)


# 7. Relaxação para Maxwell–Boltzmann (teorema H) -----------------------------
def _h_build(v: dict, wd: Path) -> dict:
    cfg = _box_build(v, wd, "Teorema H")
    cfg["velocity_distribution"] = "mono"
    return cfg


H_THEOREM = Scenario(
    id="h_theorem",
    title="Relaxação para Maxwell (teorema H)",
    category="Processos irreversíveis",
    summary="Todas as partículas com a mesma velocidade; a distribuição relaxa.",
    description="""
<p>Em <i>t</i> = 0 todas as partículas têm o <b>mesmo módulo de velocidade</b>,
|<b>v</b>| = √(2<i>kT/m</i>), em direções aleatórias. As posições já estão
equilibradas.</p>
<p><b>O que observar</b></p>
<ul>
<li>O histograma de velocidades, que começa como um pico estreito, se alarga
até a distribuição de Maxwell–Boltzmann em poucos tempos de colisão.</li>
<li>A função <i>H</i> de Boltzmann, <i>H</i> = ∫ <i>f</i> ln <i>f</i> d²<i>v</i>,
diminui (teorema <i>H</i>) até o valor de equilíbrio, enquanto a energia (e
<i>T</i>) se conserva.</li>
<li>Com “sem interação” não há colisões: a distribuição <b>não</b> relaxa.
São as colisões que produzem a irreversibilidade.</li>
<li>Diminua a densidade (menos partículas ou σ menor): o tempo de relaxação
aumenta com o livre caminho médio.</li>
</ul>""",
    params=_box_params(),
    defaults={"t_final": 15.0, "output_every": 10, "t_equil": 3.0},
    observables=["speed_hist", "h_function", "temperature"],
    build=_h_build,
)


# 8. Mistura de dois gases -----------------------------------------------------
def _mixing_build(v: dict, wd: Path) -> dict:
    cfg = _box_build(v, wd, "Mistura de dois gases")
    identical = v["identical"]
    sigma_b = v["sigma"] if identical else v["sigma"] * v["size_ratio"]
    cfg.update(particles=v["n_each"], particles_b=v["n_each"],
               initial_x_min=0.0, initial_x_max=0.5, initial_b_x_min=0.5, initial_b_x_max=1.0,
               mass_b=v["mass"] if identical else v["mass"] * v["mass_ratio"], sigma_b=sigma_b)
    if v["potential"] in SHORT_RANGE:
        cfg["min_distance"] = 2 ** (1 / 6) * max(v["sigma"], sigma_b)
    return cfg


MIXING = Scenario(
    id="mixing",
    title="Mistura de dois gases",
    category="Processos irreversíveis",
    summary="Duas espécies separadas por uma divisória que é removida.",
    description="""
<p>A espécie A (azul) é equilibrada na metade esquerda e a espécie B (laranja)
na metade direita, separadas por uma divisória. Em <i>t</i> = 0 a divisória é
retirada e as espécies se difundem uma na outra.</p>
<p><b>O que observar</b></p>
<ul>
<li>A entropia calculada <b>distinguindo as espécies</b> cresce até a entropia de
mistura ideal, −Σ <i>x</i><sub>i</sub> ln <i>x</i><sub>i</sub> = ln 2 por
partícula para quantidades iguais. A entropia calculada só com as posições (sem
distinguir as cores) praticamente não muda: a densidade já era uniforme.</li>
<li><b>Paradoxo de Gibbs</b>: marque “espécies idênticas”. A dinâmica é a mesma
de um único gás, mas se as cores forem distinguíveis a “mistura” ainda produz
ln 2 — a entropia de mistura depende de considerarmos as partículas distinguíveis.</li>
<li>A mistura é difusiva e lenta: o tempo cresce com o quadrado do tamanho da
caixa. Partículas mais leves (razão de massas &lt; 1) difundem mais rápido.</li>
</ul>""",
    params=_box_params(20.0, 20.0) + [
        Param("n_each", "Partículas de cada espécie", "int", 400, 1, 100000, 50),
        Param("identical", "Espécies idênticas (paradoxo de Gibbs)", "bool", False),
        Param("mass_ratio", "Massa de B / massa de A", "float", 1.0, 0.01, 100.0, 0.5, 2,
              show_if=("identical", (False,))),
        Param("size_ratio", "Diâmetro de B / diâmetro de A", "float", 1.0, 0.1, 10.0, 0.25, 2,
              show_if=("identical", (False,)), help="Só tem efeito com WCA ou Lennard-Jones."),
    ],
    hidden=("particles",),
    defaults={"t_final": 100.0, "output_every": 100},
    observables=["mixing_entropy", "species_fractions", "density_x"],
    color_mode="species",
    build=_mixing_build,
)


# 9. Compressão por pistão -------------------------------------------------------
PISTON_START = 2.0


def _piston_build(v: dict, wd: Path) -> dict:
    cfg = _box_build(v, wd, "Pistao")
    x0, x1 = v["piston_from"], v["piston_to"]
    if abs(x1 - x0) < 1e-9:
        raise RuntimeError("As posições inicial e final do pistão devem ser diferentes.")
    cfg.update(initial_x_max=x0, piston_x0=x0, piston_x1=x1, piston_speed=v["piston_speed"],
               piston_start=PISTON_START)
    if v["walls"] == "isothermal":
        for side in ("left", "bottom", "top"):
            cfg[f"wall_temperature_{side}"] = v["temperature"]
    # Pistão rápido acelera partículas (v' = 2u − v a cada choque): reduz dt para que
    # uma partícula não avance mais que ~5% de σ por passo em colisões entre si.
    dt = v["dt"]
    if v["potential"] in SHORT_RANGE:
        v_typ = 3 * math.sqrt(max(v["temperature"], 1e-12) / v["mass"]) + 2 * v["piston_speed"]
        dt = min(dt, 0.05 * v["sigma"] / v_typ)
    frame_interval = v["output_every"] * v["dt"]
    # o tempo de simulação cobre todo o movimento do pistão e mais 5 unidades
    needed = PISTON_START + abs(x1 - x0) * v["width"] / v["piston_speed"] + 5.0
    cfg.update(dt=dt, steps=int(round(max(v["t_final"], needed) / dt)),
               output_every=max(1, int(round(frame_interval / dt))),
               equilibration_steps=max(0, int(round(v["t_equil"] / dt))))
    return cfg


PISTON = Scenario(
    id="piston",
    title="Compressão por pistão",
    category="Termodinâmica",
    summary="Uma parede móvel comprime (ou expande) o gás; adiabática × isotérmica.",
    description=f"""
<p>A parede da direita é um <b>pistão</b> que se move com velocidade constante a
partir de <i>t</i> = {PISTON_START:g}, da posição inicial até a final (frações da
largura). As colisões com o pistão são elásticas no referencial do pistão: o gás
recebe (ou perde) energia na forma de trabalho.</p>
<p><b>O que observar</b></p>
<ul>
<li><b>Paredes isolantes</b>: compressão adiabática. Lenta (quase-estática), segue
a adiabática do gás ideal monoatômico em 2D, <i>T A</i> = constante e
<i>P A</i>² = constante (γ = 2). Rápida, o gás esquenta <b>mais</b>: o
processo é irreversível e o trabalho é maior.</li>
<li><b>Paredes térmicas</b> (à temperatura inicial): compressão aproximadamente
isotérmica se for lenta; o calor sai pelas paredes (<i>Q</i> &lt; 0). Para o gás
ideal, o trabalho isotérmico é <i>W</i>/<i>N</i> = <i>kT</i> ln(<i>A</i>₀/<i>A</i>)
— ln 2 ≈ 0,69 <i>kT</i> ao reduzir a área à metade.</li>
<li>Primeira lei: Δ<i>E</i> = <i>Q</i> + <i>W</i> em todos os casos.</li>
<li>Posição final maior que a inicial produz uma expansão: o gás esfria.</li>
<li>O tempo de simulação é estendido automaticamente até o fim do movimento; com
pistão rápido o passo <i>dt</i> é reduzido automaticamente.</li>
</ul>""",
    params=_box_params() + [
        Param("piston_from", "Posição inicial do pistão", "float", 1.0, 0.05, 1.0, 0.05, 2,
              help="Fração da largura da caixa."),
        Param("piston_to", "Posição final do pistão", "float", 0.5, 0.05, 1.0, 0.05, 2,
              help="Fração da largura da caixa (menor que a inicial = compressão)."),
        Param("piston_speed", "Velocidade do pistão", "float", 0.1, 0.001, 10.0, 0.05, 3,
              help="Compare 0,05 (lenta, ~quase-estática) com 1 ou mais (rápida, irreversível). "
                   "A velocidade térmica típica é √(kT/m)."),
        Param("walls", "Paredes fixas", "choice", "adiabatic",
              choices=[("Isolantes (adiabática)", "adiabatic"), ("Térmicas à T inicial (isotérmica)", "isothermal")]),
    ],
    defaults={"sigma": 0.1, "t_final": 5.0, "output_every": 100},
    observables=["compression_T", "pv_diagram", "first_law"],
    build=_piston_build,
)


# 10. Lei dos gases ideais --------------------------------------------------------
IDEAL_GAS = Scenario(
    id="ideal_gas",
    title="Lei dos gases ideais",
    category="Equilíbrio",
    summary="Pressão medida nas paredes; verificação de P A = N k T.",
    description="""
<p>A pressão é medida como em um gás real: o impulso que as partículas transferem
às paredes, por unidade de comprimento e de tempo. Em 2D a equação de estado do
gás ideal é <i>P A</i> = <i>N k T</i>.</p>
<p><b>O que observar</b></p>
<ul>
<li>A pressão instantânea flutua muito; a média acumulada converge.</li>
<li>Varie <i>N</i>, <i>T</i> e o tamanho da caixa e compare com <i>N k T</i>/<i>A</i>.</li>
<li>O fator de compressibilidade <i>Z</i> = <i>PA</i>/(<i>NkT</i>) mostra o desvio
do gás ideal: <i>Z</i> = 1 sem interação; <i>Z</i> &gt; 1 com WCA (área excluída
pelas partículas — aumente σ para ver); com Lennard-Jones a atração reduz <i>Z</i>.</li>
</ul>""",
    params=_box_params(20.0, 20.0),
    defaults={"particles": 2000, "sigma": 0.1, "t_final": 30.0, "output_every": 50},
    observables=["pressure", "compressibility", "temperature"],
    build=lambda v, wd: _box_build(v, wd, "Gas ideal"),
    references=lambda v: {"compressibility": [Reference(1.0, "gás ideal: Z = 1")]},
)


SCENARIOS: list[Scenario] = [EXPANSION, CHANNEL, H_THEOREM, MIXING, EQUILIBRIUM, IDEAL_GAS,
                             CONDUCTION, HEATING, PISTON, CUSTOM]


def by_id(scenario_id: str) -> Scenario:
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    raise KeyError(scenario_id)
