"""대본 스토리 점검 (python aw.py story <ep>).

.claude/skills/shorts-story/SKILL.md 의 7비트 구조를 기준으로, 대본이 '나열'이 아니라
'주인공이 시도하고 실패하고 깨닫는 이야기'인지 점검한다. 통과/주의만 알려 주고 대본은 고치지 않는다.
"""
from __future__ import annotations

import re

from .common import Episode
from .timing import estimate

REACTIONS = ["멘탈이 나가", "머리를 쥐어뜯", "속이 터졌", "발을 동동", "넋이 나갔", "두 손 두 발", "골머리",
             "제정신이 아닌", "놀라 자빠", "기가 막히", "말도 안 되"]
TURNS = ["그런데", "하지만", "그때", "그래서", "결국", "드디어", "이번엔"]
LIST_WORDS = ["첫째", "둘째", "셋째", "먼저,", "다음으로"]
BEAT_ORDER = ["hook", "goal", "try", "fail", "partial", "insight", "payoff", "today"]
BEAT_KO = {"hook": "훅", "goal": "목표", "try": "시도", "fail": "실패", "partial": "반쯤 성공",
           "insight": "깨달음", "payoff": "보상", "today": "지금"}


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
    attempts = story.get("attempts") or []
    fails = [a for a in attempts if (a.get("result") in ("fail", "partial"))]
    item(len(attempts) >= 2 and len(fails) >= 1, "시도 2번 이상 + 실패 1번 이상",
         f"시도 {len(attempts)} · 실패/반쯤 {len(fails)}")
    turns = sum(text.count(t) for t in TURNS)
    item(turns >= 3, "전환어 리듬 (그런데·하지만·그때·그래서…)", f"{turns}번")
    listy = [w for w in LIST_WORDS if w in text]
    item(not listy, "나열형 표현 없음", ", ".join(listy) if listy else "없음")
    beats = [sc.get("beat") for sc in ep.scenes]
    known = [b for b in beats if b in BEAT_ORDER]
    order_ok = known == sorted(known, key=BEAT_ORDER.index) and {"hook", "insight", "payoff"} <= set(known)
    item(order_ok, "장면 비트 순서 (훅 → … → 깨달음 → 보상)",
         " → ".join(BEAT_KO.get(b, "?") for b in beats) if any(beats) else "beat 미지정")
    notes = " ".join(ep.data.get("accuracy_notes") or [])
    item("재구성" in notes, "정확성 메모에 '재구성' 명시", "있음" if "재구성" in notes else "없음")
    item(not re.search(r"기록에 따르면|기록에 의하면", text), "지어낸 '기록' 인용 없음", "통과")

    # 비트별 시간
    plan = {s["id"]: s for s in est["scenes"]}
    timeline = [{"scene": sc["id"], "beat": BEAT_KO.get(sc.get("beat"), "-"),
                 "start": plan[sc["id"]]["start"], "end": plan[sc["id"]]["end"]} for sc in ep.scenes]
    ins = [t for t in timeline if t["beat"] == "깨달음"]
    if ins and not (0.5 <= ins[0]["start"] / total <= 0.85):
        tips.append(f"깨달음이 {ins[0]['start']:.0f}초({ins[0]['start'] / total:.0%})에 나옵니다 — 영상의 55~80% 지점이 좋습니다.")
    return {"results": results, "timeline": timeline, "tips": tips,
            "pass": all(r["pass"] for r in results)}
