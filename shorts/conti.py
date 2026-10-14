"""한 장짜리 콘티 (conti.html) — 장면별 시간·대사·이미지/영상 프롬프트·저장 파일명.

사용자는 이 페이지에서 프롬프트를 복사해 ChatGPT(이미지)와 Grok(영상)에 붙여 넣고,
결과를 images/sNN.png, clips/sNN.mp4 로 저장한다.
"""
from __future__ import annotations

import html
import json

from .common import Episode, clip_parts
from .timing import estimate, part_bounds


def image_prompt(ep: Episode, scene: dict) -> str:
    st = ep.style
    chars = {c["id"]: c for c in ep.data.get("characters") or []}
    # 장면 내용을 맨 앞에 둔다 (콘티에서 바로 보이게). 화풍 문구는 뒤에.
    parts = [str(scene.get("image_prompt", "")).strip()]
    used = [chars[c] for c in scene.get("characters") or [] if c in chars]
    if used:
        names = ", ".join(f"{c.get('name_en') or c['id']} (attached reference image char_{c['id']}.png)" for c in used)
        parts.append(f"Characters: {names} — keep their faces, proportions and outfits exactly as in the references.")
    parts += [st["image_prefix"].strip(), st["image_suffix"].strip()]
    return " ".join(p for p in parts if p)


def character_prompt(ep: Episode, char: dict) -> str:
    st = ep.style
    sheet = st["character_sheet_template"].format(description=char.get("description", "").strip())
    return f"{sheet} {st['image_prefix'].strip()} No text, no letters, no watermark."


def motion_prompt(ep: Episode, scene: dict) -> str:
    """scene 또는 clip_parts() 의 한 항목."""
    parts = [str(scene.get("motion_prompt", "")).strip()]
    if scene.get("camera"):
        parts.append(f"Camera: {scene['camera']}.")
    parts.append(ep.style["motion_suffix"].strip())
    return " ".join(p for p in parts if p)


def grok_length(ep: Episode, seconds: float) -> tuple[int, str]:
    """클립 구간 길이 → (Grok 생성 길이, 알림)."""
    lengths = sorted(ep.project["clips"]["grok_lengths"])
    for L in lengths:
        if seconds <= L + 0.05:
            return L, ""
    L = lengths[-1]
    slow = float(ep.project["clips"].get("plan_slowdown", 1.2))
    if seconds <= L * slow:
        return L, f"{L}초 클립을 {seconds / L:.2f}배 느리게 늘려 맞춥니다"
    return L, (f"구간 {seconds:.1f}초 — {L}초 클립 하나로는 부족합니다. "
               f"episode.yaml 에 extra_clips 를 추가해 클립을 나누세요")


def grok_plan(ep: Episode, timing: dict) -> list[dict]:
    """Grok 클립마다 구간·길이·파일명·프롬프트."""
    out = []
    for sc in ep.scenes:
        parts = clip_parts(sc)
        if not parts:
            continue
        bounds = part_bounds(ep, timing, sc, len(parts))
        multi = len(parts) > 1
        for part, (a, b) in zip(parts, bounds):
            L, note = grok_length(ep, b - a)
            out.append({"scene": sc["id"], "n": part["n"],
                        "label": f"{sc['id'].upper()}-{part['n']}" if multi else sc["id"].upper(),
                        "start": a, "end": b, "seconds": L, "note": note,
                        "upload": f"images/{part['image']}.png", "save": f"clips/{part['file']}",
                        "text": motion_prompt(ep, part)})
    return out


