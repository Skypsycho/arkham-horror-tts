"""Generate the tentacle arms for the selected-campaign Cthulhu marker.

    python tools/cthulhu_svg.py

The head itself is a painted image (static/cthulhu-front.png and
static/cthulhu-profile.png, cut out with tools/cutout_checkerboard.py). This
script draws the two long arms that reach from behind it along the top and
bottom of the selected row, plus a short one, and writes them to
static/cthulhu-arms.svg, which templates/index.html inlines so the arms can
animate. Colours and animation live in the .cthulhu-mark CSS in index.html.
"""
import math
from pathlib import Path

HERE = Path(__file__).parent
OUT_SVG = HERE.parent / "static" / "cthulhu-arms.svg"
W, H = 260, 70            # selected row size in px (sidebar width x row height)


def bez(p0, p1, p2, p3, n):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def spiral(start, heading, r0, turns, direction, n):
    """Curl from `start` travelling along `heading` (radians), turning
    `direction` (+1 = clockwise on screen) with shrinking radius."""
    cx = start[0] + direction * -math.sin(heading) * r0
    cy = start[1] + direction * math.cos(heading) * r0
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    pts = []
    for i in range(1, n + 1):
        t = i / n
        a = a0 + direction * t * turns * 2 * math.pi
        r = r0 * (1 - 0.8 * t)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def tentacle(segs, w0, w1, curl_r, curl_turns, curl_dir, suckers_side=1, n_suckers=6):
    """Tapered tentacle outline along chained cubic segments, ending in a curl.
    Returns (path d, [(x, y, r) suckers], base point)."""
    body = []
    for s in segs:
        pts_s = bez(*s, 40)
        body += pts_s if not body else pts_s[1:]
    p0 = segs[0][0]
    hx, hy = body[-1][0] - body[-2][0], body[-1][1] - body[-2][1]
    pts = body + spiral(body[-1], math.atan2(hy, hx), curl_r, curl_turns, curl_dir, 30)

    L = [0.0]
    for a, b in zip(pts, pts[1:]):
        L.append(L[-1] + math.dist(a, b))
    total = L[-1]

    left, right, normals = [], [], []
    for i, (x, y) in enumerate(pts):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy) or 1
        nx, ny = -dy / d, dx / d
        t = L[i] / total
        w = (w0 * (1 - t) ** 1.3 + w1 * t) / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
        normals.append((nx, ny, w))

    outline = left + right[::-1]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in outline) + " Z"

    cups = []
    for k in range(n_suckers):
        t = 0.12 + 0.58 * k / max(n_suckers - 1, 1)
        idx = min(range(len(L)), key=lambda i: abs(L[i] / total - t))
        x, y = pts[idx]
        nx, ny, w = normals[idx]
        r = max(w * 0.42, 0.45)
        cups.append((x + suckers_side * nx * w * 0.45, y + suckers_side * ny * w * 0.45, r))
    return d, cups, p0


def S(*pts):
    """Chain of cubic segments from a flat list of points: p0, c1, c2, p1, c1, c2, p2 …"""
    return [tuple(pts[i:i + 4]) for i in range(0, len(pts) - 1, 3)]


# name, segments, base width, tip width, curl radius, turns, curl dir, sucker side, suckers
# Bases sit behind the painted head, which is pushed ~10px past the row's left
# edge (it covers roughly x -10–42). Everything stays inside the row (0–H).
ARMS = [
    # runs just under the top edge, then hooks down
    ("t-over", S((30, 20), (48, 5), (74, 3), (98, 5), (116, 7), (128, 12), (129, 21)),
     6.0, 0.7, 3.0, 1.15, 1, 1, 7),
    # runs just above the bottom edge, then curls up
    ("t-under", S((30, 50), (52, 65), (86, 68), (116, 66), (136, 64), (150, 59), (151, 50)),
     6.4, 0.7, 3.2, 1.15, -1, -1, 7),
    ("t-top", S((28, 24), (56, 4), (88, 4), (120, 8), (152, 12), (180, 2), (212, 7)),
     7.2, 0.8, 4.4, 1.2, 1, 1, 9),
    ("t-low", S((28, 46), (60, 68), (94, 67), (130, 61), (166, 54), (194, 67), (230, 61)),
     7.8, 0.8, 4.6, 1.25, -1, -1, 10),
    ("t-mid", S((32, 52), (46, 64), (64, 58), (80, 60), (92, 62), (102, 66), (114, 62)),
     5.0, 0.6, 3.0, 1.1, -1, -1, 6),
]


def svg_fragment():
    parts = [
        f'<svg class="cth-arms" viewBox="0 0 {W} {H}" preserveAspectRatio="xMinYMid meet" aria-hidden="true">',
        "<defs>"
        '<linearGradient id="cthArm" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4a5e53"/>'
        '<stop offset=".5" stop-color="#2c3a33"/><stop offset="1" stop-color="#141c18"/></linearGradient>'
        # gritty skin relief, matching the painted head
        '<filter id="cthFlesh" x="-5%" y="-30%" width="110%" height="160%" color-interpolation-filters="sRGB">'
        '<feTurbulence type="turbulence" baseFrequency="0.22 0.32" numOctaves="2" seed="8" result="t"/>'
        '<feDiffuseLighting in="t" surfaceScale="1.1" lighting-color="#ffffff" result="light">'
        '<feDistantLight azimuth="235" elevation="60"/></feDiffuseLighting>'
        '<feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="0.7" k2="0" k3="0.45" k4="0" result="lit"/>'
        '<feComposite in="lit" in2="SourceGraphic" operator="in"/></filter>'
        "</defs>",
    ]
    for name, segs, w0, w1, cr, ct, cd, side, ncup in ARMS:
        d, cups, base = tentacle(segs, w0, w1, cr, ct, cd, side, ncup)
        cup_svg = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r * 1.1:.2f}"/>' for x, y, r in cups)
        parts.append(
            f'<g class="cth-tentacle {name}" style="transform-origin:{base[0]}px {base[1]}px">'
            f'<path class="cth-skin" d="{d}"/><g class="cth-cups">{cup_svg}</g></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


if __name__ == "__main__":
    frag = svg_fragment()
    OUT_SVG.write_text(frag, encoding="utf-8")
    print("wrote", OUT_SVG, len(frag), "chars")
