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
    parts.append(composition_line(scene, used))
    parts += [st["image_prefix"].strip(), st["image_suffix"].strip()]
    return " ".join(p for p in parts if p)


def composition_line(scene: dict, used: list[dict]) -> str:
    """화면 인물 규칙 (docs/scene-people.md): 주인공은 가운데 크게, 배경 인물(extras)은 뒤에 작게 몇 명만."""
    from .story import crowd_text
    if not used:
        return ""
    hero = used[0].get("name_en") or used[0]["id"]
    extras = str(scene.get("extras") or "").strip()
    if extras:
        return (f"Composition: the {hero} in the center foreground, large and clearly the focus; "
                f"in the background, smaller and slightly out of focus: {extras} (only 2-4 people, never blocking the {hero}).")
    if crowd_text(scene):   # 프롬프트에 이미 사람들이 적혀 있으면 덧붙이지 않는다 (예전 에피소드)
        return f"Composition: keep the {hero} in the center foreground as the clear focus."
    return f"Composition: the {hero} in the center as the only person in the scene."


def character_prompt(ep: Episode, char: dict) -> str:
    st = ep.style
    sheet = st["character_sheet_template"].format(description=char.get("description", "").strip())
    return f"{sheet} {st['image_prefix'].strip()} No text, no letters, no watermark."


def motion_prompt(ep: Episode, scene: dict) -> str:
    """scene 또는 clip_parts() 의 한 항목."""
    parts = [str(scene.get("motion_prompt", "")).strip()]
    if scene.get("extras"):
        parts.append("Background people stay small and move only a little; keep the focus on the main character.")
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
2. 음성(audio/raw.wav)이 없으면: 묻지 말고 바로 python aw.py tts {eid} 를 실행한다.
   (이 지시문 자체가 승인이다 — 대본 {n_chars}자 = Typecast 크레딧 약 {n_chars}. 사용한 글자 수는 마지막 보고에 적는다.)
   음성이 이미 있으면 새로 만들지 않는다 (--force 금지).
   네트워크 오류로 결과가 불명확하면 다시 생성하지 말고 멈춘다.
2-1. 자막 싱크: python -c "import faster_whisper" 가 실패하면 pip install faster-whisper 부터 한다.
   음성은 대본 전체를 파일 하나로 받는다(문장별 생성 금지). 싱크는 Whisper 정렬로 맞춘다.
   음성이 이미 있으면 python aw.py timing {eid} — 문장·글자 시각을 다시 계산 (크레딧 0).
   출력의 정렬 방식이 whisper 인지, 일치율이 80% 이상인지 확인. 아니면 이유(경고)를 보고한다.
   Whisper 는 config 의 timing.whisper_device(기본 cpu)로 돈다 — 20초 안팎. GPU 자동 전환·CUDA 설치를 시도하지 않는다.
   audio/pace.json 의 removed_seconds(줄인 쉼 길이)도 보고한다.
3. python aw.py conti {eid} — 실측 음성 타이밍으로 콘티 갱신. 6초를 넘는 클립 구간 알림이 있으면 보고.
4. python aw.py compose {eid}
5. output/final-verification.json 검수 — 가로 중앙 정렬 필수:
   - 모든 제목·자막 줄은 외곽선 포함 실제 픽셀 기준 좌우 여백 차 2px 이내
   - 영상 소스는 가운데 기준 대칭 크롭 (좌우 여백 동일)
   - 렌더 후 측정으로 확인. 하나라도 실패하면 원인을 고치고 다시 합성. 실패한 채로 납품하지 않는다.
6. output/check/final-sheet.jpg 를 직접 보고 확인:
   - 자막·제목이 핵심 장면({focus})을 가리지 않는지
   - 주인공이 가운데 크게 보이는지, Grok 이 사람을 더 만들어 넣어 주인공을 가리지 않는지 (docs/scene-people.md) → 그런 장면은 보고
   - 마지막 질문 자막("여러분의 생각이 궁금합니다")이 주인공이 시청자를 보는 컷 위에 나오고, 얼굴·손을 가리지 않는지
   - 클립에 말소리·사람 소리(웃음·외침)·음악이 섞였는지 → 그 장면(또는 extra_clips 항목) sfx_volume: 0
   - 클립 앞부분이 어색하거나 컷이 되감기처럼 튀는지 → trim_start
   - 고친 뒤 다시 compose
