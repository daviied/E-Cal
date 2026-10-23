"""Builds both ways of installing CalcVault from CALCVAULT.txt:

    CALCVAULT.hpprgm     a program, run by typing CALCVAULT on Home
    CalcVault.hpappdir   an app, opened from the Apps screen

    python build.py      (needs hp-prime-kit; set HPK to its folder)

The app is the same source with its entry point renamed START, the hook the
calculator runs when an app is opened, so the two do not clash if both are
installed. The app is built with hp-prime-kit's blank-app wrappers, the
shape measured to open on a G2.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HPK = os.environ.get("HPK", r"C:\Users\nyg4\ref\hpk")
SRC = os.path.join(HERE, "CALCVAULT.txt")
APP = "CalcVault"


def hpprime(*args):
    subprocess.run([sys.executable, os.path.join(HPK, "hpprime.py")] + list(args), check=True, cwd=HERE)


def icon(path):
    """73 x 74, the size HP's own icons are, drawn at 4x and scaled down."""
    from PIL import Image, ImageDraw
    s = 4
    w, h = 73 * s, 74 * s
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((6 * s, 4 * s, 67 * s, 70 * s), radius=9 * s, fill=(40, 70, 120, 255))
    d.rounded_rectangle((13 * s, 11 * s, 60 * s, 27 * s), radius=3 * s, fill=(225, 238, 255, 255))
    for r in range(3):
        for c in range(3):
            x, y = 13 + c * 17, 33 + r * 12
            col = (240, 190, 70, 255) if (r, c) == (2, 2) else (200, 215, 240, 255)
            d.rounded_rectangle((x * s, y * s, (x + 13) * s, (y + 9) * s), radius=2 * s, fill=col)
    # a keyhole on the display, for the vault
    d.ellipse((33 * s, 14 * s, 40 * s, 21 * s), fill=(40, 70, 120, 255))
    d.polygon([(34.5 * s, 19 * s), (38.5 * s, 19 * s), (39.5 * s, 25 * s), (33.5 * s, 25 * s)],
              fill=(40, 70, 120, 255))
    im.resize((73, 74), Image.LANCZOS).save(path)


def main():
    with open(SRC, encoding="utf-8") as f:
        source = f.read()

    hpprime("lint", SRC, "--quiet")
    hpprime("write", SRC, "-o", os.path.join(HERE, "CALCVAULT.hpprgm"))

    app_src = re.sub(r"(?m)^EXPORT CALCVAULT\(\)$", "EXPORT START()", source)
    assert app_src != source, "entry point not found"
    app_src = app_src.replace("Run CALCVAULT from Home (no parentheses).",
                              "Opened from the Apps screen; START is the app's entry point.")
    build = os.path.join(HERE, "build")
    os.makedirs(build, exist_ok=True)
    app_txt = os.path.join(build, APP + ".txt")
    with open(app_txt, "w", encoding="utf-8") as f:
        f.write(app_src)
    icon_png = os.path.join(build, "icon.png")
    icon(icon_png)
    out = os.path.join(HERE, APP + ".hpappdir")
    if os.path.isdir(out):
        shutil.rmtree(out)
    hpprime("build", APP, app_txt, "--ppl", "--icon", icon_png, "-o", HERE)
    print("built", out)


if __name__ == "__main__":
    main()
