"""Typical case in the 300-case Aurora prod run: time, GPU and CPU per pipeline step -> PNG."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

rows = [  # label, sub, minutes, gpu %, cpu %, kind
    ("Structure prediction", "cached", 0, None, None, "p"),
    ("Preparation", "", 8, 13, 0.3, "p"),
    ("Classical model", "", 7, 36, 0.5, "p"),
    ("Classical NVT", "", 1, 28, 0.5, "p"),
    ("Classical NPT", "", 7, 39, 0.6, "p"),
    ("Near-attack sampling", "", 1, 30, 1.2, "p"),
    ("Relaxed near-attack", "", 11, 29, 0.5, "p"),
    ("Reactive model", "", 2, 10, 0.5, "p"),
    ("Reactive thermalization", "", 19, 39, 1.3, "p"),
    ("Waiting for 4 free nodes", "not on a node", 174, None, None, "w"),
    ("Reaction sampling", "main simulation", 294, 51, 5.1, "m"),
]
COL = {"p": "#eb6834", "w": "#b4b2a9", "m": "#2a78d6"}
TRACK, INK, MUTED, LINE = "#efeee9", "#1f1f1d", "#898781", "#dcdad3"

def tfmt(m):
    return "~0 min" if m == 0 else (f"{m} min" if m < 60 else f"{m/60:.1f} h")

plt.rcParams["font.family"] = ["Helvetica Neue", "Arial", "DejaVu Sans"]
W, rowh = 11.6, 0.42
n = len(rows)
H = 1.5 + (n + 1.4) * rowh
fig = plt.figure(figsize=(W, H), dpi=200)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
fig.patch.set_facecolor("white")

# legend
lx, ly = 0.35, 0.38
for name, k in (("Preprocessing (1 node)", "p"), ("Waiting for nodes", "w"), ("Main simulation (4 nodes)", "m")):
    ax.add_patch(FancyBboxPatch((lx, ly - 0.07), 0.14, 0.14, boxstyle="round,pad=0,rounding_size=0.025", fc=COL[k], ec="none"))
    ax.text(lx + 0.22, ly, name, va="center", fontsize=10, color="#52514e")
    lx += 0.22 + len(name) * 0.085 + 0.45

# columns: label | time | gpu | cpu
cols = [(0.35, None), (3.0, (300, 2.6)), (6.55, (100, 1.7)), (9.15, (100, 1.6))]
hy = 0.95
for (x, _), h in zip(cols, ("Step (in order)", "Time, typical case", "GPU busy", "CPU busy")):
    ax.text(x, hy, h, fontsize=10, color=MUTED, va="center")

def bar(x, spec, v, color, txt, y):
    vmax, width = spec
    ax.add_patch(FancyBboxPatch((x, y - 0.1), width, 0.2, boxstyle="round,pad=0,rounding_size=0.04", fc=TRACK, ec="none"))
    if v:
        w = max(0.02, width * v / vmax)
        ax.add_patch(FancyBboxPatch((x, y - 0.1), w, 0.2, boxstyle="round,pad=0,rounding_size=0.04", fc=color, ec="none"))
    ax.text(x + width + 0.12, y, txt, fontsize=10, color="#52514e", va="center")

y = hy + 0.5
for i, (lab, sub, m, g, c, k) in enumerate(rows):
    if i == 9:
        ax.plot([0.35, W - 0.35], [y - rowh / 2, y - rowh / 2], color=LINE, lw=0.6)
    if sub:
        ax.text(0.35, y - 0.06, lab, fontsize=11, color=INK, va="center")
        ax.text(0.35, y + 0.13, sub, fontsize=8.5, color=MUTED, va="center")
    else:
        ax.text(0.35, y, lab, fontsize=11, color=INK, va="center")
    bar(cols[1][0], cols[1][1], m, COL[k], tfmt(m), y)
    bar(cols[2][0], cols[2][1], g, COL[k], "–" if g is None else f"{g}%", y)
    bar(cols[3][0], cols[3][1], c, COL[k], "–" if c is None else f"{c:.1f}%", y)
    y += rowh
ax.plot([0.35, W - 0.35], [y - rowh / 2 + 0.02, y - rowh / 2 + 0.02], color=LINE, lw=0.6)
y += 0.08
ax.text(0.35, y, "Total", fontsize=11, color=INK, va="center", fontweight="bold")
ax.text(cols[1][0], y, "~8.7 h", fontsize=11, color=INK, va="center", fontweight="bold")
ax.text(cols[1][0] + 0.75, y, "0.9 h prep · 2.9 h wait · 4.9 h main", fontsize=9, color=MUTED, va="center")

out = "/Users/fmuhammedkutty/Desktop/Mechanism-atlas/work/prod300/report/typical-case-steps.png"
fig.savefig(out, dpi=200, facecolor="white")
print(out)