7. python aw.py youtube {eid} — output/youtube.txt 의 추천 제목·설명을 그대로 보여 준다.
8. 보고: final.mp4 길이, 감속·정지 보정된 클립, 조정한 항목, 검수 결과(음성·자막 정렬 방식 포함).
   싱크 확인: output/final.srt 의 몇 군데(처음·중간·끝)를 실제 소리와 비교해 자막이 0.3초 이상 어긋나는 곳이 있으면 보고.
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
                if sc.get("characters"):   # 단면도·풍경(사람 없는 장면)은 장소 기준으로 첨부하지 않는다
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


def bundle(items: list[dict], header, preamble: str = "") -> str:
    body = "\n\n".join(f"{header(it)}\n{it['text']}" for it in items) + "\n"
    return f"{preamble}\n\n{body}" if preamble else body


GPT_BATCH = 10   # ChatGPT 한 번에 만들 수 있는 최대 이미지 수


def gpt_preamble(items: list[dict]) -> str:
    """ChatGPT '전체 복사' 맨 앞에 붙는 진행 지시 — 묻지 말고 캐릭터 → 장면 순서로 바로 생성 (2026-10-21 사용자)."""
    labels = [it["label"].replace("캐릭터: ", "캐릭터 ") for it in items]
    batches = [labels[i:i + GPT_BATCH] for i in range(0, len(labels), GPT_BATCH)]
    plan = "\n".join(f"   - {n}차: {', '.join(b)}" for n, b in enumerate(batches, 1))
    return f"""[진행 방식 — 질문하지 말고 바로 생성]
아래 이미지 {len(items)}장을 순서대로 만들어 줘. 확인 질문이나 선택지 제시 없이 지금 바로 시작한다.
1. 캐릭터 레퍼런스부터 만들고, 끝나면 묻지 말고 곧바로 장면 이미지로 넘어간다.
   장면에서는 이 대화에서 만든 캐릭터 레퍼런스(또는 첨부한 char_*.png)와 얼굴·체형·옷을 똑같이 유지한다.
2. 한 번에 만들 수 있는 이미지 수({GPT_BATCH}장)를 넘으면 알아서 나눠서 만든다:
{plan}
   한 차수가 끝나면 묻지 말고 바로 다음 차수를 이어서 만든다.
   응답이 끊겨야 한다면 마지막 줄에 "계속"이라고만 쓰고 멈추고, 내가 "계속"이라고 보내면 남은 이미지부터 바로 이어서 만든다.
3. 모든 이미지는 세로 9:16, 이미지 안에 글자·숫자·로고·워터마크를 넣지 않는다.
4. 각 이미지 아래에는 저장할 파일 이름(예: s01.png)만 한 줄로 적는다. 다른 설명은 쓰지 않는다."""


def redo_items(ep: Episode, gpt_items: list[dict], grok_items: list[dict]) -> tuple[list[dict], list[dict], str]:
    """episode.yaml 의 redo: {images: [s01, s08-2 ...], reason: ...} — 다시 만들 이미지와 그 이미지로 만드는 Grok 클립만 고른다.
    (2026-10-28 사용자: 얼굴이 제목에 가린 컷만 ChatGPT 한도 안에서 다시 만들기)"""
    redo = ep.data.get("redo") or {}
    keys = [str(k) for k in redo.get("images") or []]
    if not keys:
        return [], [], ""
    gpt = [it for it in gpt_items if it["key"] in keys]
    grok = [g for g in grok_items if g["upload"].removeprefix("images/").removesuffix(".png") in keys]
    return gpt, grok, str(redo.get("reason") or "")


