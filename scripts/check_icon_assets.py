from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)


def _check_png(path: Path, size: int) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"missing {path.relative_to(ROOT)}"]

    try:
        with Image.open(path) as image:
            if image.size != (size, size):
                actual = f"{image.size[0]}x{image.size[1]}"
                expected = f"{size}x{size}"
                errors.append(f"{path.relative_to(ROOT)} is {actual}, expected {expected}")
            if image.format != "PNG":
                errors.append(f"{path.relative_to(ROOT)} is {image.format}, expected PNG")
    except OSError as exc:
        errors.append(f"{path.relative_to(ROOT)} is unreadable: {exc}")

    return errors


def main() -> int:
    errors: list[str] = []
    for size in SIZES:
        errors.extend(_check_png(ASSET_DIR / f"icon-{size}.png", size))

    errors.extend(_check_png(ASSET_DIR / "icon.png", 512))

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("icon assets OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
