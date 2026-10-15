"""Whisper 단어 타임스탬프로 대본 글자마다 실제 발음 시각을 찾는다 (강제 정렬).

- faster-whisper 가 설치된 PC 에서만 동작한다 (pip install faster-whisper). 첫 실행 때 모델을 내려받는다.
- 인식 결과의 글자를 대본 글자와 순서대로 맞춰(difflib), 대본 글자 하나하나의 시작 시각을 얻는다.
  인식이 틀린 글자는 앞뒤로 맞은 글자 시각 사이를 보간한다.
- 결과: 대사마다 start/end, 그리고 글자별 시작 시각(char_starts) → 자막 묶음 전환을 글자 단위로 맞춘다.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

NORM = re.compile(r"[\s,.?!…'\"“”‘’·\-/~:;()\[\]]")


def norm(s: str) -> str:
    return NORM.sub("", s)


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(path: Path, model_size: str = "small", prompt: str = "") -> list[tuple[str, float, float]]:
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(path), language="ko", word_timestamps=True, beam_size=5,
                                   vad_filter=False, condition_on_previous_text=False,
                                   initial_prompt=prompt[:200] or None)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append((w.word, float(w.start), float(w.end)))
    return words


def char_times(words: list[tuple[str, float, float]]) -> tuple[str, list[float], list[float]]:
    """인식 단어 → (글자열, 글자별 시작, 글자별 끝). 단어 시간을 글자 수로 나눈다."""
    text, st, en = [], [], []
    for w, a, b in words:
        cs = norm(w)
        if not cs:
            continue
        step = max(b - a, 0.02) / len(cs)
        for k, c in enumerate(cs):
            text.append(c)
            st.append(a + step * k)
            en.append(a + step * (k + 1))
    return "".join(text), st, en


def align_script(lines: list[str], words: list[tuple[str, float, float]]) -> tuple[list[dict], float]:
    """대본 줄 + 인식 단어 → 줄별 {start, end, char_starts}, 일치율."""
    script = "".join(norm(l) for l in lines)
    asr, st, en = char_times(words)
    sm = difflib.SequenceMatcher(None, script, asr, autojunk=False)
    s_start: list[float | None] = [None] * len(script)
    s_end: list[float | None] = [None] * len(script)
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            s_start[a + k] = st[b + k]
            s_end[a + k] = en[b + k]
        matched += size
    ratio = matched / max(1, len(script))
    # 맞지 않은 글자는 앞뒤 맞은 글자 사이를 선형 보간
    known = [i for i, v in enumerate(s_start) if v is not None]
    if not known:
        raise ValueError("인식 결과가 대본과 전혀 맞지 않습니다")
    for i in range(len(script)):
        if s_start[i] is not None:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is None:
            s_start[i] = s_end[i] = s_start[nxt]
        elif nxt is None:
            s_start[i] = s_end[i] = s_end[prev]
        else:
            frac = (i - prev) / (nxt - prev)
            s_start[i] = s_end[prev] + (s_start[nxt] - s_end[prev]) * frac
            s_end[i] = s_start[i]
    out, pos = [], 0
    for i, line in enumerate(lines):
        n = len(norm(line))
        cs = [round(t, 3) for t in s_start[pos:pos + n]]
        out.append({"index": i, "text": line, "start": cs[0], "end": round(max(s_end[pos:pos + n]), 3),
                    "char_starts": cs})
        pos += n
    # 단조 증가 보정 (보간 오차로 앞 줄 끝이 뒤 줄 시작을 넘지 않게)
    for a, b in zip(out, out[1:]):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    for a, b in zip(out, out[1:]):
        a["pause_after"] = round(b["start"] - a["end"], 3)
    out[-1]["pause_after"] = 0.0
    return out, ratio