def redo_preamble(ep: Episode, items: list[dict], reason: str) -> str:
    chars = ", ".join(f"char_{c['id']}.png" for c in ep.data.get("characters") or [])
    why = f" ({reason})" if reason else ""
    return f"""[진행 방식 — 다시 만들기, 질문하지 말고 바로 생성]
아래 이미지 {len(items)}장만 다시 만들어 줘{why}. 캐릭터 레퍼런스는 새로 만들지 않는다 — 첨부한 {chars}의 얼굴·체형·옷을 그대로 쓴다.
1. 확인 질문이나 선택지 제시 없이 순서대로 바로 만든다. 끊겨야 한다면 마지막 줄에 "계속"이라고만 쓰고, 내가 "계속"이라고 보내면 남은 것부터 이어서 만든다.
2. 가장 중요: 이미지 위쪽 1/4은 비워 둔다(하늘이나 민무늬 벽). 머리·얼굴·들어 올린 손·모자가 위쪽 1/4에 들어가면 안 된다.
   주인공의 머리는 위에서 35~45% 높이, 무릎 또는 허리 위가 보이게. 클로즈업이어도 얼굴은 화면 가운데.
3. 모든 이미지는 세로 9:16, 이미지 안에 글자·숫자·로고·워터마크를 넣지 않는다.
4. 각 이미지 아래에는 저장할 파일 이름(예: s01.png)만 한 줄로 적는다 (기존 파일을 덮어쓴다)."""


def _collection(pid: str, title: str, hint: str, items: list[dict], header, preamble: str = "") -> str:
    src_id = f"all-{pid}"
    out = [f"<div class='panel' data-panel='{pid}' hidden>",
           f"<div class='bulk'><p><b>{_e(title)} {len(items)}개</b> · {_e(hint)}</p>"
           f"<button class='copy big' data-target='{src_id}' onclick='copyText(this)'>전체 복사</button></div>",
           f"<pre class='hidden-src' id='{src_id}'>{_e(bundle(items, header, preamble))}</pre><div class='list'>"]
    if preamble:
        out.append(f'<div class="p"><div class="h"><span><b>진행 방식</b> 전체 복사 맨 앞에 자동으로 붙습니다</span></div>'
                   f'<pre>{_e(preamble)}</pre></div>')
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
    r_gpt, r_grok, r_why = redo_items(ep, gpt_items, grok_items)
    out.append("<nav class='tabs' role='tablist'>"
               "<button class='tab' role='tab' data-tab='scenes' onclick=\"showTab('scenes')\">장면별 보기</button>"
               f"<button class='tab' role='tab' data-tab='gpt' onclick=\"showTab('gpt')\">GPT 이미지 모음<span class='n'>{len(gpt_items)}</span></button>"
               f"<button class='tab' role='tab' data-tab='grok' onclick=\"showTab('grok')\">Grok 영상 모음<span class='n'>{len(grok_items)}</span></button>"
               + (f"<button class='tab' role='tab' data-tab='redo' onclick=\"showTab('redo')\">다시 만들기<span class='n'>{len(r_gpt)}</span></button>" if r_gpt else "")
               + "<button class='tab' role='tab' data-tab='cc' onclick=\"showTab('cc')\">Claude Code</button></nav>")
    out.append("<div class='panel' data-panel='cc' hidden><div class='bulk'><p><b>로컬 Claude Code 합성 지시문</b> · "
               "이미지·클립을 폴더에 넣은 뒤 레포 폴더에서 Claude Code 를 열고 붙여 넣으세요.</p>"
               "<button class='copy big' data-target='cc-src' onclick='copyText(this)'>복사</button></div>"
               f"<div class='p'><pre id='cc-src' style='max-height:none'>{_e(cc)}</pre></div></div>")
    out.append(_collection("gpt", "ChatGPT 이미지 프롬프트", "'전체 복사'를 그대로 붙여 넣으면 캐릭터 → 장면 순서로 묻지 않고 바로 생성합니다 (10장씩 나눠서).",
                           gpt_items, gpt_header, gpt_preamble(gpt_items)))
    out.append(_collection("grok", "Grok 영상 프롬프트", f"장면 이미지를 올리고 {max_clip}초로 생성하세요. -2 클립은 같은 이미지에서 다른 동작으로 만듭니다.",
                           grok_items, grok_header))
    if r_gpt:
        out.append(_collection("redo", "다시 만들 ChatGPT 이미지", f"{r_why} — 이 이미지들만 다시 만듭니다. 아래에 같은 장면의 Grok 클립도 있습니다.",
                               r_gpt, gpt_header, redo_preamble(ep, r_gpt, r_why)).removesuffix("</div></div>")
                   + f"<h3>다시 만들 Grok 클립 {len(r_grok)}개</h3><pre class='hidden-src' id='redo-grok'>{_e(bundle(r_grok, grok_header))}</pre>"
                   + "<button class='copy big' data-target='redo-grok' onclick='copyText(this)'>Grok 전체 복사</button>"
                   + "".join(_prompt_box(f"Grok 영상 {g['label']}", g["text"]) for g in r_grok) + "</div></div>")
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
    (ep.dir / "prompts-chatgpt.txt").write_text(bundle(gpt_items, gpt_header, gpt_preamble(gpt_items)), encoding="utf-8")
    (ep.dir / "prompts-grok.txt").write_text(bundle(grok_items, grok_header), encoding="utf-8")
    r_gpt, r_grok, r_why = redo_items(ep, gpt_items, grok_items)
    for name, text in (("prompts-chatgpt-redo.txt", bundle(r_gpt, gpt_header, redo_preamble(ep, r_gpt, r_why)) if r_gpt else ""),
                       ("prompts-grok-redo.txt", bundle(r_grok, grok_header) if r_grok else "")):
        p = ep.dir / name
        if text:
            p.write_text(text, encoding="utf-8")
        elif p.exists():
            p.unlink()
    (ep.dir / "claude-code.txt").write_text(claude_code_prompt(ep, timing, grok_items), encoding="utf-8")
    publish_copy(ep)
    return str(path)


