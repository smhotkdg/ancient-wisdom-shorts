"""렌더 후 검수.

- 파일: 1080×1920, 24fps, 음성 트랙, 길이
- 텍스트: 각 오버레이 PNG 를 다시 읽어 줄별 실제 픽셀(외곽선 포함, 그림자 제외)의
  좌우 여백 차 ≤ 2px, 허용 영역·최대 폭·UI 금지 영역 확인
- 자막: 대본의 모든 글자가 빠짐없이 나오는지, 겹치는 자막이 없는지
- 확인용 이미지: 장면 중간 프레임을 360px 폭으로 모은 output/check/sheet.jpg
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

from .common import Episode, ShortsError, ffprobe_json, run, write_json
from .textrender import measure_rows


def _norm(s: str) -> str:
    return re.sub(r"[\s,.?!…'\"“”‘’·\-/]", "", s)


def verify(ep: Episode, animatic: bool = False) -> dict:
    tag = "animatic" if animatic else "final"
    work = ep.build_dir / tag
    video = ep.output_dir / f"{tag}.mp4"
    if not video.exists():
        raise ShortsError(f"영상이 없습니다: {video}")
    ovs = json.loads((work / "overlays.json").read_text(encoding="utf-8"))
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    proj = ep.project
    W, H, fps = proj["canvas"]["width"], proj["canvas"]["height"], proj["canvas"]["fps"]
    lay = proj["layout"]
    tol = lay["horizontal_centering"]["tolerance_px"]
    checks, fails, warns = [], [], []

    def check(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        if not ok:
            fails.append(f"{name}: {detail}")

    # 파일
    info = ffprobe_json(video)
    vs = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    aus = [s for s in info["streams"] if s["codec_type"] == "audio"]
    num, den = (int(x) for x in vs["r_frame_rate"].split("/"))
    dur = float(info["format"]["duration"])
    check("해상도", (vs["width"], vs["height"]) == (W, H), f"{vs['width']}x{vs['height']}")
    check("프레임레이트", abs(num / den - fps) < 0.01, f"{num / den:.3f}")
    check("오디오 트랙", len(aus) == 1, f"{len(aus)}개")
    check("영상 길이", abs(dur - report["duration"]) < 0.15, f"{dur:.3f}초 (계획 {report['duration']:.3f})")
    tm = ep.timing() or {}
    if tm and not tm.get("estimated"):
        check("음성·자막 정렬 방식", tm.get("method") in ("whisper", "silence_rate_dp", "single"),
              f"{tm.get('method')} (구버전이면 python aw.py timing 으로 다시 계산)")
        warns.extend(tm.get("warnings") or [])
    lo, hi = proj["duration"]["target_seconds"]
    if not lo <= dur <= hi:
        warns.append(f"길이 {dur:.1f}초가 목표 {lo}~{hi}초 밖입니다")

    # 텍스트 오버레이
    worst = 0
    for ov in ovs:
        kind = ov["kind"]
        cfg = lay[kind]
        img = Image.open(ep.dir / ov["png"]).convert("RGBA")
        rows = measure_rows(img, (ov["x"], ov["y"]), W)
        label = "제목" if kind == "title" else f"자막 {'/'.join(ov.get('text') or [])}"
        if len(rows) != len(ov["lines"]):
            warns.append(f"{label}: 줄 구분 측정 {len(rows)}줄 ≠ {len(ov['lines'])}줄 — 렌더 시 기록값으로 판정")
            rows = ov["lines"]
        y0, y1 = cfg["band_y"]
        for r in rows:
            diff = r["margin_diff_px"]
            worst = max(worst, diff)
            ink = r["ink"]
            if diff > tol:
                fails.append(f"{label}: 가로 중앙 오차 {diff}px > {tol}px")
            if ink[1] < y0 or ink[3] > y1:
                fails.append(f"{label}: 허용 영역 {y0}~{y1} 밖 (y {ink[1]}~{ink[3]})")
            if ink[2] - ink[0] > cfg["max_width"] * W + 1:
                fails.append(f"{label}: 최대 폭 초과 ({ink[2] - ink[0]}px)")
            sz = lay["safe_zones"]
            if ink[1] < sz["top_px"] or ink[3] > H - sz["bottom_px"]:
                fails.append(f"{label}: 위/아래 UI 금지 영역 침범")
            rc = sz["right_column"]
            if ink[2] > rc[0] and ink[3] > rc[1]:
                fails.append(f"{label}: 오른쪽 버튼 영역 침범")
        if kind == "caption" and len(ov["lines"]) > cfg["max_lines"]:
            fails.append(f"{label}: 최대 {cfg['max_lines']}줄 초과")
    checks.append({"check": "가로 중앙 정렬", "pass": worst <= tol, "detail": f"최대 좌우 여백 차 {worst}px (허용 {tol}px)"})

    # 자막 원문 일치 / 겹침
    caps = [o for o in ovs if o["kind"] == "caption"]
    shown = _norm("".join("".join(o["text"]) for o in sorted(caps, key=lambda o: o["start"])))
    script = _norm("".join(l.text for l in ep.lines))
    check("자막 원문 일치", shown == script, "일치" if shown == script else f"자막 {len(shown)}자 / 대본 {len(script)}자")
    overlaps = [(a, b) for a, b in zip(caps, caps[1:]) if b["start"] < a["end"] - 1e-3]
    check("자막 겹침 없음", not overlaps, f"{len(overlaps)}건")
    check("텍스트 배경 패널 없음", lay["background_panel"] == "none", "설정상 패널 없음")
    check("상단 진행 칩 없음", lay["progress_chips"] == "none", "설정상 진행 칩 없음")
    checks.append({"check": "텍스트 영역·폭·UI 금지 영역", "pass": not any("영역" in f or "폭" in f for f in fails),
                   "detail": "통과" if not fails else "실패 항목 참조"})

    sheet = _contact_sheet(ep, video, report, tag)
    result = {"video": str(video.relative_to(ep.dir)), "pass": not fails, "checks": checks,
              "failures": fails, "warnings": warns + report.get("notes", []),
              "contact_sheet": str(sheet.relative_to(ep.dir))}
    write_json(ep.output_dir / f"{tag}-verification.json", result)
    return result


def _contact_sheet(ep: Episode, video: Path, report: dict, tag: str) -> Path:
    """장면마다 중간 프레임 하나씩, 360px 폭으로 모은다 (폰 화면 크기 확인용)."""
    out_dir = ep.output_dir / "check"
    out_dir.mkdir(parents=True, exist_ok=True)
    t = 0.0
    frames = []
    for sc in report["scenes"]:
        mid = t + sc["duration"] * 0.6
        t += sc["duration"]
        p = out_dir / f"{tag}_{sc['id']}.jpg"
        run(["ffmpeg", "-y", "-ss", f"{mid:.3f}", "-i", video, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "3", p])
        frames.append(Image.open(p).convert("RGB"))
    cols = min(5, len(frames))
    rows = (len(frames) + cols - 1) // cols
    w, h = frames[0].size
    sheet = Image.new("RGB", (cols * w + (cols + 1) * 8, rows * h + (rows + 1) * 8), (24, 24, 24))
    for i, f in enumerate(frames):
        sheet.paste(f, (8 + (i % cols) * (w + 8), 8 + (i // cols) * (h + 8)))
    path = out_dir / f"{tag}-sheet.jpg"
    sheet.save(path, quality=88)
    for p in out_dir.glob(f"{tag}_s*.jpg"):
        p.unlink()
    return path
