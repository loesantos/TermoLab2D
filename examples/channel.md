# Caixa dividida com canal — exemplo 2D

Na pasta `Molecular Dynamics 2D`, execute:

```bash
python3 visualize.py examples/channel.cfg
```

A geometria é `channel_box.vtk`, uma caixa de **40 × 20**, com duas câmaras
de **19 × 20**, separadas por uma parede central de espessura **2**.
O canal atravessa essa parede no centro, com **comprimento 2 e altura 4**.
Todas as medidas estão nas mesmas unidades reduzidas dos exemplos anteriores.

| Região | Coordenadas |
|---|---|
| Câmara esquerda | 0 ≤ x < 19; 0 ≤ y < 20 |
| Parede divisória | 19 ≤ x < 21, exceto na abertura |
| Canal livre | 19 ≤ x < 21; 8 ≤ y < 12 |
| Câmara direita | 21 ≤ x < 40; 0 ≤ y < 20 |

As **1.500 partículas começam na câmara esquerda**, com velocidades térmicas
aleatórias e temperatura inicial 1. O canal e a câmara direita começam vazios.
A parede permanece durante toda a simulação e reflete as partículas. A única
passagem entre as câmaras é o canal central, que está aberto desde t = 0.

A condição inicial usa:

```ini
initial_x_min = 0.0
initial_x_max = 0.475
```

O valor 0.475 corresponde a 19/40, ou seja, ao limite da câmara esquerda.
Para começar à direita, use `initial_x_min = 0.525` e `initial_x_max = 1.0`.
Para iniciar em toda a área livre, use 0 e 1.

O exemplo mantém a interação coulombiana dos exemplos anteriores. Os sólidos
são barreiras mecânicas; não blindam a interação eletrostática através da parede.
A temperatura não é mantida constante por termostato. Para partículas livres,
sem interação entre si, altere `charge = 0`.

São 20.000 passos de dt = 0.001, com um quadro a cada 40 passos. A simulação
mostra a passagem pelo canal, mas esse tempo não é uma garantia de equilíbrio
entre as câmaras. Aumente `steps` se quiser acompanhar a evolução por mais tempo.

Para gravar os quadros e salvar uma imagem ao encerrar:

```bash
python3 visualize.py examples/channel.cfg --record canal.jsonl --snapshot canal.png
```

Para executar sem janela:

```bash
python3 visualize.py examples/channel.cfg --headless --snapshot canal.png
```

O VTK tem 80 × 40 células, espaçamento 0.5 e máscara `CELL_DATA`: zero é sólido,
um é livre. Em índices de células começando por zero, a parede ocupa as colunas
38 a 41; a abertura ocupa as linhas 16 a 23. A ordem dos valores é x variando
mais rápido, depois y. A borda externa da caixa é fechada pelo simulador.

`channel_initial.png` e `channel_final.png` mostram uma execução verificada.