def publish_copy(ep: Episode) -> None:
    """레포 루트 conti/ 에 에피소드별 콘티 복사본 + 목록(index.html)을 둔다 — 찾기 쉽게 (2026-10-16 사용자)."""
    from .common import ROOT, load_episode
    out = ROOT / "conti"
    out.mkdir(exist_ok=True)
    (out / f"{ep.dir.name}.html").write_text((ep.dir / "conti.html").read_text(encoding="utf-8"), encoding="utf-8")
    rows = []
    for d in sorted((ROOT / "episodes").glob("[0-9][0-9][0-9]-*")):
        if not (d / "conti.html").exists() or not (out / f"{d.name}.html").exists():
            continue
        try:
            e = load_episode(d)
            title = " ".join(e.data.get("title_lines") or []) or e.data.get("working_title") or d.name
            status = e.data.get("status", "")
        except Exception:
            title, status = d.name, ""
        rows.append(f'<li><a href="{_e(d.name)}.html"><b>{_e(d.name[:3])}</b> {_e(title)}</a>'
                    f' <span class="st">{_e(status)}</span></li>')
    (out / "index.html").write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>콘티 목록</title>
<style>:root{{--bg:#f6f3ee;--ink:#1d1b18;--muted:#6b655c;--line:#e4ddd2;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#15130f;--ink:#f0ebe2;--muted:#a59d90;--line:#332e26;--card:#1f1c17}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 "Noto Sans KR",system-ui,sans-serif}}
main{{max-width:720px;margin:0 auto;padding:24px 16px}}h1{{font-size:22px}}ul{{list-style:none;padding:0}}
li{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:10px 14px}}
a{{color:inherit;text-decoration:none}}.st{{color:var(--muted);font-size:13px;margin-left:6px}}</style></head>
<body><main><h1>에피소드 콘티 목록</h1><ul>
{chr(10).join(rows)}
</ul><p class="st">python aw.py conti &lt;ep&gt; 를 실행하면 자동으로 갱신됩니다.</p></main></body></html>
""", encoding="utf-8")
