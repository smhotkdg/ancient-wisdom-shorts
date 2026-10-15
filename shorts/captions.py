"""대사를 화면 자막 묶음으로 나눈다.

규칙 (layout v6): 한 묶음은 최대 두 줄·28자·7어절, 줄 폭 74% 이내, 글자 크기는 줄이지 않는다.
의미 단위(쉼표/마침표/물음표)에서 먼저 나누고, 원문의 모든 단어를 빠짐없이 보여 준다.
episode.yaml 에서 captions 를 직접 쓰면 그대로 쓴다 (줄바꿈은 '/' 또는 '\\n').
"""
from __future__ import annotations

import re

from .common import Episode, ShortsError
from .textrender import text_width

PUNCT_SPLIT = re.compile(r"(?<=[,.?!…])\s+")
TRIM_END = ",."   # 줄 끝의 쉼표/마침표는 화면에서 뺀다 (?, ! 는 유지)
# 이런 끝말 뒤에서 끊으면 의미 단위가 자연스럽다 (조사·연결어미·종결어미)
GOOD_END = ("은", "는", "이", "가", "을", "를", "에", "에서", "에게", "의", "와", "과", "도", "만", "로",
            "고", "서", "면", "데", "며", "지만", "니다", "요", "죠", "까", "다", "게", "듯", "해", "야")


def _break_penalty(word: str) -> int:
    w = word.rstrip(",.?!…")
    if word and word[-1] in ",.?!…":
        return -4
    return 0 if w.endswith(GOOD_END) else 6


def _norm(s: str) -> str:
    return re.sub(r"[\s,.?!…'\"“”‘’·\-/]", "", s)


def _clean(line: str) -> str:
    line = line.strip()
    while line and line[-1] in TRIM_END:
        line = line[:-1].rstrip()
    return line


def _fits_line(text: str, project: dict) -> bool:
    W = project["canvas"]["width"]
    return text_width(text, project, "caption") <= project["layout"]["caption"]["max_width"] * W


def _two_lines(words: list[str], project: dict) -> list[str] | None:
    """한 묶음을 한 줄 또는 균형 잡힌 두 줄로. 불가능하면 None."""
    one = " ".join(words)
    if _fits_line(one, project):
        return [one]
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if _fits_line(a, project) and _fits_line(b, project):
            score = abs(len(a) - len(b)) + _break_penalty(words[i - 1])
            if best is None or score < best[0]:
                best = (score, [a, b])
    return best[1] if best else None


def _pack(words: list[str], project: dict) -> list[list[str]]:
    """단어 목록을 제한 안에 드는 묶음들로 나눈다."""
    cap = project["layout"]["caption"]
    max_chars, max_words = int(cap["max_chars"]), int(cap["max_words"])

    def ok(ws):
        text = _clean(" ".join(ws))
        return len(ws) <= max_words and len(text) <= max_chars and _two_lines(ws, project) is not None

    if ok(words):
        return [words]
    if len(words) == 1:
        raise ShortsError(f"한 단어가 자막 폭을 넘습니다: {words[0]}")
    # 의미 단위 끝말 + 가운데에 가까운 지점부터 나눠 본다
    order = sorted(range(1, len(words)),
                   key=lambda i: abs(i - len(words) / 2) * 2 + _break_penalty(words[i - 1]))
    for i in order:
        left, right = words[:i], words[i:]
        try:
            return _pack(left, project) + _pack(right, project)
        except ShortsError:
            continue
    raise ShortsError("자막을 나눌 수 없습니다: " + " ".join(words))


