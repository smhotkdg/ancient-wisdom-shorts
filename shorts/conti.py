"""한 장짜리 콘티 (conti.html) — 장면별 시간·대사·이미지/영상 프롬프트·저장 파일명.

사용자는 이 페이지에서 프롬프트를 복사해 ChatGPT(이미지)와 Grok(영상)에 붙여 넣고,
결과를 images/sNN.png, clips/sNN.mp4 로 저장한다.
"""
from __future__ import annotations

import html
import json

from .common import Episode
from .timing import estimate


def image_prompt(ep: Episode, scene: dict) -> str:
    st = ep.style
    chars = {c["id"]: c for c in ep.data.get("characters") or []}
    parts = [st["image_prefix"].strip(), str(scene.get("image_prompt", "")).strip()]
    used = [chars[c] for c in scene.get("characters") or [] if c in chars]
    if used:
        names = ", ".join(f"{c.get('name_en') or c['id']} (attached reference image char_{c['id']}.png)" for c in used)
        parts.append(f"Characters: {names} — keep their faces, proportions and outfits exactly as in the references.")
    parts.append(st["image_suffix"].strip())
    return " ".join(p for p in parts if p)


def character_prompt(ep: Episode, char: dict) -> str:
    st = ep.style
    sheet = st["character_sheet_template"].format(description=char.get("description", "").strip())
    return f"{st['image_prefix'].strip()} {sheet} No text, no letters, no watermark."


def motion_prompt(ep: Episode, scene: dict) -> str:
    parts = [str(scene.get("motion_prompt", "")).strip()]
    if scene.get("camera"):
        parts.append(f"Camera: {scene['camera']}.")
    parts.append(ep.style["motion_suffix"].strip())
    return " ".join(p for p in parts if p)


def grok_length(ep: Episode, seconds: float) -> tuple[int | None, str]:
    lengths = sorted(ep.project["clips"]["grok_lengths"])
    for L in lengths:
        if seconds <= L + 0.05:
            return L, ""
    slow = float(ep.project["clips"]["max_slowdown"])
    if seconds <= lengths[-1] * slow:
        return lengths[-1], f"{lengths[-1]}초 클립을 최대 {slow}배 느리게 늘려 맞춥니다"
    return lengths[-1], "장면이 너무 깁니다 — 장면을 나누는 것을 권장합니다"


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


CSS = """
:root{--bg:#f6f3ee;--card:#ffffff;--ink:#1d1b18;--muted:#6b655c;--line:#e4ddd2;--accent:#b8860b;--accent-ink:#ffffff;--chip:#f1ebe1;--code:#faf7f2;--warn:#a2461f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15130f;--card:#1f1c17;--ink:#f0ebe2;--muted:#a59d90;--line:#332e26;--accent:#e2b13c;--accent-ink:#1b1610;--chip:#2a251e;--code:#191612;--warn:#f08a5d}}
:root[data-theme="dark"]{--bg:#15130f;--card:#1f1c17;--ink:#f0ebe2;--muted:#a59d90;--line:#332e26;--accent:#e2b13c;--accent-ink:#1b1610;--chip:#2a251e;--code:#191612;--warn:#f08a5d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "Pretendard","Noto Sans KR",system-ui,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:flex-end;justify-content:space-between;border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:18px}
h1{margin:0;font-size:26px;line-height:1.25;font-weight:800;letter-spacing:-.01em}h1 .y{color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;gap:6px}.chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:13px;white-space:nowrap}
.hook{margin:6px 0 0;color:var(--muted)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin:0 0 18px;padding:0;list-style:none;counter-reset:s}
.steps li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px 10px 40px;position:relative;font-size:14px}
.steps li:before{counter-increment:s;content:counter(s);position:absolute;left:12px;top:10px;width:20px;height:20px;border-radius:50%;background:var(--ink);color:var(--bg);font-size:12px;display:grid;place-items:center;font-weight:700}
h2{font-size:17px;margin:22px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:8px;min-width:0}
.top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.sid{font-weight:800;font-size:18px}.time{color:var(--muted);font-variant-numeric:tabular-nums;font-size:13px}
.badge{margin-left:auto;font-size:12px;font-weight:700;border-radius:6px;padding:2px 8px;background:var(--accent);color:var(--accent-ink)}.badge.still{background:var(--chip);color:var(--ink);border:1px solid var(--line)}
.narr{font-size:16px;font-weight:600;line-height:1.5}.vis{color:var(--muted);font-size:14px}
.p{border:1px solid var(--line);border-radius:8px;background:var(--code);overflow:hidden}
.p .h{display:flex;justify-content:space-between;align-items:center;padding:6px 8px 6px 10px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted);gap:8px}
.p pre{margin:0;padding:8px 10px;white-space:pre-wrap;word-break:break-word;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;max-height:9.5em;overflow:auto}
button.copy{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer;flex:none}button.copy.ok{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.files{font:12.5px ui-monospace,Menlo,Consolas,monospace;color:var(--muted)}.files b{color:var(--ink)}
.note{color:var(--warn);font-size:13px}
footer{margin-top:24px;border-top:1px solid var(--line);padding-top:12px;color:var(--muted);font-size:13px}footer ul{margin:4px 0 10px;padding-left:18px}
@media (max-width:420px){.grid{grid-template-columns:1fr}h1{font-size:22px}}
"""

JS = """
function copyText(btn){const pre=btn.closest('.p').querySelector('pre');const t=pre.innerText;
const done=()=>{btn.textContent='복사됨';btn.classList.add('ok');setTimeout(()=>{btn.textContent='복사';btn.classList.remove('ok')},1400)};
try{navigator.clipboard.writeText(t).then(done,()=>fallback(t,done))}catch(e){fallback(t,done)}}
function fallback(t,done){const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy');done()}catch(e){}a.remove()}
"""


