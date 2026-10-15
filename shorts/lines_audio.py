"""문장별로 만든 음성을 정해진 쉼으로 이어 붙이고, 문장마다 정확한 시작/끝을 기록한다.

audio/lines/NN.wav (Typecast 문장별 원음) → audio/raw.wav + audio/lines.json
각 문장 파일 앞뒤의 무음은 잘라 내고(말 시작~끝만), 사이에 line_pause / question_pause 를 넣는다.
lines.json 의 시간은 raw.wav 기준이며, timing 단계에서 감속(rate_after)을 반영해 voice.wav 기준으로 바꾼다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .common import Episode, ShortsError, media_duration, need_tool, run, write_json

SR = 44100


def _speech_bounds(path: Path) -> tuple[float, float, float]:
    from .timing import detect_silences
    total = media_duration(path)
    s, e = 0.0, total
    for a, b in detect_silences(path, -40, 0.05):
        if a <= 0.02:
            s = b
        if b >= total - 0.02:
            e = a
    if e - s < 0.1:
        s, e = 0.0, total
    return s, e, total


def script_hash(ep: Episode) -> str:
    return hashlib.sha1("\n".join(l.text for l in ep.lines).encode("utf-8")).hexdigest()[:12]


def assemble(ep: Episode, files: list[Path]) -> dict:
    need_tool("ffmpeg")
    if len(files) != len(ep.lines):
        raise ShortsError("문장 음성 파일 수가 대사 수와 다릅니다")
    vc = ep.project["voice"]
    lp, qp = float(vc.get("line_pause", 0.45)), float(vc.get("question_pause", 0.6))
    work = ep.audio_dir / "lines"
    parts, entries, t = [], [], 0.0
    for i, (line, f) in enumerate(zip(ep.lines, files)):
        s, e, _ = _speech_bounds(f)
        seg = work / f"_trim_{i:02d}.wav"
        run(["ffmpeg", "-y", "-ss", f"{s:.4f}", "-to", f"{e:.4f}", "-i", f,
             "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", seg])
        d = media_duration(seg)
        entries.append({"index": i, "text": line.text, "start": round(t, 4), "end": round(t + d, 4)})
        parts.append(seg)
        t += d
        if i < len(files) - 1:
            gap = qp if line.text.rstrip().endswith("?") else lp
            sil = work / f"_gap_{i:02d}.wav"
            n = int(round(gap * SR))
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-af", f"atrim=end_sample={n}",
                 "-c:a", "pcm_s16le", sil])
            parts.append(sil)
            t += n / SR
    lst = work / "_concat.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "pcm_s16le", ep.raw_voice])
    raw_d = media_duration(ep.raw_voice)
    if abs(raw_d - t) > 0.05:
        raise ShortsError(f"이어 붙인 음성 길이({raw_d:.2f}초)가 계산값({t:.2f}초)과 다릅니다")
    info = {"script_hash": script_hash(ep), "line_pause": lp, "question_pause": qp, "lines": entries,
            "raw_duration": round(media_duration(ep.raw_voice), 4)}
    write_json(ep.audio_dir / "lines.json", info)
    for p in parts + [lst]:
        p.unlink(missing_ok=True)
    return info
