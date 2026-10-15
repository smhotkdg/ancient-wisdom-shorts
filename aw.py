#!/usr/bin/env python3
"""ancient-wisdom-shorts 명령 도구.

  python aw.py doctor                  이 PC 환경 점검 (ffmpeg, 폰트, 패키지, .env)
  python aw.py new <slug> [--id 001]   새 에피소드 폴더 만들기
  python aw.py script <ep>             대본·글자 수·예상 길이
  python aw.py captions <ep>           화면 자막 나눔 미리보기
  python aw.py story <ep>              스토리형 대본 점검 (주인공·전환어·나열 여부·구조 순서)
  python aw.py check-voice             Typecast 인증과 필재 확인 (생성 없음, 크레딧 0)
  python aw.py tts <ep> [--force]      필재 음성 생성(크레딧 사용) → 타이밍
  python aw.py voice <ep> --file F     다른 곳에서 받은 음성 가져오기 → 타이밍
  python aw.py timing <ep>             음성 타이밍 다시 계산
  python aw.py conti <ep>              한 장 콘티 conti.html 만들기
  python aw.py animatic <ep>           이미지(없으면 설명 카드)로 가편집 → 검수
  python aw.py compose <ep>            최종 합성 → 검수
  python aw.py youtube <ep>            유튜브 제목·설명만 다시 만들기 (output/youtube.txt)
  python aw.py verify <ep>             검수만 다시
  python aw.py status <ep>             무엇이 준비됐고 무엇이 빠졌는지
  python aw.py selftest                가짜 소스로 전체 흐름 시험

<ep> 는 에피소드 폴더 경로 또는 번호(예: 001).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from shorts.common import ROOT, ShortsError, fail, load_episode, load_project, say  # noqa: E402


def resolve_ep(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    matches = sorted((ROOT / "episodes").glob(f"{arg}*"))
    matches = [m for m in matches if (m / "episode.yaml").exists()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ShortsError(f"에피소드를 찾을 수 없습니다: {arg}")
    raise ShortsError(f"여러 에피소드가 해당합니다: {', '.join(m.name for m in matches)}")


def cmd_doctor(_):
    import importlib
    ok = True
    for mod in ("yaml", "PIL", "numpy"):
        try:
            importlib.import_module(mod)
            say(f"  ✓ python 패키지 {mod}")
        except ImportError:
            ok = False
            say(f"  ✗ python 패키지 {mod} 없음 → pip install -r requirements.txt")
    from shorts import asr
    say(f"  {'✓' if asr.available() else '·'} faster-whisper "
        + ("(자막 싱크: 음성 인식 정렬)" if asr.available() else "없음 → 무음 기반 정렬. 정확한 싱크: pip install faster-whisper"))
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool):
            say(f"  ✓ {tool}")
        else:
            ok = False
            say(f"  ✗ {tool} 없음 (Windows: winget install Gyan.FFmpeg)")
    try:
        from shorts.fonts import font_report
        for w, path in font_report(load_project()).items():
            say(f"  ✓ 폰트 {w}: {path}")
    except ShortsError as e:
        ok = False
        say(f"  ✗ {e}")
    env = ROOT / ".env"
    say(f"  {'✓' if env.exists() else '·'} .env {'있음' if env.exists() else '없음 (음성 생성할 PC에만 필요)'}")
    say("점검 통과" if ok else "부족한 항목을 설치하세요")


def cmd_new(a):
    eps = ROOT / "episodes"
    nums = [int(p.name[:3]) for p in eps.glob("[0-9][0-9][0-9]-*") if p.name[:3].isdigit()]
    num = a.id or f"{(max(nums) + 1) if nums else 1:03d}"
    d = eps / f"{num}-{a.slug}"
    if d.exists():
        raise ShortsError(f"이미 있습니다: {d}")
    shutil.copytree(ROOT / "templates" / "episode", d)
    spec = d / "episode.yaml"
    spec.write_text(spec.read_text(encoding="utf-8").replace("{{ID}}", num).replace("{{SLUG}}", a.slug),
                    encoding="utf-8")
    say(f"만들었습니다: {d.relative_to(ROOT)}")


def cmd_script(a):
    from shorts.timing import estimate
    ep = load_episode(resolve_ep(a.ep))
    est = estimate(ep)
    n = sum(len("".join(l.text.split())) for l in ep.lines)
    for l in ep.lines:
        say(f"  {l.scene}  {l.text}")
    say(f"\n공백 제외 {n}자 · Typecast 크레딧 약 {len(ep.script_text())} · 예상 영상 {est['video_duration']:.1f}초")
    for s in est["scenes"]:
        say(f"  {s['id']} {s['duration']:.1f}초")


def cmd_captions(a):
    from shorts.captions import build_captions
    ep = load_episode(resolve_ep(a.ep))
    for cap in build_captions(ep):
        say(f"{cap['scene']}  {cap['text']}")
        for c in cap["chunks"]:
            say("      " + "  /  ".join(c))


def cmd_story(a):
    from shorts.story import check
    res = check(load_episode(resolve_ep(a.ep)))
    for r in res["results"]:
        say(f"  {'✓' if r['pass'] else '·'} {r['check']}: {r['detail']}")
    say("  흐름: " + "  ".join(f"{t['scene']}({t['beat']} {t['start']:.0f}s)" for t in res["timeline"]))
    for t in res["tips"]:
        say(f"  [제안] {t}")
    say("스토리 점검 통과" if res["pass"] else "스토리 보강 필요 — .claude/skills/shorts-story/SKILL.md 참고")


def cmd_youtube(a):
    from shorts.compose import _youtube
    ep = load_episode(resolve_ep(a.ep))
    _youtube(ep)
    say((ep.output_dir / "youtube.txt").read_text(encoding="utf-8"))


def cmd_check_voice(_):
    from shorts import typecast
    say(str(typecast.check(load_project())))


def _after_voice(ep):
    from shorts.timing import build_timing
    t = build_timing(ep)
    extra = f" · 일치율 {t['match_ratio']:.0%}" if t.get("match_ratio") is not None else ""
    say(f"음성 {t['voice_duration']:.2f}초 · 정렬 방식 {t['method']}{extra} · 영상 {t['video_duration']:.2f}초")
    for s in t["scenes"]:
        say(f"  {s['id']} {s['start']:6.2f}–{s['end']:6.2f}  ({s['duration']:.2f}초)")
    for w in t["warnings"]:
        say(f"  [주의] {w}")


def cmd_tts(a):
    from shorts import typecast
    ep = load_episode(resolve_ep(a.ep))
    info = typecast.generate(ep, force=a.force)
    say(f"필재 생성 완료: {info['characters']}자")
    _after_voice(ep)


def cmd_voice(a):
    from shorts.timing import import_voice
    ep = load_episode(resolve_ep(a.ep))
    import_voice(ep, Path(a.file), force=a.force)
    _after_voice(ep)


def cmd_timing(a):
    _after_voice(load_episode(resolve_ep(a.ep)))


def cmd_conti(a):
    from shorts import conti
    ep = load_episode(resolve_ep(a.ep))
    say(f"콘티: {conti.write(ep)}")


def _print_verify(res):
    for c in res["checks"]:
        say(f"  {'✓' if c['pass'] else '✗'} {c['check']}: {c['detail']}")
    for f in res["failures"]:
        say(f"  ✗ {f}")
    for w in res["warnings"]:
        say(f"  · {w}")
    say(f"  확인용 이미지: {res['contact_sheet']}")
    say("검수 통과" if res["pass"] else "검수 실패")


def cmd_compose(a, animatic=False):
    from shorts.compose import compose
    from shorts.verify import verify
    ep = load_episode(resolve_ep(a.ep))
    rep = compose(ep, animatic=animatic)
    say(f"완료: {ep.dir.name}/{rep['output']} ({rep['duration']:.2f}초, 자막 {rep['captions']}개)")
    _print_verify(verify(ep, animatic=animatic))


def cmd_verify(a):
    from shorts.verify import verify
    ep = load_episode(resolve_ep(a.ep))
    _print_verify(verify(ep, animatic=a.animatic))


def cmd_status(a):
    ep = load_episode(resolve_ep(a.ep))
    def mark(p):
        return "✓" if p.exists() else "·"
    say(f"{ep.slug}  ({ep.data.get('status', '?')})")
    say(f"  {mark(ep.raw_voice)} 음성   {mark(ep.timing_path)} 타이밍   {mark(ep.dir / 'conti.html')} 콘티")
    for c in ep.data.get("characters") or []:
        say(f"  {mark(ep.images_dir / ('char_' + c['id'] + '.png'))} 캐릭터 char_{c['id']}.png")
    from shorts.common import clip_parts
    for sc in ep.scenes:
        sid = sc["id"]
        img = any((ep.images_dir / f"{sid}{e}").exists() for e in (".png", ".jpg", ".jpeg", ".webp"))
        parts = clip_parts(sc)
        clips = "  ".join(f"{p['file']} {'✓' if (ep.clips_dir / p['file']).exists() else '·'}" for p in parts)
        say(f"  {sid}  이미지 {'✓' if img else '·'}  " + (clips if parts else "(정지 장면)"))
    say(f"  {mark(ep.output_dir / 'animatic.mp4')} 애니매틱   {mark(ep.output_dir / 'final.mp4')} 최종")


def cmd_selftest(_):
    from shorts.selftest import selftest
    selftest()


def main():
    p = argparse.ArgumentParser(description="ancient-wisdom-shorts", formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("new"); s.add_argument("slug"); s.add_argument("--id"); s.set_defaults(fn=cmd_new)
    for name, fn in (("script", cmd_script), ("captions", cmd_captions), ("story", cmd_story), ("youtube", cmd_youtube), ("timing", cmd_timing),
                     ("conti", cmd_conti), ("status", cmd_status)):
        s = sub.add_parser(name); s.add_argument("ep"); s.set_defaults(fn=fn)
    sub.add_parser("check-voice").set_defaults(fn=cmd_check_voice)
    s = sub.add_parser("tts"); s.add_argument("ep"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_tts)
    s = sub.add_parser("voice"); s.add_argument("ep"); s.add_argument("--file", required=True)
    s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_voice)
    s = sub.add_parser("animatic"); s.add_argument("ep"); s.set_defaults(fn=lambda a: cmd_compose(a, animatic=True))
    s = sub.add_parser("compose"); s.add_argument("ep"); s.set_defaults(fn=cmd_compose)
    s = sub.add_parser("verify"); s.add_argument("ep"); s.add_argument("--animatic", action="store_true"); s.set_defaults(fn=cmd_verify)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    a = p.parse_args()
    try:
        a.fn(a)
    except ShortsError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