def split_line(text: str, project: dict) -> list[list[str]]:
    """대사 한 줄 → [[줄1, 줄2?], ...] 묶음 목록."""
    chunks: list[list[str]] = []
    raw = [p for p in PUNCT_SPLIT.split(text.strip()) if p]
    # '사실,' '그런데,' 처럼 아주 짧은 구절은 뒤 구절에 붙인다
    phrases: list[str] = []
    carry = ""
    for p in raw:
        p = (carry + " " + p).strip() if carry else p
        carry = ""
        if len(_norm(p)) <= 3 and p is not raw[-1]:
            carry = p
            continue
        phrases.append(p)
    if carry:
        phrases.append(carry)
    # 짧은 구절끼리는 합쳐 본다
    merged: list[str] = []
    for p in phrases:
        if merged:
            cand = merged[-1] + " " + p
            cap = project["layout"]["caption"]
            if len(cand) <= cap["max_chars"] // 2 + 2 and len(cand.split()) <= cap["max_words"]:
                merged[-1] = cand
                continue
        merged.append(p)
    for phrase in merged:
        for ws in _pack(phrase.split(), project):
            lines = _two_lines(ws, project)
            chunks.append([_clean(l) for l in lines])
    return chunks


def manual_chunks(line_text: str, caps: list[str], project: dict) -> list[list[str]]:
    out = []
    for c in caps:
        parts = [p.strip() for p in re.split(r"\s*/\s*|\n", str(c)) if p.strip()]
        if len(parts) > project["layout"]["caption"]["max_lines"]:
            raise ShortsError(f"자막은 최대 두 줄입니다: {c}")
        for p in parts:
            if not _fits_line(p, project):
                raise ShortsError(f"자막 줄이 폭 74%를 넘습니다: {p}")
        out.append([_clean(p) for p in parts])
    if _norm("".join("".join(x) for x in out)) != _norm(line_text):
        raise ShortsError(f"직접 쓴 자막이 대사와 다릅니다 (모든 단어가 들어가야 함):\n  대사: {line_text}\n  자막: {caps}")
    return out


def build_captions(ep: Episode) -> list[dict]:
    """대사별 자막 묶음 [{line, chunks:[[..]]}]."""
    out = []
    for line in ep.lines:
        if line.captions:
            chunks = manual_chunks(line.text, line.captions, ep.project)
        else:
            chunks = split_line(line.text, ep.project)
        out.append({"line": line.index, "scene": line.scene, "text": line.text, "chunks": chunks})
    return out


def time_chunks(captions: list[dict], timing: dict, offset: float, gap_fill: float = 0.6,
                lead: float = 0.0) -> list[dict]:
    """대사 구간 안에서 글자 수 비례로 묶음 시간을 나눈다. 반환 시간은 영상 기준(offset 포함)."""
    lines = {l["index"]: l for l in timing["lines"]}
    events = []
    for cap in captions:
        tl = lines[cap["line"]]
        s, e = tl["start"], tl["end"]
        weights = [max(1, len(_norm("".join(c)))) for c in cap["chunks"]]
        total = sum(weights)
        cuts, acc = [], 0
        cs = tl.get("char_starts")
        if cs and len(cs) == sum(len(_norm("".join(c))) for c in cap["chunks"]):
            # Whisper: 각 묶음의 첫 글자가 실제로 발음된 시각에 전환
            for w in weights[:-1]:
                acc += w
                cuts.append(cs[acc])
        else:
            # 무음 기반: 글자 비례 경계 → 근처 쉼이 끝나는 시각(다음 말 시작)으로 맞춘다 (±1.2초 안)
            pauses = [b for a, b in tl.get("pauses") or []]
            for w in weights[:-1]:
                acc += w
                t0 = s + (e - s) * acc / total
                near = [p for p in pauses if abs(p - t0) <= 1.2 and (not cuts or p > cuts[-1] + 0.4)]
                cuts.append(min(near, key=lambda p: abs(p - t0)) if near else t0)
        edges = [s, *cuts, e]
        for chunk, a, b in zip(cap["chunks"], edges, edges[1:]):
            events.append({"line": cap["line"], "scene": cap["scene"], "lines": chunk,
                           "start": round(max(0.0, a + offset - lead), 3), "end": round(b + offset - lead, 3)})
    # 짧은 공백은 다음 자막 시작까지 이어서 깜빡임을 없앤다
    for a, b in zip(events, events[1:]):
        if 0 < b["start"] - a["end"] <= gap_fill:
            a["end"] = b["start"]
    return events
