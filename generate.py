"""Additive light art: coloured ellipses that all overlap one common centre.

Every ellipse contains the centre point, whatever the parameters; the script
checks this and refuses to render otherwise.

Light is summed in LINEAR RGB (not alpha-blended in sRGB), clipped, and encoded
to sRGB. That is the true additive image on black ("light"). A white ground
cannot be lit further, so the white version ("paper") is a translation: each
pixel's departure from neutral becomes colour, and full overlap stays white.

Outputs (PNG, SIZE x SIZE), prefixed by --name:
  <name>_light.png     additive light on black (RGB)
  <name>_paper.png     translation for a white ground (RGBA, transparent ground)
  <name>_preview.jpg   paper (on white) and light side by side

Code: 0BSD. Generated images: CC0 1.0.
"""
import argparse
import colorsys
import math
from pathlib import Path

import numpy as np
from PIL import Image

SEED = 20261004
N = 36            # number of ellipses
SIZE = 2900       # output side in pixels
EDGE = 1.11       # ellipse boundary, in units of its own radius squared
SOFTNESS = 0.36   # width of the faded rim (same units)
SATURATION = 0.93
HUE_START = 0.035


def parse_colors(spec):
    """'rainbow' or a comma-separated list of hex colours like '#ff2a6d,#05d9e8'."""
    if spec == 'rainbow':
        return None
    stops = []
    for h in spec.split(','):
        h = h.strip().lstrip('#')
        if len(h) != 6:
            raise ValueError(f'not a #rrggbb colour: {h!r}')
        stops.append([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    return np.asarray(stops, dtype=np.float64)


def srgb_to_linear(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - .055)


def beam_colors(n, stops=None, steps=0, saturation=SATURATION, hue_start=HUE_START):
    """One colour per ellipse, going once around the circle.

    rainbow (stops None): hues evenly around the colour wheel.
    stops: a closed gradient through the given colours, blended in linear RGB.
    steps > 0 quantises the gradient into that many distinct colours, in
    contiguous blocks; steps 0 keeps it continuous.
    """
    pos = [j / n if steps <= 0 else (j * steps // n) / steps for j in range(n)]
    if stops is None:
        return [np.asarray(colorsys.hsv_to_rgb((p + hue_start) % 1.0, saturation, 1.0),
                           dtype=np.float32) for p in pos]
    lin = srgb_to_linear(stops)
    k = len(lin)
    out = []
    for p in pos:
        x = p * k
        i = int(x) % k
        f = x - int(x)
        c = (1 - f) * lin[i] + f * lin[(i + 1) % k]
        out.append(np.asarray(linear_to_srgb(c), dtype=np.float32))
    return out


def make_axes(seed=SEED, n=N, beams=None, gain=1.0):
    rng = np.random.default_rng(seed)
    if beams is None:
        beams = beam_colors(n)
    # keep the centre about as bright whatever the count
    scale = gain * N / n
    axes = []
    for j in range(n):
        theta = 2 * math.pi * j / n - 0.85 + float(rng.normal(0, 0.07))
        major = float(rng.uniform(0.89, 1.16))
        minor = float(rng.uniform(0.28, 0.43))
        offset = float(rng.uniform(0.29, 0.44))
        # weak single ellipses make the overlaps much brighter
        strength = float(rng.uniform(.041, .055)) * scale
        axes.append((theta, major, minor, offset, beams[j], strength))
    return axes


def petal_weight(q, edge, softness, falloff):
    # smoothstep rim: solid inside q < edge - softness, gone at q = edge
    t = np.clip((edge - q) / softness, 0.0, 1.0)
    m = t * t * (3 - 2 * t)
    if falloff:
        # brightest at the ellipse's own centre, dimmer toward its rim
        m = m * (1 - falloff * np.sqrt(np.clip(q / edge, 0, 1)))
    return m


def centre_weights(axes, edge, softness, falloff):
    """Weight of every ellipse at the common centre; all must be > 0."""
    q = np.asarray([(d / a) ** 2 for _, a, _, d, _, _ in axes], dtype=np.float32)
    return petal_weight(q, edge, softness, falloff)


def auto_extent(axes, edge):
    """Smallest canvas half-width (rounded up, plus margin) that holds every petal."""
    r = math.sqrt(edge)
    reach = 0.0
    for theta, a, b, d, _, _ in axes:
        c, s = math.cos(theta), math.sin(theta)
        reach = max(reach,
                    abs(d * c) + r * math.hypot(a * c, b * s),
                    abs(d * s) + r * math.hypot(a * s, b * c))
    return math.ceil(reach * 1.066 * 100) / 100


def render_light(axes, size, extent, edge=EDGE, softness=SOFTNESS, falloff=0.0):
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
        m = petal_weight(q, edge, softness, falloff)
        light += m[:, :, None] * (strength * beam[None, None, :])
    return np.clip(light, 0, 1)


def paper(srgb, ink):
    """RGBA that, composited over white, gives white - colour.

    Colour is each channel's shortfall from the pixel's brightest channel, so
    neutral pixels (empty ground, white centre) stay white.
    """
    peak = np.max(srgb, axis=2)
    contrast = np.clip(peak[:, :, None] - srgb, 0, 1)
    delta = np.clip(contrast * ink, 0, 0.82)
    target = np.clip(1 - delta, 0, 1)
    alpha = np.clip(np.max(delta, axis=2) / 0.75, 0, 0.96)
    rgb = np.clip(1 - (1 - target) / np.maximum(alpha[:, :, None], 1e-5), 0, 1)
    return np.concatenate([(255 * rgb + .5).astype('uint8'),
                           (255 * alpha + .5).astype('uint8')[:, :, None]], axis=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=Path, default=Path('samples'))
    ap.add_argument('--name', default='art', help='file name prefix')
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('--size', type=int, default=SIZE, help='pixels per side')
    ap.add_argument('-n', '--count', type=int, default=N, help='number of ellipses')
    ap.add_argument('--colors', default='rainbow',
                    help="'rainbow' or hex stops '#ff2a6d,#05d9e8,...' (closed gradient)")
    ap.add_argument('--steps', type=int, default=0,
                    help='number of distinct colours (0 = continuous gradient)')
    ap.add_argument('--saturation', type=float, default=SATURATION, help='rainbow only')
    ap.add_argument('--hue-start', type=float, default=HUE_START, help='rainbow only, 0..1')
    ap.add_argument('--softness', type=float, default=SOFTNESS,
                    help=f'rim fade width, 0 < s < {EDGE} (small = crisp edges)')
    ap.add_argument('--falloff', type=float, default=0.0,
                    help='0..1, dims each petal from its own centre to its rim')
    ap.add_argument('--gain', type=float, default=1.0, help='overall brightness')
    ap.add_argument('--ink', type=float, default=1.0, help='colour strength of the paper version')
    ap.add_argument('--extent', type=float, default=None,
                    help='canvas half-width in ellipse units (default: fit all petals)')
    args = ap.parse_args()
    if args.count < 1:
        ap.error('--count must be at least 1')
    if not 0 < args.softness < EDGE:
        ap.error(f'--softness must be in (0, {EDGE})')
    if not 0 <= args.falloff <= 1:
        ap.error('--falloff must be in [0, 1]')

    stops = parse_colors(args.colors)
    beams = beam_colors(args.count, stops, args.steps, args.saturation, args.hue_start)
    axes = make_axes(args.seed, args.count, beams, args.gain)

    w = centre_weights(axes, EDGE, args.softness, args.falloff)
    if not (w > 0).all():
        raise SystemExit('refusing to render: not every ellipse covers the centre')
    extent = args.extent if args.extent is not None else auto_extent(axes, EDGE)

    srgb = linear_to_srgb(render_light(axes, args.size, extent, EDGE, args.softness, args.falloff))
    light = Image.fromarray(np.uint8(np.clip(srgb * 255 + 0.5, 0, 255)), 'RGB')
    pap = Image.fromarray(paper(srgb, args.ink), 'RGBA')

    args.out.mkdir(parents=True, exist_ok=True)
    light.save(args.out / f'{args.name}_light.png', optimize=True)
    pap.save(args.out / f'{args.name}_paper.png', optimize=True)

    side = 800
    board = Image.new('RGB', (2 * side, side), 'white')
    tile = Image.new('RGBA', pap.size, (255, 255, 255, 255))
    tile.alpha_composite(pap)
    board.paste(tile.convert('RGB').resize((side, side), Image.Resampling.LANCZOS), (0, 0))
    board.paste(light.resize((side, side), Image.Resampling.LANCZOS), (side, 0))
    board.save(args.out / f'{args.name}_preview.jpg', quality=90)

    print(f'{args.name}: seed {args.seed}, {len(axes)} ellipses, extent {extent}, '
          f'every ellipse covers the centre (min weight {w.min():.3f})')


if __name__ == '__main__':
    main()
