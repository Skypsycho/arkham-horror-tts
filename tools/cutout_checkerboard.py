"""Remove a baked-in "transparency" checkerboard from an image and save a real
transparent PNG, cropped to the subject.

    python tools/cutout_checkerboard.py <input.png> <output.png> [--height 320]

Works for dark/colourful subjects on the light-grey/white checkerboard that
image generators paint when asked for a transparent background:
  1. background = light, colourless pixels connected to the image border
     (flood fill, so light highlights inside the subject are kept)
  2. the edge is pulled in a pixel and feathered so no light halo remains
  3. faded "smoke" edges (grey, semi-light) become a dark translucent fade
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SAT_MAX = 22        # max(R,G,B) - min(R,G,B) below this counts as colourless
BG_MIN_LUM = 172    # colourless pixels at least this light can be background
SOFT_LO, SOFT_HI = 120, 200   # luminance range turned into a soft fade
MIN_POCKET = 600    # enclosed light-grey regions at least this many px are background
                    # (pale barnacles/highlights are smaller; checkerboard pockets far bigger)


def cutout(src, dst, height):
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(np.float32)
    lum = rgb.mean(axis=2)
    sat = rgb.max(axis=2) - rgb.min(axis=2)

    light_grey = (sat < SAT_MAX) & (lum >= BG_MIN_LUM)
    # light-grey regions that touch the border, plus enclosed pockets (e.g.
    # inside curled tentacles) big enough to be checkerboard rather than a
    # highlight — the subject's own highlights are tinted, not colourless
    labels, n = ndimage.label(light_grey)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    sizes = ndimage.sum(np.ones_like(lum), labels, index=np.arange(n + 1))
    pockets = np.flatnonzero(sizes >= MIN_POCKET)
    bg = np.isin(labels, np.union1d(border[border > 0], pockets[pockets > 0]))

    # soft fade for colourless, mid-light pixels next to the background (smoke)
    near_bg = ndimage.binary_dilation(bg, iterations=6)
    smoky = near_bg & ~bg & (sat < SAT_MAX + 10) & (lum > SOFT_LO)
    alpha = np.ones(lum.shape, np.float32)
    alpha[bg] = 0.0
    fade = np.clip((SOFT_HI - lum) / (SOFT_HI - SOFT_LO), 0, 1)
    alpha[smoky] = np.minimum(alpha[smoky], fade[smoky])

    # pull the edge in by one pixel, then feather it
    solid = alpha > 0.5
    eroded = ndimage.binary_erosion(solid, iterations=1)
    alpha = np.where(solid & ~eroded, alpha * 0.5, alpha)
    alpha = ndimage.gaussian_filter(alpha, 0.8) * (alpha > 0)

    # light pixels that survive at the edge get darkened so they don't glow
    edge = (alpha < 0.95) & (alpha > 0)
    dark = np.array([22, 32, 28], np.float32)
    t = np.clip((lum - 110) / 100, 0, 1)[..., None] * edge[..., None]
    rgb = rgb * (1 - t) + dark * t

    out = np.dstack([rgb, alpha * 255]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    img = img.crop(bbox)
    if height and img.height > height:
        img = img.resize((round(img.width * height / img.height), height), Image.LANCZOS)
    img.save(dst, optimize=True)
    print(f"{Path(dst).name}: {img.size[0]}x{img.size[1]}  (cropped from {bbox})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--height", type=int, default=320)
    a = ap.parse_args()
    cutout(a.src, a.dst, a.height)
