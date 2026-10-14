# 작업 흐름

## 0. PC 준비 (처음 한 번)

```
git clone https://github.com/smhotkdg/ancient-wisdom-shorts.git
cd ancient-wisdom-shorts
pip install -r requirements.txt
python aw.py doctor
```

- ffmpeg 없음 → Windows `winget install Gyan.FFmpeg`, Mac `brew install ffmpeg`
- 폰트 없음 → [Noto Sans KR](https://fonts.google.com/noto/specimen/Noto+Sans+KR) 설치 (또는 `fonts/`에 Black·Bold 파일 넣기)
- 음성을 만들 PC → `.env.example`을 `.env`로 복사하고 `TYPECAST_API_KEY` 입력, `python aw.py check-voice`
- 전체 흐름 확인 → `python aw.py selftest` (비용 0, 몇 분 걸림)

## 1. 주제 → 대본 (Claude)

사용자: "주제 찾아줘" → Claude가 후보 2~3개를 근거와 함께 제안 → 사용자가 고른다.

```
python aw.py new <slug>          # episodes/NNN-slug/ 생성
```

Claude가 `episode.yaml`에 대본·장면·프롬프트·근거·유튜브 문구를 쓴다 → [story-format.md](story-format.md).

```
python aw.py script <ep>         # 글자 수, 예상 길이
python aw.py captions <ep>       # 자막 나눔 확인
```

## 2. 필재 음성 (Claude, 승인 후)

```
python aw.py tts <ep>            # 대본 글자 수만큼 크레딧 사용
```

생성 직후 문장별 타이밍(`audio/timing.json`)과 장면별 길이가 나온다. 정렬 방식이 `proportional`로 나오면 자막 시간을 한 번 더 확인한다.

Typecast 웹(Studio)에서 직접 받은 파일을 쓰려면:

```
python aw.py voice <ep> --file 받은파일.wav
```

## 3. 한 장 콘티 (Claude)

```
python aw.py conti <ep>          # episodes/NNN-slug/conti.html
```

실측 음성 기준 장면별 시간, 대사, ChatGPT 이미지 프롬프트, Grok 영상 프롬프트, Grok 권장 길이, 저장 파일명이 한 페이지에 나온다. 각 프롬프트에 복사 버튼이 있다.

탭 세 개:

- **장면별 보기** — 장면마다 대사·설명·프롬프트
- **GPT 이미지 모음** — 캐릭터 시트 + 장면 이미지 프롬프트를 순서대로, 저장 파일명·첨부할 캐릭터 이미지 표시, "전체 복사"
- **Grok 영상 모음** — Grok 장면만, 권장 길이·업로드할 이미지·저장 파일명 표시, "전체 복사"

- **Claude Code** — 이 에피소드 합성용 로컬 Claude Code 지시문 (가로 중앙 정렬 검수 포함), 복사 버튼

같은 내용이 `prompts-chatgpt.txt`, `prompts-grok.txt`, `claude-code.txt`로도 저장된다.

## 4. 이미지·영상 생성 (사용자)

→ [prompt-guide.md](prompt-guide.md)

1. ChatGPT: 캐릭터 기준 이미지 → `images/char_<id>.png`
2. ChatGPT: 장면 이미지 (캐릭터 이미지 첨부) → `images/s01.png` …
3. Grok: 장면 이미지 업로드 + 동작 프롬프트, 콘티의 권장 길이 → `clips/s01.mp4` …

파일명만 맞추면 확장자는 png/jpg/webp 모두 된다. 영상은 mp4.

(선택) 이미지까지만 만든 상태에서 `python aw.py animatic <ep>`로 템포를 먼저 볼 수 있다.

## 5. 합성·검수 (Claude)

```
python aw.py status <ep>         # 빠진 파일 확인
python aw.py compose <ep>        # output/final.mp4 + 검수
```

결과물:

- `output/final.mp4` — 1080×1920, 24fps, 7Mbps, 필재 + 작은 효과음
- `output/final.srt` — 자막
- `output/youtube.txt` — 추천 제목·설명·해시태그
- `output/final-verification.json` — 검수 결과 (가로 중앙 오차, 영역, 원문 일치 등)
- `output/check/final-sheet.jpg` — 장면 모음 (360px 폭)

수정이 필요하면:

| 문제 | 조치 |
|---|---|
| 클립 앞부분이 어색함 | 장면에 `trim_start: 1.2` |
| 효과음이 큼/말소리가 섞임 | 장면에 `sfx_volume: 0.05` 또는 `0` |
| 전체 효과음 조절 | 에피소드에 `sfx_volume: 0.2` |
| 자막 줄바꿈이 어색함 | 대사에 `captions: ["…", "… / …"]` |
| 끝 여운이 짧음 | 에피소드에 `extra_tail_seconds: 1.0` |
| 클립이 없는 장면 | 이미지로 느린 줌 처리 (자동) |

## 클라우드 Claude와 파일 주고받기

claude.ai에서 작업할 때는 PC 폴더를 채팅에 연결(메시지 창 옆 "+" → 폴더 추가)하면 Claude가 그 폴더의 이미지·클립을 가져와 합성하고 결과를 다시 넣는다. claude.ai 작업 공간에서는 Typecast API가 막혀 있으므로 음성은 PC에서 `aw.py tts`로 만들거나 Typecast 웹에서 받는다.
