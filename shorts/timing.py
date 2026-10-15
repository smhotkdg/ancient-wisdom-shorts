"""음성 길이 측정과 대사별 시간 정렬.

1) raw.wav → voice.wav : 피치 유지 감속(rate_after, 기본 0.94)
2) 무음 구간 검출 → 대사 경계 N-1 개를 고른다
   (글자 수로 추정한 위치에 가깝고 길이가 긴 쉼을 동적 계획법으로 선택)
3) audio/timing.json : 대사별 시작/끝, 장면별 구간
"""
from __future__ import annotations

import math
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
    (ep.audio_dir / "lines.json").unlink(missing_ok=True)   # 통파일 음성이므로 문장별 정보는 무효
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
    _tighten_pauses(ep)


def _tighten_pauses(ep: Episode) -> None:
    """속도감: max_pause 보다 긴 쉼은 가운데를 잘라 max_pause 로 줄인다. 말소리는 건드리지 않는다."""
    mp = float(ep.project["voice"].get("max_pause", 0) or 0)
    if mp <= 0:
        return
    import wave
    import numpy as np
    sil = detect_silences(ep.voice, -40, mp + 0.02)
    with wave.open(str(ep.voice), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype="<i2")
    keep, pos, removed = [], 0, 0.0
    total = n / sr
    for s0, e0 in sil:
        if s0 <= 0.01:                     # 앞 여백은 0.05초만 남김
            cut_a, cut_b = 0, max(0, int((e0 - 0.05) * sr))
        elif e0 >= total - 0.01:           # 끝 여백은 그대로
            continue
        else:
            half = mp / 2
            cut_a, cut_b = int((s0 + half) * sr), int((e0 - half) * sr)
        if cut_b > cut_a:
            keep.append(a[pos:cut_a])
            pos = cut_b
            removed += (cut_b - cut_a) / sr
    keep.append(a[pos:])
    out = np.concatenate(keep)
    with wave.open(str(ep.voice), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(out.astype("<i2").tobytes())
    ep.audio_dir.joinpath("pace.json").write_text(
        '{"max_pause": %s, "removed_seconds": %.3f}' % (mp, removed), encoding="utf-8")


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


def _commas(text: str) -> int:
    return len(re.findall(r"[,·…]", text))


def align(lines: list[str], silences: list[tuple[float, float]], total: float) -> tuple[list[dict], dict]:
    """대사 경계 찾기.

    후보 = 말 중간의 쉼(무음). 문장 끝 쉼과 쉼표 쉼이 비슷하게 길 때 쉼만 보고 고르면 경계를 잘못 잡는다
    (예: 12자 문장이 5초로 잡힘). 그래서 각 문장 길이가 '글자 수 × 말하는 속도 + 쉼표 쉼'에
    맞는지(로그 비율 제곱)를 비용으로 넣고, 쉼 길이는 보조 점수로만 쓴다. 속도는 두 번 다시 추정한다.
    """
    speech_start, speech_end = 0.0, total
    sil = list(silences)
    if sil and sil[0][0] <= 0.05:
        speech_start = sil.pop(0)[1]
    if sil and sil[-1][1] >= total - 0.05:
        speech_end = sil.pop()[0]
    interior = [x for x in sil if speech_start < x[0] and x[1] < speech_end]
    n, need = len(lines), len(lines) - 1
    chars = [_char_weight(t) for t in lines]
    commas = [_commas(t) for t in lines]
    warnings: list[str] = []
    span = speech_end - speech_start
    M = len(interior)

    if need == 0:
        chosen, method = [], "single"
    elif M < need:
        warnings.append(f"쉼이 부족합니다 (필요 {need}, 검출 {M}). 글자 비례로 나눴습니다 — 자막 시간을 확인하세요.")
        cum, chosen = 0, []
        for c in chars[:-1]:
            cum += c
            t = speech_start + span * cum / sum(chars)
            chosen.append((t, t))
        method = "proportional"
    else:
        comma_pause, line_pause = 0.30, 0.60
        rate = max(0.05, (span - need * line_pause - sum(commas) * comma_pause) / sum(chars))
        INF = float("inf")
        for _ in range(2):
            def seg_cost(i, a, b):
                dur = b - a
                if dur <= 0.15:
                    return INF
                exp = chars[i] * rate + commas[i] * comma_pause
                return 6.0 * math.log(dur / exp) ** 2

            starts = [x[1] for x in interior]
            ends = [x[0] for x in interior]
            bonus = [-0.5 * min(x[1] - x[0], 1.2) for x in interior]
            # dp[i][j]: i번째 경계를 쉼 j 로 골랐을 때 대사 0..i 까지의 최소 비용
            dp = [[INF] * M for _ in range(need)]
            prev = [[-1] * M for _ in range(need)]
            for j in range(M):
                dp[0][j] = seg_cost(0, speech_start, ends[j]) + bonus[j]
            for i in range(1, need):
                for j in range(i, M):
                    best, arg = INF, -1
                    for k in range(i - 1, j):
                        if dp[i - 1][k] == INF:
                            continue
                        c = dp[i - 1][k] + seg_cost(i, starts[k], ends[j])
                        if c < best:
                            best, arg = c, k
                    if arg >= 0:
                        dp[i][j] = best + bonus[j]
                        prev[i][j] = arg
            last = [dp[need - 1][j] + seg_cost(n - 1, starts[j], speech_end) for j in range(M)]
            j = min(range(M), key=lambda k: last[k])
            if last[j] == INF:
                raise ShortsError("대사 경계를 찾지 못했습니다")
            picks = [j]
            for i in range(need - 1, 0, -1):
                j = prev[i][j]
                picks.append(j)
            chosen = [interior[k] for k in reversed(picks)]
            # 고른 경계로 말하는 속도를 다시 추정
            edges = [speech_start] + [c[1] for c in chosen]
            ends_ = [c[0] for c in chosen] + [speech_end]
            talk = sum(e - s0 for s0, e in zip(edges, ends_)) - sum(commas) * comma_pause
            rate = max(0.05, talk / sum(chars))
        method = "silence_rate_dp"

    out = []
    start = speech_start
    for i, text in enumerate(lines):
        end, nxt = (chosen[i] if i < need else (speech_end, speech_end))
        out.append({"index": i, "text": text, "start": round(start, 3), "end": round(end, 3),
                    "pause_after": round(nxt - end, 3)})
        start = nxt
    # 이상치 경고: 글자당 시간이 평균의 0.6배 미만 / 1.6배 초과
    per = [(l["end"] - l["start"] - commas[i] * 0.3) / chars[i] for i, l in enumerate(out)]
    avg = sum(per) / len(per)
    odd = [i for i, v in enumerate(per) if v < avg * 0.55 or v > avg * 1.9]
    if odd:
        warnings.append("말하는 속도가 튀는 대사가 있습니다 (경계 오류 가능): "
                        + ", ".join(f"{i}번 {per[i]:.3f}s/자" for i in odd) + " — aw.py timing 결과를 확인하세요.")
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


def _per_line_timing(ep: Episode) -> list[dict] | None:
    """문장별 생성 음성(audio/lines.json)이 현재 대본과 같으면 정확한 문장 시간을 쓴다 (voice.wav 기준)."""
    p = ep.audio_dir / "lines.json"
    if not p.exists() or not ep.project["voice"].get("per_line"):
        return None
    import json
    from .lines_audio import script_hash
    info = json.loads(p.read_text(encoding="utf-8"))
    if info.get("script_hash") != script_hash(ep) or len(info["lines"]) != len(ep.lines):
        return None
    rate = float(ep.project["voice"].get("rate_after", 1.0))
    out = []
    for e in info["lines"]:
        out.append({"index": e["index"], "text": e["text"], "start": round(e["start"] / rate, 3),
                    "end": round(e["end"] / rate, 3)})
    for a, b in zip(out, out[1:]):
        a["pause_after"] = round(b["start"] - a["end"], 3)
    out[-1]["pause_after"] = 0.0
    return out


def _snap_to_speech(lines: list[dict], silences: list[tuple[float, float]]) -> list[dict]:
    """Whisper 는 쉼 뒤 첫 단어의 시작을 앞 단어 끝(쉼 시작)으로 잡는다 → 자막이 목소리보다 먼저 뜬다.
    단어 첫 글자의 시작이 무음 구간 안(또는 바로 앞)에 있으면 그 무음이 끝나는 곳(실제 말 시작)으로 옮긴다."""
    from .asr import norm
    last = 0.0
    for ln in lines:
        heads, k, prev = {}, 0, ""           # 단어 첫 글자 위치 → 앞 단어가 쉼표로 끝났는지
        for w in ln["text"].split():
            if norm(w):
                heads[k] = k == 0 or bool(re.search(r"[,…]$", prev))
                k += len(norm(w))
                prev = w
        cs = []
        for i, c in enumerate(ln["char_starts"]):
            if i in heads:
                if heads[i]:
                    # 문장 첫 단어·쉼표 뒤 단어: 앞에 쉼이 있어야 한다. Whisper 는 이 단어를 쉼보다
                    # 0.5초 가까이 앞에 두기도 하므로, 근처에서 가장 긴 쉼의 끝을 말 시작으로 본다
                    near = [(b - a, -abs(b - c), b) for a, b in silences if c - 0.4 <= a <= c + 0.5]
                    if near:
                        c = max(near)[2]
                else:
                    for a, b in silences:
                        if a - 0.12 <= c < b:   # 쉼 바로 앞(0.12초 이내)이나 쉼 안에서 시작하면 쉼 끝으로
                            c = b
                            break
            last = max(last, c)
            cs.append(round(last, 3))
        ln["char_starts"] = cs
        ln["start"] = cs[0]
        ln["end"] = max(ln["end"], cs[-1])
    for a, b in zip(lines, lines[1:]):
        # 앞 줄 끝은 다음 줄 시작 전 무음이 시작되는 곳으로
        gap = next((x for x, y in silences if a["end"] - 0.3 <= x < b["start"] and y >= b["start"] - 0.02), None)
        a["end"] = round(min(b["start"], gap if gap is not None else a["end"]), 3)
        a["pause_after"] = round(b["start"] - a["end"], 3)
    lines[-1]["pause_after"] = 0.0
    return lines


def build_timing(ep: Episode) -> dict:
    if not ep.raw_voice.exists():
        raise ShortsError(f"음성이 없습니다: {ep.raw_voice}  (python aw.py tts 또는 python aw.py voice --file ...)")
    _postprocess(ep)
    total = media_duration(ep.voice)
    texts = [l.text for l in ep.lines]
    cfg = ep.project.get("timing") or {}
    engine = cfg.get("engine", "auto")
    lines = meta = None
    warn = None
    per_line = _per_line_timing(ep)
    if per_line is not None:
        lines = per_line
        meta = {"speech_start": lines[0]["start"], "speech_end": lines[-1]["end"], "method": "per_line",
                "warnings": []}
        # 문장 안 자막 전환용 글자 시각: Whisper 가 있으면 사용
        if engine in ("auto", "whisper"):
            from . import asr
            if asr.available():
                try:
                    al, ratio = asr.transcribe_align(ep.voice, texts, cfg.get("whisper_model", "small"))
                    if ratio >= float(cfg.get("min_match", 0.6)):
                        for ln, w in zip(lines, al):
                            # 문장 경계는 정확한 값 유지, 글자 시각은 그 안으로 제한
                            ln["char_starts"] = [min(max(c, ln["start"]), ln["end"]) for c in w["char_starts"]]
                        meta["method"] = "per_line+whisper"
                        meta["match_ratio"] = round(ratio, 3)
                except Exception as exc:
                    meta["warnings"].append(f"Whisper 실행 실패({type(exc).__name__}) — 문장 안 자막은 쉼 기준으로 나눕니다.")
        if "char_starts" not in lines[0]:
            fine = detect_silences(ep.voice, -35, 0.12)
            for ln in lines:
                ln["pauses"] = [[round(x, 3), round(y, 3)] for x, y in fine if ln["start"] + 0.2 < x and y < ln["end"] - 0.2]
    elif engine in ("auto", "whisper"):
        from . import asr
        if asr.available():
            try:
                al, ratio = asr.transcribe_align(ep.voice, texts, cfg.get("whisper_model", "small"))
            except Exception as exc:  # 모델 다운로드 실패 등
                al, ratio = None, 0.0
                warn = f"Whisper 실행 실패({type(exc).__name__}) — 무음 기반 정렬로 대체했습니다."
            if al and ratio >= float(cfg.get("min_match", 0.6)):
                lines = _snap_to_speech(al, detect_silences(ep.voice, -35, 0.05))
                meta = {"speech_start": al[0]["start"], "speech_end": al[-1]["end"], "method": "whisper",
                        "match_ratio": round(ratio, 3), "warnings": []}
                if ratio < 0.8:
                    meta["warnings"].append(f"인식 일치율 {ratio:.0%} — 자막 시간을 한 번 확인하세요.")
            elif al:
                warn = f"Whisper 인식 일치율 {ratio:.0%}가 낮아 무음 기반 정렬로 대체했습니다."
        elif engine == "whisper":
            raise ShortsError("timing.engine 이 whisper 인데 faster-whisper 가 없습니다: pip install faster-whisper")
    if lines is None:
        silences = detect_silences(ep.voice)
        lines, meta = align(texts, silences, total)
        if warn:
            meta["warnings"].insert(0, warn)
        # 문장 안 쉼(쉼표 등) — 자막 묶음 전환을 실제 쉼 끝(다음 말 시작)에 맞추는 데 쓴다
        fine = detect_silences(ep.voice, -35, 0.12)
        for ln in lines:
            ln["pauses"] = [[round(a, 3), round(b, 3)] for a, b in fine if ln["start"] + 0.2 < a and b < ln["end"] - 0.2]
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
    mp = float(vc.get("max_pause", 0) or 0)
    pause = min(0.45, mp) if mp > 0 else 0.45
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