def _prompt_box(label: str, text: str) -> str:
    return (f'<div class="p"><div class="h"><span>{_e(label)}</span>'
            f'<button class="copy" onclick="copyText(this)">복사</button></div><pre>{_e(text)}</pre></div>')


def build(ep: Episode) -> str:
    timing = ep.timing() or estimate(ep)
    measured = not timing.get("estimated")
    plan = {s["id"]: s for s in timing["scenes"]}
    lines_by_scene: dict[str, list[str]] = {}
    for l in ep.lines:
        lines_by_scene.setdefault(l.scene, []).append(l.text)
    title_lines = ep.data.get("title_lines") or [ep.data.get("working_title", ep.slug)]
    t_html = "<br>".join(f'<span class="{"y" if i else ""}">{_e(t)}</span>' for i, t in enumerate(title_lines))
    total = timing["video_duration"]
    grok_count = sum(1 for s in ep.scenes if (s.get("source") or "grok") == "grok")
    chars = ep.data.get("characters") or []

    out = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{_e(ep.data.get('id', ''))} 콘티</title><style>{CSS}</style></head><body><div class='wrap'>"]
    out.append("<header><div>")
    out.append(f"<h1>{t_html}</h1>")
    if ep.data.get("hook"):
        out.append(f"<p class='hook'>훅: {_e(ep.data['hook'])}</p>")
    out.append("</div><div class='meta'>")
    out.append(f"<span class='chip'>{_e(ep.slug)}</span><span class='chip'>화풍: {_e(ep.style.get('label'))}</span>")
    out.append(f"<span class='chip'>{'실측' if measured else '추정'} {total:.1f}초</span>")
    out.append(f"<span class='chip'>장면 {len(ep.scenes)} · Grok {grok_count}</span></div></header>")

    out.append("<ol class='steps'>")
    if chars:
        out.append("<li><b>캐릭터 기준 이미지</b>를 먼저 만들고 <code>images/char_아이디.png</code> 로 저장</li>")
    out.append("<li>장면 이미지: 캐릭터 이미지를 첨부하고 프롬프트 붙여넣기 → <code>images/sNN.png</code></li>")
    out.append("<li>Grok: 장면 이미지를 올리고 동작 프롬프트, 권장 길이로 생성 → <code>clips/sNN.mp4</code></li>")
    out.append("<li>파일을 에피소드 폴더에 넣고 알려주기 → 합성</li></ol>")

    if chars:
        out.append("<h2>캐릭터</h2><div class='grid'>")
        for c in chars:
            out.append("<div class='card'>")
            out.append(f"<div class='top'><span class='sid'>{_e(c.get('name') or c['id'])}</span></div>")
            if c.get("note"):
                out.append(f"<div class='vis'>{_e(c['note'])}</div>")
            out.append(_prompt_box("ChatGPT 이미지 프롬프트 (기준 시트)", character_prompt(ep, c)))
            out.append(f"<div class='files'>저장: <b>images/char_{_e(c['id'])}.png</b></div></div>")
        out.append("</div>")

    out.append("<h2>장면</h2><div class='grid'>")
    for sc in ep.scenes:
        sid = sc["id"]
        p = plan[sid]
        src = sc.get("source") or "grok"
        out.append("<div class='card'>")
        if src == "grok":
            L, note = grok_length(ep, p["duration"])
            badge = f"<span class='badge'>Grok {L}초</span>"
        else:
            note = ""
            badge = "<span class='badge still'>정지 이미지</span>"
        out.append(f"<div class='top'><span class='sid'>{sid.upper()}</span>"
                   f"<span class='time'>{p['start']:.1f}–{p['end']:.1f}초 · {p['duration']:.1f}초</span>{badge}</div>")
        out.append(f"<div class='narr'>{'<br>'.join(_e(t) for t in lines_by_scene[sid])}</div>")
        if sc.get("visual"):
            out.append(f"<div class='vis'>{_e(sc['visual'])}</div>")
        out.append(_prompt_box("ChatGPT 이미지", image_prompt(ep, sc)))
        if src == "grok":
            out.append(_prompt_box("Grok 영상", motion_prompt(ep, sc)))
        if note:
            out.append(f"<div class='note'>{_e(note)}</div>")
        files = f"<b>images/{sid}.png</b>" + (f" · <b>clips/{sid}.mp4</b>" if src == "grok" else "")
        out.append(f"<div class='files'>저장: {files}</div></div>")
    out.append("</div>")

    srcs, notes = ep.data.get("sources") or [], ep.data.get("accuracy_notes") or []
    if srcs or notes:
        out.append("<footer>")
        if srcs:
            out.append("<b>근거</b><ul>" + "".join(f"<li>{_e(s)}</li>" for s in srcs) + "</ul>")
        if notes:
            out.append("<b>정확성 메모</b><ul>" + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul>")
        out.append("</footer>")
    out.append(f"</div><script>{JS}</script></body></html>")
    return "".join(out)


def write(ep: Episode) -> str:
    path = ep.dir / "conti.html"
    path.write_text(build(ep), encoding="utf-8")
    prompts = {"characters": {c["id"]: character_prompt(ep, c) for c in ep.data.get("characters") or []},
               "scenes": {s["id"]: {"image": image_prompt(ep, s),
                                    "motion": motion_prompt(ep, s) if (s.get("source") or "grok") == "grok" else None}
                          for s in ep.scenes}}
    (ep.dir / "prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
