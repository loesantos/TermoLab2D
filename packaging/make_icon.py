#!/usr/bin/env python3
"""Gera o ícone do TermoLab2D: gui/icone.png (256 px) e packaging/windows/icone.ico."""
from pathlib import Path
import random
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent


def draw(size: int) -> Image.Image:
    s = 4 * size                                   # desenha grande e reduz (antisserrilhado)
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(0.18 * s)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=(28, 61, 90, 255))
    m = int(0.14 * s)                               # caixa interna
    box = (m, m, s - m, s - m)
    d.rectangle(box, fill=(245, 247, 251, 255))
    w = max(2, int(0.06 * s))
    d.rectangle((m - w // 2, m, m + w // 2, s - m), fill=(224, 49, 49, 255))      # parede quente
    d.rectangle((s - m - w // 2, m, s - m + w // 2, s - m), fill=(25, 113, 194, 255))  # parede fria
    rng = random.Random(7)
    colors = [(13, 8, 135), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33)]
    n = 9 if size >= 32 else 5
    pr = int((0.055 if size >= 32 else 0.08) * s)
    pts = []
    while len(pts) < n:
        x = rng.uniform(m + w + pr, s - m - w - pr)
        y = rng.uniform(m + pr, s - m - pr)
        if all((x - a) ** 2 + (y - b) ** 2 > (2.6 * pr) ** 2 for a, b in pts):
            pts.append((x, y))
    for i, (x, y) in enumerate(pts):
        # mais quentes (claras) perto da parede quente, à esquerda
        c = colors[min(len(colors) - 1, int((1 - (x - m) / (s - 2 * m)) * len(colors)))]
        d.ellipse((x - pr, y - pr, x + pr, y + pr), fill=c + (255,))
    return im.resize((size, size), Image.LANCZOS)


def main():
    big = draw(256)
    big.save(ROOT / "gui" / "icone.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [draw(n) for n in sizes]
    imgs[-1].save(ROOT / "packaging" / "windows" / "icone.ico", sizes=[(n, n) for n in sizes],
                  append_images=imgs[:-1])
    print("ícones gerados")


if __name__ == "__main__":
    main()
