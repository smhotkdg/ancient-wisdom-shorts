"""가짜 소스로 전체 흐름을 시험한다 (Typecast·ChatGPT·Grok 사용 없음, 비용 0).

episodes/_selftest/ 에 만들고 Git 에는 올리지 않는다.
대사 사이 쉼이 있는 합성 '음성', 그라데이션 이미지, 테스트 패턴 클립을 만들어
타이밍 → 콘티 → 애니매틱 → 최종 합성 → 검수를 돌린다.
"""
from __future__ import annotations

import shutil
import wave

import numpy as np
from PIL import Image, ImageDraw

from .common import ROOT, load_episode, run, say

SPEC = """
id: "000"
title_lines: ["이집트 사람들은", "멘탈이 나갔습니다"]
hook: 시험용 에피소드
caption_keywords: [석상, 모래, 물]
characters:
  - id: worker
    name: 일꾼
    name_en: Egyptian worker
    description: a cheerful ancient Egyptian worker in a white linen kilt
scenes:
  - id: s01
    source: still
    lines:
      - "이집트 사람들은 멘탈이 나가버렸습니다."
      - "석상이 모래에 파묻혀 꿈쩍도 안 했거든요."
    visual: 썰매 위 석상, 모래에 박힌 앞부분
    image_prompt: A huge stone statue on a wooden sledge stuck in desert sand.
    characters: [worker]
  - id: s02
    source: grok
    lines:
      - "그런데 한 사람이 썰매 앞에 물을 붓기 시작합니다."
    visual: 일꾼이 항아리로 물을 붓는다
    image_prompt: A worker pours water from a clay jar onto the sand in front of the sledge.
    motion_prompt: The worker tilts the jar and water darkens the sand.
    camera: slow push in
    characters: [worker]
  - id: s03
    source: grok
    lines:
      - text: "젖은 모래는 단단해져서, 썰매가 훨씬 쉽게 미끄러졌죠."
        captions: ["젖은 모래는 단단해져서", "썰매가 훨씬 / 쉽게 미끄러졌죠"]
      - "물 한 바가지가 거대한 석상을 움직인 겁니다."
    visual: 썰매가 젖은 모래 위로 미끄러진다
    image_prompt: The sledge slides smoothly over dark wet sand pulled by workers.
    motion_prompt: Workers pull and the sledge glides forward.
    extra_clips:
      - motion_prompt: Close view of the sledge runners gliding on wet sand.
        punch_in: 1.1
youtube:
  titles: ["시험용 제목"]
  description: 시험용 설명
  hashtags: [시험]
"""


def _voice(path, lines, sr=48000):
    rng = np.random.default_rng(7)
    parts = [np.zeros(int(0.08 * sr))]
    for i, text in enumerate(lines):
        n_chars = len("".join(text.split()))
        dur = n_chars / 6.2
        t = np.arange(int(dur * sr)) / sr
        # 음절처럼 진폭이 출렁이는 톤 (중간 쉼표에서 짧은 쉼)
        env = 0.55 + 0.45 * np.sin(2 * np.pi * 4.5 * t) ** 2
        tone = 0.25 * env * np.sin(2 * np.pi * (180 + 30 * np.sin(2 * np.pi * 0.7 * t)) * t)
        tone += 0.01 * rng.standard_normal(len(t))
        if "," in text:
            cut = int(len(t) * 0.5)
            tone = np.concatenate([tone[:cut], np.zeros(int(0.22 * sr)), tone[cut:]])
        parts.append(tone)
        parts.append(np.zeros(int((0.55 if i < len(lines) - 1 else 0.3) * sr)))
    audio = np.concatenate(parts)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _image(path, label, hue):
    W, H = 1024, 1536  # ChatGPT 세로 이미지 크기 (2:3) — 9:16 으로 잘리는지 시험
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=(int(hue[0] * (0.6 + 0.4 * y / H)), int(hue[1] * (0.6 + 0.4 * y / H)), hue[2]))
    d.ellipse([W / 2 - 180, H / 2 - 180, W / 2 + 180, H / 2 + 180], outline=(255, 255, 255), width=10)
    d.line([(W / 2, 0), (W / 2, H)], fill=(255, 255, 255), width=4)   # 중앙선: 좌우 대칭 크롭 확인용
    d.text((40, 40), label, fill=(255, 255, 255))
    img.save(path)


def selftest():
    d = ROOT / "episodes" / "_selftest"
    if d.exists():
        shutil.rmtree(d)
    (d / "audio").mkdir(parents=True)
    (d / "images").mkdir()
    (d / "clips").mkdir()
    (d / "episode.yaml").write_text(SPEC.strip() + "\n", encoding="utf-8")
    ep = load_episode(d)
    say("1) 가짜 소스 만들기")
    _voice(ep.raw_voice, [l.text for l in ep.lines])
    _image(ep.images_dir / "s01.png", "s01", (200, 150, 90))
    _image(ep.images_dir / "s02.png", "s02", (90, 140, 200))
    _image(ep.images_dir / "s03.png", "s03", (120, 180, 110))
    _image(ep.images_dir / "char_worker.png", "char", (180, 180, 180))
    # Grok 대신: 720×1280 4초 테스트 패턴 + 효과음 (장면보다 짧게 → 감속/정지 처리 시험)
    for name, freq in (("s02.mp4", 660), ("s03-2.mp4", 440)):   # s03-1 은 일부러 비움 → 이미지 대체 시험
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=24:duration=6",
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=6", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", ep.clips_dir / name])
    from .compose import compose
    from .conti import write as write_conti
    from .timing import build_timing
    from .verify import verify
    say("2) 타이밍")
    t = build_timing(ep)
    say(f"   음성 {t['voice_duration']:.2f}초 · {t['method']} · 영상 {t['video_duration']:.2f}초")
    for ln in t["lines"]:
        say(f"   대사{ln['index']} {ln['start']:.2f}–{ln['end']:.2f}")
    say("3) 콘티")
    write_conti(ep)
    say("4) 애니매틱")
    compose(ep, animatic=True)
    say("5) 최종 합성")
    compose(ep, animatic=False)
    say("6) 검수")
    res = verify(ep)
    for c in res["checks"]:
        say(f"   {'✓' if c['pass'] else '✗'} {c['check']}: {c['detail']}")
    for f in res["failures"]:
        say(f"   ✗ {f}")
    say("SELFTEST " + ("통과" if res["pass"] else "실패") + f" — {d.relative_to(ROOT)}/output/")
    return res
