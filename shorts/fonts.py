"""PC마다 설치된 한글 폰트를 찾는다. fonts/ 폴더 → 사용자/시스템 폰트 폴더 순서."""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .common import ROOT, ShortsError

EXTS = {".otf", ".ttf", ".ttc"}


def _dirs() -> list[Path]:
    home = Path.home()
    dirs = [ROOT / "fonts", home / ".fonts", home / ".local/share/fonts",
            Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
            Path("/Library/Fonts"), home / "Library/Fonts", Path("/System/Library/Fonts")]
    if sys.platform == "win32":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs.insert(1, windir / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.insert(1, Path(local) / "Microsoft/Windows/Fonts")
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=1)
def _all_files() -> list[Path]:
    out = []
    for d in _dirs():
        for p in d.rglob("*"):
            if p.suffix.lower() in EXTS:
                out.append(p)
    return out


def _ttc_index(path: Path) -> int:
    """Noto Sans CJK .ttc 에서 KR 얼굴 번호를 찾는다."""
    for i in range(12):
        try:
            f = ImageFont.truetype(str(path), 20, index=i)
        except OSError:
            break
        fam = " ".join(f.getname())
        if "KR" in fam or "Korean" in fam:
            return i
    return 0


@lru_cache(maxsize=8)
def find_font(weight: str, candidates: tuple[str, ...]) -> tuple[str, int, str | None]:
    files = _all_files()
    for cand in candidates:
        c = cand.lower()
        for p in files:
            if p.stem.lower().startswith(c):
                index = _ttc_index(p) if p.suffix.lower() == ".ttc" else 0
                variation = None
                if "variable" in p.stem.lower():
                    variation = "Black" if weight == "black" else "Bold"
                return str(p), index, variation
    raise ShortsError(
        "한글 폰트를 찾지 못했습니다. Noto Sans KR(Black, Bold)을 설치하거나 "
        "fonts/ 폴더에 NotoSansKR-Black.ttf, NotoSansKR-Bold.ttf 를 넣으세요. "
        "https://fonts.google.com/noto/specimen/Noto+Sans+KR")


def load_font(project: dict, weight: str, size: int) -> ImageFont.FreeTypeFont:
    path, index, variation = find_font(weight, tuple(project["fonts"][weight]))
    font = ImageFont.truetype(path, size, index=index)
    if variation:
        try:
            font.set_variation_by_name(variation)
        except Exception:
            pass
    return font


def font_report(project: dict) -> dict:
    return {w: find_font(w, tuple(project["fonts"][w]))[0] for w in ("black", "bold")}
