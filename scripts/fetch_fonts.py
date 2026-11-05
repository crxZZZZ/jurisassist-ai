"""Fetch only the two OFL Latin font files used by the offline interface."""

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx


def main():
    target = Path(__file__).resolve().parents[1] / "frontend/public/fonts"
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for family, key, weights in [
            ("DM+Sans", "dm-sans", "400..700"),
            ("Manrope", "manrope", "400..800"),
        ]:
            response = client.get(
                f"https://fonts.googleapis.com/css2?family={family}:wght@{weights}&display=swap"
            )
            response.raise_for_status()
            latin = response.text.split("/* latin */")[-1]
            match = re.search(r"url\((https://[^)]+)\)", latin)
            if match is None or urlparse(match[1]).hostname != "fonts.gstatic.com":
                raise RuntimeError("Font source not recognized")
            font = client.get(match[1])
            font.raise_for_status()
            (target / f"{key}-latin.woff2").write_bytes(font.content)
            license_file = client.get(
                f"https://raw.githubusercontent.com/google/fonts/main/ofl/{key.replace('-', '')}/OFL.txt"
            )
            license_file.raise_for_status()
            (target / f"{key}-OFL.txt").write_text(license_file.text, encoding="utf-8")
            print(f"{key}: {len(font.content)} bytes")


if __name__ == "__main__":
    main()
