"""대본 스토리 점검 (python aw.py story <ep>).

영상 구조(훅→문제→질문→해결→반전→마무리→정보)는 그대로 두고, 내레이션이 '나열'이 아니라
'주인공이 겪는 이야기'로 쓰였는지 점검한다. 통과/주의만 알려 주고 대본은 고치지 않는다.
"""
from __future__ import annotations

import re

from .common import Episode
from .timing import estimate

REACTIONS = ["멘탈이 나가", "머리를 쥐어뜯", "속이 터졌", "발을 동동", "넋이 나갔", "두 손 두 발", "골머리", "말문이 막혔", "눈앞이 캄캄", "진땀을 뺐", "혼이 쏙",
             "제정신이 아닌", "놀라 자빠", "기가 막히", "말도 안 되"]
TURNS = ["그런데", "하지만", "그때", "그래서", "결국", "드디어", "이번엔", "그러자", "그렇게"]
LIST_WORDS = ["첫째", "둘째", "셋째", "먼저,", "다음으로"]
# 화면 인물 = 주인공 한 명 (2026-10-16 사용자: 인물이 많으면 집중도가 떨어진다 — 008 군중 장면)
CROWD_EN = re.compile(r"\b(villagers|crowd|crowds|workers|townspeople|farmers|families|family|children|everyone|"
                      r"group of|lines of|many hands|people)\b", re.I)
CROWD_KO = re.compile(r"사람들|마을 사람|일꾼|군중|가족|농부들|아이들|여럿")
NO_PEOPLE = re.compile(r"\bno (other |visible )?(people|crews?)\b", re.I)


def crowd_scenes(ep: Episode) -> list[str]:
    """이미지·영상 프롬프트에 여러 사람(군중·일꾼·가족 등)이 나오는 장면 id."""
    found = []
    for sc in ep.scenes:
        parts = [(sc["id"], sc)] + [(f"{sc['id']}-{i + 2}", x) for i, x in enumerate(sc.get("extra_clips") or [])]
        for pid, part in parts:
            en = " ".join(str(part.get(k) or "") for k in ("image_prompt", "motion_prompt"))
            en = NO_PEOPLE.sub("", en)
            ko = str(part.get("visual") or "")
            if CROWD_EN.search(en) or CROWD_KO.search(ko):
                found.append(pid)
    return found


BEAT_ORDER = ["hook", "problem", "question", "solution", "twist", "resolve", "info"]
BEAT_KO = {"hook": "훅", "problem": "문제", "question": "질문", "solution": "해결", "twist": "반전",
           "resolve": "마무리", "info": "정보"}


def check(ep: Episode) -> dict:
    lines = [l.text for l in ep.lines]
    text = " ".join(lines)
    est = estimate(ep)
    total = est["video_duration"]
    first = lines[0]
    results, tips = [], []

    def item(ok, name, detail):
        results.append({"pass": ok, "check": name, "detail": detail})

    story = ep.data.get("story") or {}
    hero = story.get("hero") or ""
    item(any(r in first for r in REACTIONS), "첫 문장 반응어 훅", first)
    item(bool(hero) and hero in text, "주인공이 대본에 등장", f"story.hero = {hero or '(없음)'}")
    q_lines = [i for i, l in enumerate(lines) if "?" in l]
    item(len(q_lines) >= 2, "질문 두 번 이상", f"{len(q_lines)}번")
    hero_lines = sum(1 for l in lines if hero and hero in l)
    item(hero_lines >= 2, "주인공을 따라가는 서술 (2문장 이상)", f"{hero_lines}문장")
    turns = sum(text.count(t) for t in TURNS)
    item(turns >= 3, "전환어 리듬 (그런데·하지만·그때·그래서…)", f"{turns}번")
    listy = [w for w in LIST_WORDS if w in text]
    item(not listy, "나열형 표현 없음", ", ".join(listy) if listy else "없음")
    beats = [sc.get("beat") for sc in ep.scenes]
    known = [b for b in beats if b in BEAT_ORDER]
    order_ok = known == sorted(known, key=BEAT_ORDER.index) and {"hook", "question", "solution", "info"} <= set(known)
    item(order_ok, "구조 순서 (훅 → 문제 → 질문 → 해결 → 반전 → 마무리 → 정보)",
         " → ".join(BEAT_KO.get(b, "?") for b in beats) if any(beats) else "beat 미지정")
    # 마지막 대사 = 정답 공개
    last = lines[-1]
    reveal = story.get("reveal") or []
    reveal = [reveal] if isinstance(reveal, str) else list(reveal)
    item(bool(re.search(r"바로[, ]*.+입니다", last)), "마지막 대사 정답 공개 (이것이 바로 ○○입니다)", last)
    if reveal:
        early = " ".join(lines[:-1]) + " " + " ".join(ep.data.get("title_lines") or [])
        leaked = [r for r in reveal if r in early]
        item(not leaked and all(r in last for r in reveal), "정답 이름을 마지막까지 아낌",
             f"앞부분·제목에 노출: {', '.join(leaked)}" if leaked else f"마지막에만 등장: {', '.join(reveal)}")
    else:
        item(False, "정답 이름을 마지막까지 아낌", "story.reveal 미지정")

    crowd = crowd_scenes(ep)
    item(not crowd, "화면 인물은 주인공 한 명 (군중·일꾼·가족 장면 없음)",
         f"여러 사람이 나오는 장면: {', '.join(crowd)}" if crowd else "통과")

    notes = " ".join(ep.data.get("accuracy_notes") or [])
    item("재구성" in notes, "정확성 메모에 '재구성' 명시", "있음" if "재구성" in notes else "없음")
    item(not re.search(r"기록에 따르면|기록에 의하면", text), "지어낸 '기록' 인용 없음", "통과")

    # 비트별 시간
    plan = {s["id"]: s for s in est["scenes"]}
    timeline = [{"scene": sc["id"], "beat": BEAT_KO.get(sc.get("beat"), "-"),
                 "start": plan[sc["id"]]["start"], "end": plan[sc["id"]]["end"]} for sc in ep.scenes]
    return {"results": results, "timeline": timeline, "tips": tips,
            "pass": all(r["pass"] for r in results)}
