"""최종 합성 / 애니매틱.

장면 소스 → 1080×1920 24fps 장면 파일 → 이어 붙이기 → 제목·자막 오버레이 → 필재 + 효과음(+BGM) 믹스.

- Grok 클립: 가로세로 비율이 달라도 화면을 꽉 채우고 가운데 기준으로 자른다(좌우 대칭).
  장면보다 짧으면 최대 max_slowdown 배까지 느리게, 그래도 모자라면 마지막 프레임을 유지한다.
  클립 원음은 효과음으로 sfx_volume(기본 0.12) 만큼만 남긴다.
- 이미지만 있는 장면: 부드러운 느린 줌(상한 1.08배) — 강한 줌 금지.
- 애니매틱: 클립을 쓰지 않고 이미지(없으면 장면 설명 카드)로 템포만 확인한다.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from .captions import build_captions, time_chunks
from .common import (Episode, ShortsError, clip_parts, has_audio, media_duration, need_tool, run, say,
                     write_json)
from .fonts import load_font
from .textrender import render_block
from .timing import estimate, part_bounds

ENC_MID = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p",
           "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]


def _canvas(ep: Episode) -> tuple[int, int, int]:
    c = ep.project["canvas"]
    return int(c["width"]), int(c["height"]), int(c["fps"])


# ── 장면 소스 ─────────────────────────────────────────────

def _scene_image(ep: Episode, sid: str) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = ep.images_dir / f"{sid}{ext}"
        if p.exists():
            return p
    return None


def plan_segments(ep: Episode, timing: dict, animatic: bool) -> tuple[list[dict], list[str]]:
    """장면을 렌더 단위(세그먼트)로 나눈다. Grok 장면은 클립 수만큼, 나머지는 하나."""
    segs, notes = [], []
    for sc in ep.scenes:
        sid = sc["id"]
        img = _scene_image(ep, sid)
        parts = clip_parts(sc)
        if parts and not animatic:
            bounds = part_bounds(ep, timing, sc, len(parts))
            for part, (a, b) in zip(parts, bounds):
                clip = ep.clips_dir / part["file"]
                img = _scene_image(ep, part["image"]) or _scene_image(ep, sid)
                tag = f"{sid}-{part['n']}" if len(parts) > 1 else sid
                if clip.exists():
                    segs.append({"scene": sc, "tag": tag, "kind": "clip", "path": clip, "part": part, "start": a, "end": b})
                elif img is not None:
                    segs.append({"scene": sc, "tag": tag, "kind": "still", "path": img, "part": part, "start": a, "end": b})
                    notes.append(f"{tag}: clips/{part['file']} 없음 → 이미지로 대신합니다")
                else:
                    notes.append(f"{tag}: images/{sid}.png 와 clips/{part['file']} 가 모두 없습니다")
            continue
        plan = {p["id"]: p for p in timing["scenes"]}[sid]
        a, b = float(plan["start"]), float(plan["end"])
        if img is not None:
            segs.append({"scene": sc, "tag": sid, "kind": "still", "path": img, "part": None, "start": a, "end": b})
        elif animatic:
            segs.append({"scene": sc, "tag": sid, "kind": "card", "path": None, "part": None, "start": a, "end": b})
        else:
            notes.append(f"{sid}: images/{sid}.png 가 없습니다 (모두 없습니다)")
    return segs, notes


def _placeholder(ep: Episode, sc: dict, lines: list[str]) -> Image.Image:
    W, H, _ = _canvas(ep)
    img = Image.new("RGB", (W, H), (32, 30, 27))
    d = ImageDraw.Draw(img)
    for y in range(H):  # 은은한 세로 그라데이션
        v = int(26 + 22 * y / H)
        d.line([(0, y), (W, y)], fill=(v + 6, v + 3, v))
    big = load_font(ep.project, "black", 150)
    mid = load_font(ep.project, "bold", 40)
    sid = sc["id"].upper()
    w = d.textlength(sid, font=big)
    d.text(((W - w) / 2, 640), sid, font=big, fill=(226, 177, 60))
    y = 840
    for para in [sc.get("visual") or ""]:
        for ln in textwrap.wrap(para, 22)[:6]:
            lw = d.textlength(ln, font=mid)
            d.text(((W - lw) / 2, y), ln, font=mid, fill=(220, 214, 204))
            y += 56
    return img


def _render_frames(base: Image.Image, out: Path, duration: float, ep: Episode, motion: str) -> None:
    """정지 이미지를 부드럽게 움직여 장면 파일로 만든다 (Pillow 서브픽셀 변환 → ffmpeg)."""
    need_tool("ffmpeg")
    W, H, fps = _canvas(ep)
    zmax = float(ep.project["clips"]["still_zoom_max"]) if motion != "none" else 1.0
    bw, bh = base.size
    # 화면을 꽉 채우는 배율 (cover)
    cover = max(W / bw, H / bh)
    vw, vh = W / cover, H / cover            # 원본 좌표계에서 z=1 일 때 보이는 영역
    n = max(1, int(round(duration * fps)))
    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
           "-map", "0:v", "-map", "1:a", "-t", f"{duration:.3f}", *ENC_MID, str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            t = i / max(1, n - 1)
            if motion == "slow_zoom":
                z = 1 + (zmax - 1) * t
                cx, cy = bw / 2, bh / 2
            elif motion in ("pan_left", "pan_right"):
                z = (1 + zmax) / 2
                slack = (bw - vw / z) / 2
                dirn = -1 if motion == "pan_left" else 1
                cx, cy = bw / 2 + dirn * slack * (t - 0.5) * 2 * 0.9, bh / 2
            else:
                z, cx, cy = 1.0, bw / 2, bh / 2
            ww, hh = vw / z, vh / z
            box = (cx - ww / 2, cy - hh / 2, cx + ww / 2, cy + hh / 2)
            frame = base.transform((W, H), Image.EXTENT, box, resample=Image.BICUBIC)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        err = proc.stderr.read()
        if proc.wait() != 0:
            raise ShortsError("정지 장면 렌더 실패:\n" + err.decode("utf-8", "replace")[-1500:])
    finally:
        if proc.poll() is None:
            proc.kill()


def _render_clip(ep: Episode, sc: dict, clip: Path, duration: float, out: Path) -> dict:
    """sc: 장면 또는 클립 설정 (trim_start, sfx_volume, punch_in)."""
    W, H, fps = _canvas(ep)
    cfg = ep.project["clips"]
    trim = float(sc.get("trim_start") or 0.0)
    z = max(1.0, float(sc.get("punch_in") or 1.0))
    SW, SH = int(round(W * z / 2)) * 2, int(round(H * z / 2)) * 2
    avail = media_duration(clip) - trim
    if avail <= 0.2:
        raise ShortsError(f"{sc['id']}: trim_start 가 클립 길이보다 깁니다")
    speed = max(1.0, float(cfg.get("speed_up", 1.0)))
    if avail >= duration * speed:
        k = 1.0 / speed                      # 속도감: 넉넉하면 빠르게 재생
    elif avail >= duration:
        k = duration / avail                 # 남는 만큼만 빠르게
    else:
        k = min(duration / avail, float(cfg["max_slowdown"]))
    freeze = max(0.0, duration - avail * k)
    sharpen = float(cfg.get("upscale_sharpen", 0.0))
    vf = (f"[0:v]setpts={k:.5f}*PTS,fps={fps},"
          f"scale={SW}:{SH}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1"
          + (f",unsharp=5:5:{sharpen}:5:5:0" if sharpen > 0 else "")
          + f",tpad=stop_mode=clone:stop_duration={freeze + 0.5:.3f},trim=end_frame={int(round(duration * fps))},"
          f"setpts=PTS-STARTPTS,format=yuv420p[v]")
    vol = float(sc["sfx_volume"]) if sc.get("sfx_volume") is not None else ep.sfx_volume()
    cmd = ["ffmpeg", "-y", "-ss", f"{trim:.3f}", "-i", clip]
    if has_audio(clip) and vol > 0:
        tempo = f"atempo={1 / k:.5f}," if k > 1.001 else ""
        af = (f"[0:a]{tempo}volume={vol},aresample=48000,aformat=channel_layouts=stereo,"
              f"apad,atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[a]")
        amap = "[a]"
    else:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        af, amap = "", "1:a"
    fc = vf + (";" + af if af else "")
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap, "-t", f"{duration:.3f}", *ENC_MID, out]
    run(cmd)
    return {"clip_seconds_used": round(avail, 3), "slowdown": round(k, 3), "freeze_seconds": round(freeze, 3)}


# ── 메인 ─────────────────────────────────────────────────

def compose(ep: Episode, animatic: bool = False) -> dict:
    need_tool("ffmpeg")
    W, H, fps = _canvas(ep)
    timing = ep.timing()
    has_voice = timing is not None and ep.voice.exists()
    if not has_voice:
        if not animatic:
            raise ShortsError("음성/타이밍이 없습니다. 먼저 python aw.py tts (또는 voice) 를 실행하세요.")
        timing = estimate(ep)
        say("  (음성이 없어 추정 타이밍으로 애니매틱을 만듭니다 — 내레이션 없음)")

    segs, notes = plan_segments(ep, timing, animatic)
    bad = [n for n in notes if "모두 없습니다" in n]
    if bad:
        raise ShortsError("소스 파일이 없습니다:\n  " + "\n  ".join(bad))
    for n in notes:
        say("  [알림] " + n)

    tag = "animatic" if animatic else "final"
    work = ep.build_dir / tag
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("scene_*.mkv"):
        old.unlink()
    lines_by_scene: dict[str, list[str]] = {}
    for l in ep.lines:
        lines_by_scene.setdefault(l.scene, []).append(l.text)

    report = {"mode": tag, "scenes": []}
    parts = []
    # 세그먼트 경계를 프레임 격자에 맞춰 누적 오차를 없앤다
    total_frames = int(round(float(timing["video_duration"]) * fps))
    fb = [int(round(g["start"] * fps)) for g in segs] + [total_frames]
    by_scene: dict[str, dict] = {}
    for k, g in enumerate(segs):
        sc, sid = g["scene"], g["scene"]["id"]
        dur = (fb[k + 1] - fb[k]) / fps
        out = work / f"scene_{g['tag']}.mkv"
        info = {"tag": g["tag"], "kind": g["kind"], "duration": round(dur, 3),
                "source": str(g["path"].relative_to(ep.dir)) if g["path"] else None}
        say(f"  {g['tag']:6s} {dur:5.2f}초  {g['kind']}")
        if g["kind"] == "clip":
            settings = {"sfx_volume": sc.get("sfx_volume"),
                        **{k2: v for k2, v in (g["part"] or {}).items() if v is not None}}
            info.update(_render_clip(ep, settings, g["path"], dur, out))
        else:
            if g["kind"] == "still":
                base = Image.open(g["path"]).convert("RGB")
                motion = sc.get("still_motion") or ep.project["clips"]["still_motion"]
            else:
                base = _placeholder(ep, sc, lines_by_scene[sid])
                motion = "none"
            _render_frames(base, out, dur, ep, motion)
            info["motion"] = motion
        parts.append(out)
        entry = by_scene.setdefault(sid, {"id": sid, "duration": 0.0, "segments": []})
        entry["duration"] = round(entry["duration"] + dur, 3)
        entry["segments"].append(info)
    report["scenes"] = list(by_scene.values())

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")

    # ── 오버레이 ──
    ov_dir = work / "overlays"
    ov_dir.mkdir(exist_ok=True)
    overlays = []
    total = float(timing["video_duration"])
    title_lines = ep.data.get("title_lines")
    if ep.project["layout"]["title"]["enabled"] and title_lines:
        blk = render_block(list(title_lines), project=ep.project, kind="title", canvas=(W, H))
        p = ov_dir / "title.png"
        blk.image.save(p)
        overlays.append({"kind": "title", "png": p, "x": blk.x, "y": blk.y, "w": blk.image.width,
                         "h": blk.image.height, "start": 0.0, "end": total, "lines": blk.lines,
                         "font_px": blk.font_px})
    caps = build_captions(ep)
    events = time_chunks(caps, timing, offset=float(timing["lead_in"]),
                         lead=float((ep.project.get("timing") or {}).get("caption_lead", 0.0)))
    for i, ev in enumerate(events):
        blk = render_block(ev["lines"], project=ep.project, kind="caption",
                           keywords=ep.data.get("caption_keywords") or [], canvas=(W, H))
        p = ov_dir / f"cap_{i:03d}.png"
        blk.image.save(p)
        overlays.append({"kind": "caption", "png": p, "x": blk.x, "y": blk.y, "w": blk.image.width,
                         "h": blk.image.height, "start": ev["start"], "end": ev["end"], "lines": blk.lines,
                         "text": ev["lines"], "line": ev["line"], "font_px": blk.font_px})

    # ── 최종 ffmpeg ──
    out_dir = ep.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / ("animatic.mp4" if animatic else "final.mp4")
    a = ep.project["audio"]
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat]
    n_in = 1
    audio_labels = ["[0:a]"]
    fc = []
    if has_voice:
        cmd += ["-i", ep.voice]
        lead_ms = int(round(float(timing["lead_in"]) * 1000))
        fc.append(f"[{n_in}:a]adelay=delays={lead_ms}:all=1,volume={a['voice_volume']},"
                  f"aresample=48000,aformat=channel_layouts=stereo[vo]")
        audio_labels.append("[vo]")
        n_in += 1
    bgm = (ep.data.get("bgm_file") or a.get("bgm_file") or "").strip()
    if bgm:
        bgm_path = (ep.dir / bgm) if (ep.dir / bgm).exists() else (Path(__file__).resolve().parent.parent / bgm)
        if bgm_path.exists():
            cmd += ["-stream_loop", "-1", "-i", bgm_path]
            fc.append(f"[{n_in}:a]volume={a['bgm_volume']},aresample=48000,aformat=channel_layouts=stereo,"
                      f"atrim=duration={total:.3f}[bg]")
            audio_labels.append("[bg]")
            n_in += 1
        else:
            say(f"  [알림] BGM 파일 없음: {bgm}")
    first_ov = n_in
    for ov in overlays:
        cmd += ["-i", ov["png"]]
    vlabel = "[0:v]"
    jz = float((ep.project.get("pace") or {}).get("jump_zoom", 1.0))
    zoom_iv = _jump_zoom_intervals(events, [(fb[i] / fps, fb[i + 1] / fps) for i in range(len(segs))]) if jz > 1.001 else []
    if zoom_iv:
        ZW, ZH = int(round(W * jz / 2)) * 2, int(round(H * jz / 2)) * 2
        en = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in zoom_iv)
        fc.append(f"[0:v]split[jzbase][jzsrc];[jzsrc]scale={ZW}:{ZH}:flags=lanczos,crop={W}:{H}[jzz];"
                  f"[jzbase][jzz]overlay=0:0:enable='{en}'[jz]")
        vlabel = "[jz]"
    report["jump_zoom_intervals"] = len(zoom_iv)
    for k, ov in enumerate(overlays):
        nxt = f"[v{k}]"
        en = "" if ov["kind"] == "title" else f":enable='between(t,{ov['start']:.3f},{ov['end']:.3f})'"
        fc.append(f"{vlabel}[{first_ov + k}:v]overlay=x={ov['x']}:y={ov['y']}{en}{nxt}")
        vlabel = nxt
    fc.append(f"{vlabel}format=yuv420p[vout]")
    fo = float(a["fade_out_seconds"])
    lufs = a.get("loudness_lufs")
    norm = f"loudnorm=I={float(lufs)}:TP=-1.5:LRA=11,aresample=48000," if lufs is not None else ""
    fc.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:normalize=0:dropout_transition=0,"
              f"{norm}apad,atrim=duration={total:.3f},afade=t=out:st={max(0, total - fo):.3f}:d={fo}[aout]")
    br = int(ep.project["canvas"]["video_bitrate"])
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
            "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-profile:v", "high",
            "-b:v", str(br), "-maxrate", str(int(br * 1.3)), "-bufsize", str(br * 2), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", ep.project["canvas"]["audio_bitrate"], "-ar", "48000",
            "-movflags", "+faststart", final]
    say("  인코딩 중...")
    run(cmd)

    # ── 부산물: 자막 SRT, 오버레이 기록, 유튜브 문구 ──
    srt = out_dir / ("animatic.srt" if animatic else "final.srt")
    srt.write_text(_srt(events), encoding="utf-8")
    write_json(work / "overlays.json", [{**o, "png": str(Path(o["png"]).relative_to(ep.dir))} for o in overlays])
    report.update({"output": str(final.relative_to(ep.dir)), "duration": total, "voice": has_voice,
                   "captions": len(events), "sfx_volume": ep.sfx_volume(), "notes": notes})
    write_json(work / "report.json", report)
    if not animatic:
        _youtube(ep)
    return report


def _jump_zoom_intervals(events: list[dict], seg_bounds: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """같은 화면 구간(세그먼트) 안에서 자막이 바뀔 때마다 확대/원래를 번갈아. 세그먼트가 바뀌면 원래 크기로 시작."""
    out = []
    for a, b in seg_bounds:
        starts = sorted(e["start"] for e in events if a + 0.25 < e["start"] < b - 0.25)
        edges = [a, *starts, b]
        for i in range(1, len(edges) - 1, 2):      # 두 번째, 네 번째… 묶음 구간을 확대
            out.append((edges[i], edges[i + 1]))
    return out


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(events: list[dict]) -> str:
    return "\n".join(f"{i}\n{_ts(e['start'])} --> {_ts(e['end'])}\n" + "\n".join(e["lines"]) + "\n"
                     for i, e in enumerate(events, 1))


def youtube_text(ep: Episode) -> str:
    """유튜브 업로드용 문구: 추천 제목 + 설명(재미있는 본문 → 댓글 질문 → 재구성 안내) + 해시태그."""
    yt = ep.data.get("youtube") or {}
    lines = ["[추천 제목]"] + [f"- {t}" for t in yt.get("titles") or []]
    body = [(yt.get("description") or "").strip()]
    if yt.get("comment_question"):
        body.append("💬 " + yt["comment_question"].strip())
    disc = ((ep.project.get("youtube") or {}).get("disclaimer") or "").strip()
    if disc:
        body.append(disc)
    tags = yt.get("hashtags") or []
    if tags:
        body.append(" ".join(t if t.startswith("#") else "#" + t for t in tags))
    lines += ["", "[설명] (아래를 그대로 붙여 넣기)", "\n\n".join(b for b in body if b)]
    return "\n".join(lines).strip() + "\n"


def _youtube(ep: Episode) -> None:
    if not ep.data.get("youtube"):
        return
    ep.output_dir.mkdir(parents=True, exist_ok=True)
    (ep.output_dir / "youtube.txt").write_text(youtube_text(ep), encoding="utf-8")
