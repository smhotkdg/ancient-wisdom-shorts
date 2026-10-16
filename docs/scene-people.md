# 화면 인물 가이드 — 주인공 중심, 배경 인물은 양념처럼

2026-10-16 사용자 피드백으로 정한 기준. 대본·콘티를 만들 때마다 이 문서를 따른다 (CLAUDE.md 2-3).

## 왜

- **인물이 너무 많으면 집중도가 떨어진다.** 008 케스와차카는 마을 사람·군중·잔치 장면이 6개라 산만했다.
- **하지만 주인공 혼자만 나올 필요는 없다.** 장면에 잘 맞는 배경 인물은 이야기를 살린다.
  좋은 예 — 007 나일로미터 s08: 관리가 가운데서 곡식 자루를 세고, 뒤에서 농부 몇 명이 어깨를 늘어뜨린다.
  대사("세금도 높게 매겼거든요")에 배경 인물의 표정이 바로 반응한다.

## 규칙

| | 할 것 | 하지 말 것 |
|---|---|---|
| 주인공 | 늘 가운데, 가장 크게, 표정이 보이게 | 주인공이 작거나 가장자리로 밀려나는 구도 |
| 배경 인물 | 뒤쪽에 작게 2~4명, 대사에 반응하는 역할 (한숨, 놀람, 환호, 걱정) | 군중이 화면의 주인공인 장면 (줄지어 밧줄 당기기, 잔치, 대규모 공사 현장) |
| 개수 | 배경 인물 장면은 **에피소드당 3개 이하** | 매 장면 사람 추가 |
| 나머지 장면 | 주인공 혼자 · 손 클로즈업 · 결과물 · 풍경 · 단면도 | — |
| 내레이션 | 주어는 주인공 ("농부는 …") | "마을 사람들은 …"처럼 집단을 주어로 |
| 정확성 | 실제로는 여럿이 했다면 `accuracy_notes`에 적는다 | — |

배경 인물을 넣기 좋은 순간:
- **문제** 장면에서 같은 처지의 사람들 (다 같이 추워 떠는 모습 — 단, 주인공이 앞)
- **반전** 장면에서 걱정하거나 수군대는 사람들 (007 s07 농부들)
- **마무리·정보** 장면에서 결과에 반응하는 사람들 (007 s08 한숨, 012 승리 후 환호)

## episode.yaml 에 쓰는 법

배경 인물은 `image_prompt`에 직접 쓰지 말고 장면의 `extras:`에 적는다.
콘티(`aw.py conti`)가 구도 문장을 자동으로 붙인다.

```yaml
  - id: s08
    beat: resolve
    lines:
      - "물이 넉넉히 차오르면 풍년이 들 테니, 그해 세금도 높게 매겼거든요."
    image_prompt: >-
      A golden wheat field at harvest beside the river, sacks of grain piled up, the official counting sacks
      and tallying on his scroll.
    characters: [official]          # 첫 번째가 주인공
    extras: "three tired farmers in simple linen clothes, sighing and slumping their shoulders"
    motion_prompt: >-
      The official counts the sacks and marks his scroll; the farmers behind him sigh together.
```

콘티가 자동으로 붙이는 문장:

| 장면 | 이미지 프롬프트에 붙는 구도 문장 |
|---|---|
| `extras` 있음 | `Composition: the <주인공> in the center foreground, large and clearly the focus; in the background, smaller and slightly out of focus: <extras> (only 2-4 people, never blocking the <주인공>).` |
| 주인공만 | `Composition: the <주인공> in the center as the only person in the scene.` |
| 사람 없음 (풍경·단면도) | 붙지 않음 — `image_prompt` 끝에 `No people.` 을 직접 쓴다 |

`extras`가 있으면 Grok 동작 프롬프트에도 `Background people stay small and move only a little; keep the focus on the main character.`가 붙는다.
`extra_clips` 항목에도 `extras:`를 쓸 수 있다.

## 점검

- `python aw.py story <ep>` — 배경 인물 장면(`extras` + 프롬프트 속 villagers·workers·crowd·farmers·family·people / 사람들·일꾼·가족)을 세어 **3개를 넘으면 실패**.
  `No people.` / `No other people.` / `No visible people.`는 세지 않는다.
- 이미지 확인 (사용자, ChatGPT): 주인공이 가운데 크게 나왔는지, 배경 인물이 주인공을 가리지 않는지. 가리면 다시 생성.
- 합성 검수 (로컬 Claude Code): `final-sheet.jpg`에서 Grok이 사람을 더 만들어 넣었는지 확인하고 보고.

## 주제 고를 때

한 사람이 처음부터 끝까지 끌고 갈 수 있는 이야기를 우선한다.
마을 전체 행사가 핵심인 주제(케스와차카처럼)는 주인공 한 명의 시선으로 줄이거나 피한다.
