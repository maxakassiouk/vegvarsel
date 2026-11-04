"""Export Vegvarsel's logo sizes from the transparent master artwork.

    python tools/make_logo.py

Requires Pillow. See docs/branding/README.md for the source and design brief.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "branding" / "vegvarsel-master.png"
OUT = ROOT / "custom_components" / "vegvarsel" / "brand"


def main() -> None:
    with Image.open(SOURCE) as source:
        if source.width != source.height or source.mode != "RGBA":
            raise ValueError("Logo master must be a square RGBA image with transparency.")
        artwork = source.copy()

    outputs = (
        (OUT / "icon.png", 256),
        (OUT / "icon@2x.png", 512),
        (ROOT / "docs" / "vegvarsel-logo.png", 1024),
    )
    for path, size in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        artwork.resize((size, size), Image.Resampling.LANCZOS).save(path, optimize=True)
        print(f"written: {path.relative_to(ROOT)} ({size} x {size})")


if __name__ == "__main__":
    main()