def claude_code_prompt(ep: Episode, timing: dict, grok_items: list[dict]) -> str:
    """로컬 Claude Code 에 붙여 넣을 합성 지시문 (에피소드마다 자동 생성)."""
    eid = ep.data.get("id") or ep.slug
    rel = f"episodes/{ep.dir.name}"
    n_chars = len(ep.script_text())
    chars = ep.data.get("characters") or []
    n_img = len(chars) + len(ep.scenes) + sum(1 for g in grok_items if g["upload"] != f"images/{g['scene']}.png")
    focus = ", ".join(ep.data.get("caption_keywords") or []) or "핵심 동작"
    return f"""{rel} 를 최종 합성해줘. CLAUDE.md 규칙을 따른다.

0. git pull
1. python aw.py status {eid} — 이미지 {n_img}장, Grok 클립 {len(grok_items)}개, 음성이 있는지 확인. 이미지·클립이 빠졌으면 목록을 알려주고 멈춤.
2. 음성(audio/raw.wav)이 없으면: 대본 {n_chars}자 = Typecast 크레딧 약 {n_chars}. 실행해도 되는지 나에게 먼저 묻고, 승인 후 python aw.py tts {eid}.
   네트워크 오류로 결과가 불명확하면 다시 생성하지 말고 멈춘다.
3. python aw.py conti {eid} — 실측 음성 타이밍으로 콘티 갱신. 6초를 넘는 클립 구간 알림이 있으면 보고.
4. python aw.py compose {eid}
5. output/final-verification.json 검수 — 가로 중앙 정렬 필수:
   - 모든 제목·자막 줄은 외곽선 포함 실제 픽셀 기준 좌우 여백 차 2px 이내
   - 영상 소스는 가운데 기준 대칭 크롭 (좌우 여백 동일)
   - 렌더 후 측정으로 확인. 하나라도 실패하면 원인을 고치고 다시 합성. 실패한 채로 납품하지 않는다.
6. output/check/final-sheet.jpg 를 직접 보고 확인:
   - 자막·제목이 핵심 장면({focus})을 가리지 않는지
   - 클립에 말소리·음악이 섞였는지 → 그 장면(또는 extra_clips 항목) sfx_volume: 0
   - 클립 앞부분이 어색하거나 컷이 되감기처럼 튀는지 → trim_start
   - 고친 뒤 다시 compose
7. python aw.py youtube {eid} — output/youtube.txt 의 추천 제목·설명을 그대로 보여 준다.
8. 보고: final.mp4 길이, 감속·정지 보정된 클립, 조정한 항목, 검수 결과.
9. episode.yaml status: done, docs/topics.md 의 {eid} 상태를 "완성"으로 바꾸고 커밋·푸시 (이미지·영상·음성은 제외).
"""


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
code{word-break:break-all}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr));gap:8px;margin:0 0 18px;padding:0;list-style:none;counter-reset:s}
.steps li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px 10px 40px;position:relative;font-size:14px}
.steps li:before{counter-increment:s;content:counter(s);position:absolute;left:12px;top:10px;width:20px;height:20px;border-radius:50%;background:var(--ink);color:var(--bg);font-size:12px;display:grid;place-items:center;font-weight:700}
h2{font-size:17px;margin:22px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(340px,100%),1fr));gap:12px}
footer li{word-break:break-all}
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
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 16px;border-bottom:1px solid var(--line);padding-bottom:10px}
.tab{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 14px;font:inherit;font-size:14px;font-weight:600;cursor:pointer}
.tab[aria-selected="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.tab .n{font-weight:500;opacity:.7;margin-left:4px}
.panel[hidden]{display:none}
.bulk{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;justify-content:space-between;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.bulk p{margin:0;color:var(--muted);font-size:14px}
button.copy.big{font-size:14px;font-weight:700;padding:7px 16px;background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
button.copy.big.ok{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.list{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(440px,100%),1fr));gap:10px}
.list .p pre{max-height:none}
.list .h b{color:var(--ink);font-size:13px}
.hidden-src{display:none}
@media (max-width:420px){.grid{grid-template-columns:1fr}h1{font-size:22px}}
"""

JS = """
function copyText(btn){const pre=btn.dataset.target?document.getElementById(btn.dataset.target):btn.closest('.p').querySelector('pre');const t=pre.textContent;
const label=btn.textContent;const done=()=>{btn.textContent='복사됨';btn.classList.add('ok');setTimeout(()=>{btn.textContent=label;btn.classList.remove('ok')},1400)};
try{navigator.clipboard.writeText(t).then(done,()=>fallback(t,done))}catch(e){fallback(t,done)}}
function showTab(id){document.querySelectorAll('.tab').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===id?'true':'false'));
document.querySelectorAll('.panel').forEach(p=>{p.hidden=p.dataset.panel!==id});try{localStorage.setItem('conti-tab',id)}catch(e){}}
document.addEventListener('DOMContentLoaded',()=>{let t='scenes';try{t=localStorage.getItem('conti-tab')||'scenes'}catch(e){}
if(!document.querySelector('.panel[data-panel="'+t+'"]'))t='scenes';showTab(t)});
function fallback(t,done){const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy');done()}catch(e){}a.remove()}
"""


def _prompt_box(label: str, text: str) -> str:
    return (f'<div class="p"><div class="h"><span>{_e(label)}</span>'
            f'<button class="copy" onclick="copyText(this)">복사</button></div><pre>{_e(text)}</pre></div>')


def collect(ep: Episode, timing: dict) -> tuple[list[dict], list[dict]]:
    """GPT 이미지 프롬프트(캐릭터 + 장면)와 Grok 프롬프트를 순서대로 모은다."""
    chars = {c["id"]: c for c in ep.data.get("characters") or []}
    gpt = []
    for c in chars.values():
        gpt.append({"key": f"char_{c['id']}", "label": f"캐릭터: {c.get('name') or c['id']}",
                    "save": f"images/char_{c['id']}.png", "attach": "", "text": character_prompt(ep, c)})
    for sc in ep.scenes:
        sid = sc["id"]
        att = [f"char_{c}.png" for c in sc.get("characters") or [] if c in chars]
        gpt.append({"key": sid, "label": sid.upper(), "save": f"images/{sid}.png",
                    "attach": ", ".join(att), "text": image_prompt(ep, sc)})
        for part in clip_parts(sc):
            if part["own_image"]:
                patt = [f"char_{c}.png" for c in part.get("characters") or [] if c in chars]
                patt.append(f"{sid}.png (같은 장소·조명 유지)")
                gpt.append({"key": part["image"], "label": part["image"].upper(), "save": f"images/{part['image']}.png",
                            "attach": ", ".join(patt), "text": image_prompt(ep, part)})
    return gpt, grok_plan(ep, timing)


def gpt_header(it: dict) -> str:
    att = f" · 첨부: {it['attach']}" if it["attach"] else ""
    return f"[{it['label']}] 저장: {it['save']}{att}"


def grok_header(it: dict) -> str:
    return (f"[{it['label']}] {it['seconds']}초 · 업로드: {it['upload']} · 저장: {it['save']}"
            f" · 구간 {it['start']:.1f}–{it['end']:.1f}초")


def bundle(items: list[dict], header) -> str:
    return "\n\n".join(f"{header(it)}\n{it['text']}" for it in items) + "\n"


def _collection(pid: str, title: str, hint: str, items: list[dict], header) -> str:
    src_id = f"all-{pid}"
    out = [f"<div class='panel' data-panel='{pid}' hidden>",
           f"<div class='bulk'><p><b>{_e(title)} {len(items)}개</b> · {_e(hint)}</p>"
           f"<button class='copy big' data-target='{src_id}' onclick='copyText(this)'>전체 복사</button></div>",
           f"<pre class='hidden-src' id='{src_id}'>{_e(bundle(items, header))}</pre><div class='list'>"]
    for it in items:
        out.append(f'<div class="p"><div class="h"><span><b>{_e(it["label"])}</b> {_e(header(it).split("] ", 1)[1])}</span>'
                   f'<button class="copy" onclick="copyText(this)">복사</button></div><pre>{_e(it["text"])}</pre></div>')
    out.append("</div></div>")
    return "".join(out)


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
    gpt_items, grok_items = collect(ep, timing)
    grok_by_scene: dict[str, list[dict]] = {}
    for g in grok_items:
        grok_by_scene.setdefault(g["scene"], []).append(g)
    grok_count = len(grok_items)
    max_clip = max(ep.project["clips"]["grok_lengths"])
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
    out.append(f"<span class='chip'>장면 {len(ep.scenes)} · Grok 클립 {grok_count}개 (최대 {max_clip}초)</span></div></header>")

    out.append("<ol class='steps'>")
    if chars:
        out.append("<li><b>캐릭터 기준 이미지</b>를 먼저 만들고 <code>images/char_아이디.png</code> 로 저장</li>")
    out.append("<li>장면 이미지: 캐릭터 이미지를 첨부하고 프롬프트 붙여넣기 → <code>images/sNN.png</code></li>")
    out.append(f"<li>Grok: 장면 이미지를 올리고 동작 프롬프트, {max_clip}초로 생성 → <code>clips/sNN.mp4</code> "
               "(같은 장면 두 번째 클립은 <code>clips/sNN-2.mp4</code>)</li>")
    out.append("<li>파일을 에피소드 폴더에 넣고 알려주기 → 합성</li></ol>")

    cc = claude_code_prompt(ep, timing, grok_items)
    out.append("<nav class='tabs' role='tablist'>"
               "<button class='tab' role='tab' data-tab='scenes' onclick=\"showTab('scenes')\">장면별 보기</button>"
               f"<button class='tab' role='tab' data-tab='gpt' onclick=\"showTab('gpt')\">GPT 이미지 모음<span class='n'>{len(gpt_items)}</span></button>"
               f"<button class='tab' role='tab' data-tab='grok' onclick=\"showTab('grok')\">Grok 영상 모음<span class='n'>{len(grok_items)}</span></button>"
               "<button class='tab' role='tab' data-tab='cc' onclick=\"showTab('cc')\">Claude Code</button></nav>")
    out.append("<div class='panel' data-panel='cc' hidden><div class='bulk'><p><b>로컬 Claude Code 합성 지시문</b> · "
               "이미지·클립을 폴더에 넣은 뒤 레포 폴더에서 Claude Code 를 열고 붙여 넣으세요.</p>"
               "<button class='copy big' data-target='cc-src' onclick='copyText(this)'>복사</button></div>"
               f"<div class='p'><pre id='cc-src' style='max-height:none'>{_e(cc)}</pre></div></div>")
    out.append(_collection("gpt", "ChatGPT 이미지 프롬프트", "캐릭터 시트부터 순서대로. 첨부 표시가 있으면 그 이미지를 함께 올리세요.",
                           gpt_items, gpt_header))
    out.append(_collection("grok", "Grok 영상 프롬프트", f"장면 이미지를 올리고 {max_clip}초로 생성하세요. -2 클립은 같은 이미지에서 다른 동작으로 만듭니다.",
                           grok_items, grok_header))
    out.append("<div class='panel' data-panel='scenes'>")

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
        gs = grok_by_scene.get(sid, [])
        if gs:
            badge = f"<span class='badge'>Grok {gs[0]['seconds']}초" + (f" ×{len(gs)}" if len(gs) > 1 else "") + "</span>"
        else:
            badge = "<span class='badge still'>정지 이미지</span>"
        out.append(f"<div class='top'><span class='sid'>{sid.upper()}</span>"
                   f"<span class='time'>{p['start']:.1f}–{p['end']:.1f}초 · {p['duration']:.1f}초</span>{badge}</div>")
        out.append(f"<div class='narr'>{'<br>'.join(_e(t) for t in lines_by_scene[sid])}</div>")
        if sc.get("visual"):
            out.append(f"<div class='vis'>{_e(sc['visual'])}</div>")
        out.append(_prompt_box("ChatGPT 이미지", image_prompt(ep, sc)))
        for part in clip_parts(sc):
            if part["own_image"]:
                out.append(_prompt_box(f"ChatGPT 이미지 {part['image'].upper()} (새 이미지)", image_prompt(ep, part)))
        for g in gs:
            rng = f" · {g['start']:.1f}–{g['end']:.1f}초" if len(gs) > 1 else ""
            out.append(_prompt_box(f"Grok 영상 {g['label']}{rng}", g["text"]))
            if g["note"]:
                out.append(f"<div class='note'>{_e(g['label'])}: {_e(g['note'])}</div>")
        extra_imgs = "".join(f" · <b>images/{p['image']}.png</b>" for p in clip_parts(sc) if p["own_image"])
        files = f"<b>images/{sid}.png</b>{extra_imgs}" + "".join(f" · <b>{_e(g['save'])}</b>" for g in gs)
        out.append(f"<div class='files'>저장: {files}</div></div>")
    out.append("</div></div>")

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
    timing = ep.timing() or estimate(ep)
    gpt_items, grok_items = collect(ep, timing)
    prompts = {"characters": {c["id"]: character_prompt(ep, c) for c in ep.data.get("characters") or []},
               "scenes": {s["id"]: {"image": image_prompt(ep, s),
                                    "clips": [{"file": g["save"], "seconds": g["seconds"], "motion": g["text"]}
                                              for g in grok_items if g["scene"] == s["id"]]}
                          for s in ep.scenes}}
    (ep.dir / "prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")
    (ep.dir / "prompts-chatgpt.txt").write_text(bundle(gpt_items, gpt_header), encoding="utf-8")
    (ep.dir / "prompts-grok.txt").write_text(bundle(grok_items, grok_header), encoding="utf-8")
    (ep.dir / "claude-code.txt").write_text(claude_code_prompt(ep, timing, grok_items), encoding="utf-8")
    return str(path)
