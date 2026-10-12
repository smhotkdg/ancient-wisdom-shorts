"""제목·자막 오버레이 렌더러 (layout v6).

각 줄을 외곽선까지 포함한 실제 픽셀 경계(ink bbox) 기준으로 가로 중앙에 놓고,
렌더 후 좌우 여백을 다시 측정해 기록한다. 패널/배경 박스는 그리지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from .fonts import load_font

DARK = (12, 12, 16, 255)


def _hex(c: str) -> tuple[int, int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255


def _segments(text: str, keywords: list[str], base: str, accent: str) -> list[tuple[str, str]]:
    """키워드 부분만 강조색으로 나눈다."""
    if not keywords:
        return [(text, base)]
    marks = [False] * len(text)
    for kw in sorted(set(k for k in keywords if k), key=len, reverse=True):
        start = 0
        while True:
            i = text.find(kw, start)
            if i < 0:
                break
            for j in range(i, i + len(kw)):
                marks[j] = True
            start = i + len(kw)
    segs: list[tuple[str, str]] = []
    for ch, m in zip(text, marks):
        col = accent if m else base
        if segs and segs[-1][1] == col:
            segs[-1] = (segs[-1][0] + ch, col)
        else:
            segs.append((ch, col))
    return segs


def _line_layer(text, font, colors_segments, outline, shear):
    """한 줄을 투명 레이어에 그린다. 반환: (RGBA 이미지, 줄 상자 높이, 기준 y)."""
    ascent, descent = font.getmetrics()
    width = int(font.getlength(text)) + 2 * outline
    pad = outline + int(abs(shear) * (ascent + descent)) + 8
    W, H = width + 2 * pad, ascent + descent + 2 * outline + 2 * 8
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = pad, 8 + outline
    # 1) 외곽선: 줄 전체를 한 번에 (구간 경계에 이음새가 생기지 않게)
    if outline > 0:
        d.text((x0, y0), text, font=font, fill=DARK, stroke_width=outline, stroke_fill=DARK)
    # 2) 채움: 구간별 색
    x = x0
    for seg, col in colors_segments:
        d.text((x, y0), seg, font=font, fill=_hex(col))
        x += font.getlength(seg)
    if shear:
        baseline = y0 + ascent
        # 출력 (x, y) ← 입력 (x + shear*(y - baseline), y) : 위쪽이 오른쪽으로 기운다
        img = img.transform(img.size, Image.AFFINE, (1, shear, -shear * baseline, 0, 1, 0),
                            resample=Image.BICUBIC)
    return img, ascent + descent + 2 * outline


def _ink_bbox(img: Image.Image, threshold: int = 8):
    a = img.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    return a.getbbox()


@dataclass
class Block:
    image: Image.Image          # 잘라낸 오버레이 (그림자 포함)
    x: int                      # 캔버스 위 배치 좌표
    y: int
    lines: list[dict]           # 줄별 측정값 (캔버스 좌표)
    font_px: int


def render_block(lines: list[str], *, project: dict, kind: str, keywords: list[str] | None = None,
                 canvas: tuple[int, int] | None = None) -> Block:
    """kind = 'title' | 'caption'"""
    lay = project["layout"][kind]
    W, H = canvas or (project["canvas"]["width"], project["canvas"]["height"])
    weight = lay["font_weight"]
    size = int(lay["font_px"])
    min_size = int(lay.get("min_font_px", size))
    max_w = lay["max_width"] * W
    shear = float(lay.get("italic_shear", 0.0))
    outline = int(lay["outline_px"])

    while True:
        font = load_font(project, weight, size)
        layers = []
        for i, text in enumerate(lines):
            if kind == "title":
                cols = lay["colors"]
                segs = [(text, cols[min(i, len(cols) - 1)])]
            else:
                segs = _segments(text, keywords or [], lay["color"], lay["keyword_color"])
            layer, box_h = _line_layer(text, font, segs, outline, shear)
            # 가운데 맞춤은 검수와 같은 기준(진한 픽셀, alpha ≥ 200)으로 잰다
            bbox = _ink_bbox(layer, threshold=199)
            layers.append((layer, box_h, bbox))
        widest = max(b[2] - b[0] for _, _, b in layers)
        if widest <= max_w or size <= min_size:
            break
        size -= 2

    gap = int(lay["line_gap_px"])
    cx, cy = lay["center"]
    block_h = sum(h for _, h, _ in layers) + gap * (len(layers) - 1)
    canvas_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top = cy - block_h / 2
    measured = []
    for (layer, box_h, bbox), text in zip(layers, lines):
        ink_w = bbox[2] - bbox[0]
        # 실제 픽셀 경계의 가운데를 cx 에 맞춘다 (홀수 폭은 왼쪽으로 내림)
        px = int(round(cx - ink_w / 2)) - bbox[0]
        py = int(round(top)) - 8
        canvas_img.alpha_composite(layer, (px, py))
        ink = [px + bbox[0], py + bbox[1], px + bbox[2], py + bbox[3]]
        left, right = ink[0], W - ink[2]
        measured.append({"text": text, "ink": ink, "left_margin": left, "right_margin": right,
                         "margin_diff_px": abs(left - right)})
        top += box_h + gap

    # 그림자: 텍스트 알파를 오프셋 + 블러
    sh = lay.get("shadow") or {}
    if sh:
        alpha = canvas_img.getchannel("A")
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        a = alpha.point(lambda v: int(v * float(sh.get("opacity", 0.6))))
        shadow.paste(dark, (int(sh.get("offset_px", 4)), int(sh.get("offset_px", 4))), a)
        shadow = shadow.filter(ImageFilter.GaussianBlur(float(sh.get("blur_px", 6)) / 2))
        shadow.alpha_composite(canvas_img)
        canvas_img = shadow

    full = _ink_bbox(canvas_img, threshold=2)
    crop = canvas_img.crop(full)
    return Block(image=crop, x=full[0], y=full[1], lines=measured, font_px=size)


def measure_rows(img: Image.Image, offset: tuple[int, int], W: int, threshold: int = 200) -> list[dict]:
    """렌더된 오버레이 PNG를 독립적으로 다시 잰다 (검수용).

    그림자(반투명)는 제외하고 진한 픽셀(글자+외곽선)만 본다. 빈 행으로 줄을 나눈다.
    """
    a = img.getchannel("A").point(lambda v: 255 if v >= threshold else 0)
    w, h = a.size
    px = a.load()
    rows = [any(px[x, y] for x in range(0, w, 1)) for y in range(h)]
    groups, start = [], None
    for i, on in enumerate(rows + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start > 6:
                groups.append((start, i))
            start = None
    out = []
    for gy0, gy1 in groups:
        b = a.crop((0, gy0, w, gy1)).getbbox()
        x0, x1 = offset[0] + b[0], offset[0] + b[2]
        out.append({"ink": [x0, offset[1] + gy0 + b[1], x1, offset[1] + gy0 + b[3]],
                    "left_margin": x0, "right_margin": W - x1, "margin_diff_px": abs(x0 - (W - x1))})
    return out


def text_width(text: str, project: dict, kind: str) -> float:
    lay = project["layout"][kind]
    font = load_font(project, lay["font_weight"], int(lay["font_px"]))
    return font.getlength(text) + 2 * int(lay["outline_px"])
