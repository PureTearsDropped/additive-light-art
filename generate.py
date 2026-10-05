"""Additive light art: 36 coloured ellipses that all overlap one common centre.

Light is summed in LINEAR RGB (not alpha-blended in sRGB), clipped, and encoded
to sRGB. That is the true additive image on black. Because white fabric cannot
emit light, the white-ground variants are a print translation: each pixel's
departure from neutral becomes ink, and full overlap stays white.

Outputs (PNG, SIZE x SIZE):
  additive_black.png        true additive light on black (RGB)
  white_soft.png            print translation for white ground, gentle (RGBA)
  white_bright.png          print translation for white ground, vivid (RGBA)
  preview.jpg               the three side by side, white variants shown on white

Code: 0BSD. Generated images: CC0 1.0.
"""
import argparse
import colorsys
import math
from pathlib import Path

import numpy as np
from PIL import Image

SEED = 20261004
N = 36          # number of ellipses
SIZE = 2900     # output side in pixels
EXTENT = 1.70   # half-width of the canvas in ellipse units (1.43 clips petal tips)


def make_axes(seed=SEED, n=N):
    rng = np.random.default_rng(seed)
    axes = []
    for j in range(n):
        theta = 2 * math.pi * j / n - 0.85 + float(rng.normal(0, 0.07))
        major = float(rng.uniform(0.89, 1.16))
        minor = float(rng.uniform(0.28, 0.43))
        offset = float(rng.uniform(0.29, 0.44))
        hsv = ((j / n + 0.035) % 1.0, 0.93, 1.0)
        beam = np.asarray(colorsys.hsv_to_rgb(*hsv), dtype=np.float32)
        # weak single ellipses make the overlaps much brighter
        strength = float(rng.uniform(.041, .055))
        axes.append((theta, major, minor, offset, beam, strength))
    return axes


def render_light(axes, size=SIZE, extent=EXTENT):
    """Linear-RGB radiance, clipped to [0, 1]."""
    coords = (np.arange(size, dtype=np.float32) + .5 - size / 2) / (size / 2) * extent
    xx = coords[None, :]
    yy = coords[:, None]
    light = np.zeros((size, size, 3), dtype=np.float32)
    for theta, a, b, d, beam, strength in axes:
        c = np.float32(math.cos(theta))
        s = np.float32(math.sin(theta))
        u = c * xx + s * yy
        v = -s * xx + c * yy
        q = ((u - d) / a) ** 2 + (v / b) ** 2
        # smoothstep edge: solid interior for q < 0.75, fades out by q = 1.11
        t = np.clip((1.11 - q) / .36, 0.0, 1.0)
        m = t * t * (3 - 2 * t)
        light += m[:, :, None] * (strength * beam[None, None, :])
    return np.clip(light, 0, 1)


def linear_to_srgb(x):
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - .055)


def white_print(srgb, pigment_boost):
    """RGBA that, composited over white, gives white - ink.

    Ink is each channel's shortfall from the pixel's brightest channel, so
    neutral pixels (black ground, white centre) carry no ink at all.
    """
    peak = np.max(srgb, axis=2)
    contrast = np.clip(peak[:, :, None] - srgb, 0, 1)
    delta = np.clip(contrast * pigment_boost, 0, 0.82)
    target = np.clip(1 - delta, 0, 1)
    alpha = np.clip(np.max(delta, axis=2) / 0.75, 0, 0.96)
    rgb = np.clip(1 - (1 - target) / np.maximum(alpha[:, :, None], 1e-5), 0, 1)
    return np.concatenate([(255 * rgb + .5).astype('uint8'),
                           (255 * alpha + .5).astype('uint8')[:, :, None]], axis=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=Path, default=Path('samples'))
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('--size', type=int, default=SIZE)
    ap.add_argument('--extent', type=float, default=EXTENT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    axes = make_axes(args.seed)
    srgb = linear_to_srgb(render_light(axes, args.size, args.extent))

    black = Image.fromarray(np.uint8(np.clip(srgb * 255 + 0.5, 0, 255)), 'RGB')
    soft = Image.fromarray(white_print(srgb, 0.70), 'RGBA')
    bright = Image.fromarray(white_print(srgb, 1.24), 'RGBA')
    black.save(args.out / 'additive_black.png', optimize=True)
    soft.save(args.out / 'white_soft.png', optimize=True)
    bright.save(args.out / 'white_bright.png', optimize=True)

    side = 800
    board = Image.new('RGB', (3 * side, side), 'white')
    for k, im in enumerate([soft, bright]):
        tile = Image.new('RGBA', im.size, (255, 255, 255, 255))
        tile.alpha_composite(im)
        board.paste(tile.convert('RGB').resize((side, side), Image.Resampling.LANCZOS), (k * side, 0))
    board.paste(black.resize((side, side), Image.Resampling.LANCZOS), (2 * side, 0))
    board.save(args.out / 'preview.jpg', quality=90)

    print('seed', args.seed, 'size', args.size, 'extent', args.extent, 'ellipses', len(axes))
    print('all ellipses contain the centre', all((d / a) ** 2 < 1 for _, a, _, d, _, _ in axes))


if __name__ == '__main__':
    main()
