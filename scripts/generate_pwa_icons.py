import os
import subprocess
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_SVG = REPO_ROOT / "assets" / "verifika2" / "verifika2_app_icon.svg"
OUT_DIR = REPO_ROOT / "web" / "icons" / "ios" / "v26"


SIZES = [
    ("apple-touch-icon-120.png", 120),
    ("apple-touch-icon-152.png", 152),
    ("apple-touch-icon-167.png", 167),
    ("apple-touch-icon-180.png", 180),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
]


def _require_magick() -> str:
    exe = os.environ.get("MAGICK_BIN") or "magick"
    try:
        subprocess.check_output([exe, "-version"], stderr=subprocess.STDOUT)
    except Exception as exc:
        raise RuntimeError(
            "No se encontró ImageMagick (`magick`). Instálalo o exporta MAGICK_BIN apuntando al binario."
        ) from exc
    return exe


def _foreground_center_delta(png_path: Path) -> tuple[float, float]:
    im = Image.open(png_path).convert("RGBA")
    w, h = im.size
    px = im.load()
    pts = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 10:
                continue
            # Verde del check y dorado del "²" (tolerante).
            is_green = g > 120 and r < 130 and b < 130
            is_gold = r > 160 and g > 110 and b < 150
            if is_green or is_gold:
                pts.append((x, y))
    if not pts:
        return 0.0, 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return (cx - (w / 2)), (cy - (h / 2))


def main() -> None:
    exe = _require_magick()
    if not SRC_SVG.exists():
        raise SystemExit(f"SVG no encontrado: {SRC_SVG}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size in SIZES:
        out = OUT_DIR / filename
        subprocess.check_call(
            [
                exe,
                "-density",
                "256",
                str(SRC_SVG),
                "-resize",
                f"{size}x{size}",
                str(out),
            ]
        )
        dx, dy = _foreground_center_delta(out)
        # Aceptamos 1px de tolerancia por antialiasing.
        if abs(dx) > 1.1 or abs(dy) > 1.1:
            raise SystemExit(f"Icono descentrado: {out} (dx={dx:.2f}, dy={dy:.2f})")

    print(f"OK: iconos generados en {OUT_DIR}")


if __name__ == "__main__":
    main()
