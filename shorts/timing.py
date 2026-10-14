"""음성 길이 측정과 대사별 시간 정렬.

1) raw.wav → voice.wav : 피치 유지 감속(rate_after, 기본 0.94)
2) 무음 구간 검출 → 대사 경계 N-1 개를 고른다
   (글자 수로 추정한 위치에 가깝고 길이가 긴 쉼을 동적 계획법으로 선택)
3) audio/timing.json : 대사별 시작/끝, 장면별 구간
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .common import Episode, ShortsError, media_duration, need_tool, run, write_json

SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
SIL_END = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")


def import_voice(ep: Episode, src: Path, force: bool = False) -> None:
    """다른 곳(예: Typecast 웹)에서 받은 음성 파일을 raw.wav 로 가져온다."""
    if ep.raw_voice.exists() and not force:
        raise ShortsError(f"이미 음성이 있습니다: {ep.raw_voice} (바꾸려면 --force)")
    ep.audio_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".wav":
        shutil.copyfile(src, ep.raw_voice)
    else:
        need_tool("ffmpeg")
        run(["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", "44100", ep.raw_voice])


def _postprocess(ep: Episode) -> None:
    need_tool("ffmpeg")
    rate = float(ep.project["voice"].get("rate_after", 1.0))
    af = f"atempo={rate}" if abs(rate - 1.0) > 1e-3 else "anull"
    run(["ffmpeg", "-y", "-i", ep.raw_voice, "-af", af, "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", ep.voice])


def detect_silences(path: Path, noise_db: float = -35, min_dur: float = 0.16) -> list[tuple[float, float]]:
    p = run(["ffmpeg", "-hide_banner", "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
             "-f", "null", "-"])
    log = p.stderr.decode("utf-8", "replace")
    out, start = [], None
    for ln in log.splitlines():
        m = SIL_START.search(ln)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = SIL_END.search(ln)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:
        out.append((start, media_duration(path)))
    return out


def _char_weight(text: str) -> int:
    return max(1, len(re.sub(r"\s", "", text)))


def align(lines: list[str], silences: list[tuple[float, float]], total: float) -> tuple[list[dict], dict]:
    # 말 시작/끝
    speech_start, speech_end = 0.0, total
    sil = list(silences)
    if sil and sil[0][0] <= 0.05:
        speech_start = sil.pop(0)[1]
    if sil and sil[-1][1] >= total - 0.05:
        speech_end = sil.pop()[0]
    interior = [s for s in sil if speech_start < s[0] and s[1] < speech_end]
    n = len(lines)
    need = n - 1
    warnings = []
    # 글자 비례 예상 경계 위치
    w = [_char_weight(t) for t in lines]
    span = speech_end - speech_start
    cum, expected = 0, []
    for wi in w[:-1]:
        cum += wi
        expected.append(speech_start + span * cum / sum(w))

    chosen: list[tuple[float, float]] = []
    if need > 0 and len(interior) >= need:
        M = len(interior)
        INF = float("inf")
        # cost: 예상 위치와의 거리(정규화) - 쉼 길이 보너스
        def cost(i, j):
            s, e = interior[j]
            mid = (s + e) / 2
            return abs(mid - expected[i]) / max(span, 1e-6) * 4.0 - min(e - s, 1.2) * 1.0

        dp = [[INF] * M for _ in range(need)]
        prev = [[-1] * M for _ in range(need)]
        for j in range(M):
            dp[0][j] = cost(0, j)
        for i in range(1, need):
            best, arg = INF, -1
            for j in range(M):
                if j - 1 >= 0 and dp[i - 1][j - 1] < best:
                    best, arg = dp[i - 1][j - 1], j - 1
                if best < INF:
                    dp[i][j] = best + cost(i, j)
                    prev[i][j] = arg
        j = min(range(M), key=lambda k: dp[need - 1][k])
        if dp[need - 1][j] == INF:
            raise ShortsError("대사 경계를 찾지 못했습니다")
        picks = [j]
        for i in range(need - 1, 0, -1):
            j = prev[i][j]
            picks.append(j)
        chosen = [interior[k] for k in reversed(picks)]
        method = "silence_dp"
    else:
        if need > 0:
            warnings.append(f"쉼이 부족합니다 (필요 {need}, 검출 {len(interior)}). 글자 비례로 나눴습니다 — 자막 시간을 확인하세요.")
        chosen = [(t, t) for t in expected]
        method = "proportional"

    out = []
    start = speech_start
    for i, text in enumerate(lines):
        if i < need:
            end, nxt = chosen[i]
        else:
            end, nxt = speech_end, speech_end
        out.append({"index": i, "text": text, "start": round(start, 3), "end": round(end, 3),
                    "pause_after": round(nxt - end, 3)})
        start = nxt
    meta = {"speech_start": round(speech_start, 3), "speech_end": round(speech_end, 3),
            "method": method, "warnings": warnings}
    return out, meta


def scene_plan(ep: Episode, timing: dict) -> list[dict]:
    """장면별 영상 구간. 컷은 앞 대사 뒤 쉼의 가운데에서 바꾼다."""
    proj = ep.project
    lead = float(proj["duration"]["lead_in_seconds"])
    tail = float(proj["duration"]["tail_seconds_min"])
    lines = timing["lines"]
    by_scene: dict[str, list[dict]] = {}
    for ln, src in zip(lines, ep.lines):
        by_scene.setdefault(src.scene, []).append(ln)
    order = [sc["id"] for sc in ep.scenes]
    starts = []
    for k, sid in enumerate(order):
        first = by_scene[sid][0]
        if k == 0:
            starts.append(0.0)
        else:
            prev_last = by_scene[order[k - 1]][-1]
            cut = prev_last["end"] + prev_last["pause_after"] / 2
            starts.append(round(lead + cut, 3))
    total = round(lead + timing["speech_end"] + tail, 3)
    extra = ep.data.get("extra_tail_seconds") or 0
    total = round(total + float(extra), 3)
    plan = []
    for k, sid in enumerate(order):
        end = starts[k + 1] if k + 1 < len(order) else total
        plan.append({"id": sid, "start": starts[k], "end": end, "duration": round(end - starts[k], 3),
                     "lines": [l["index"] for l in by_scene[sid]]})
    return plan


def part_bounds(ep: Episode, timing: dict, scene: dict, n_parts: int) -> list[tuple[float, float]]:
    """장면 안 클립 구간(영상 시간). 클립 수 = 대사 수이면 문장 사이 쉼 가운데에서 나눈다."""
    plan = {s["id"]: s for s in timing["scenes"]}[scene["id"]]
    s0, s1 = float(plan["start"]), float(plan["end"])
    if n_parts <= 1:
        return [(s0, s1)]
    lead = float(timing["lead_in"])
    lines = [timing["lines"][i] for i in plan["lines"]]
    if len(lines) == n_parts:
        cuts = [lead + l["end"] + l["pause_after"] / 2 for l in lines[:-1]]
    else:
        cuts = [s0 + (s1 - s0) * k / n_parts for k in range(1, n_parts)]
    edges = [s0, *cuts, s1]
    return [(round(a, 3), round(b, 3)) for a, b in zip(edges, edges[1:])]


def build_timing(ep: Episode) -> dict:
    if not ep.raw_voice.exists():
        raise ShortsError(f"음성이 없습니다: {ep.raw_voice}  (python aw.py tts 또는 python aw.py voice --file ...)")
    _postprocess(ep)
    total = media_duration(ep.voice)
    silences = detect_silences(ep.voice)
    lines, meta = align([l.text for l in ep.lines], silences, total)
    timing = {"voice_file": "audio/voice.wav", "voice_duration": round(total, 3),
              "rate_after": ep.project["voice"].get("rate_after", 1.0),
              "lead_in": float(ep.project["duration"]["lead_in_seconds"]),
              "lines": lines, **meta}
    timing["scenes"] = scene_plan(ep, timing)
    timing["video_duration"] = timing["scenes"][-1]["end"]
    lo, hi = ep.project["duration"]["target_seconds"]
    if not lo <= timing["video_duration"] <= hi:
        timing["warnings"].append(f"영상 길이 {timing['video_duration']:.1f}초가 목표 {lo}~{hi}초 밖입니다.")
    write_json(ep.timing_path, timing)
    return timing


def estimate(ep: Episode) -> dict:
    """음성 생성 전 길이 추정 (콘티 초안용)."""
    vc = ep.project["voice"]
    cps = float(vc["chars_per_second_raw"]) * float(vc.get("rate_after", 1.0))
    lead = float(ep.project["duration"]["lead_in_seconds"])
    pause = 0.45
    t = lead
    lines = []
    for l in ep.lines:
        d = _char_weight(l.text) / cps
        lines.append({"index": l.index, "text": l.text, "start": round(t - lead, 3), "end": round(t - lead + d, 3),
                      "pause_after": pause})
        t += d + pause
    timing = {"estimated": True, "lines": lines, "speech_start": 0.0,
              "speech_end": lines[-1]["end"], "lead_in": lead, "warnings": []}
    timing["scenes"] = scene_plan(ep, timing)
    timing["video_duration"] = timing["scenes"][-1]["end"]
    return timing
