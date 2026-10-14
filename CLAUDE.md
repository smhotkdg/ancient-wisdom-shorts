# ancient-wisdom-shorts — Claude 작업 규칙

과거 사람들이 난관을 지혜롭게 해결한 이야기를 45~60초 유튜브 쇼츠로 만든다.
예: "폼페이는 왜 길 한가운데 커다란 돌을 놓았을까?", "이집트 사람들은 왜 석상 앞에 물을 부었을까?"
첫 문장은 "○○ 사람들은 멘탈이 나가버렸습니다" 같은 과장된 반응 훅으로 시작하고, 해결 과정을 보여 준다.

이 파일은 어느 PC·어느 Claude(로컬 Claude Code, claude.ai)에서든 같은 방식으로 작업하기 위한 기준이다.
세부 문서: [작업 흐름](docs/workflow.md) · [대본 형식](docs/story-format.md) · [프롬프트](docs/prompt-guide.md) · [팩트 체크](docs/fact-check.md) · [주제 목록](docs/topics.md)

## 분업 (협업 방식)

| 단계 | 담당 | 결과물 |
|---|---|---|
| 1. 주제 찾기·팩트 체크 | Claude | 후보 2~3개 → 사용자 선택 |
| 2. 대본·장면 설계 | Claude — **스토리형** (`.claude/skills/shorts-story`) → `aw.py story` 점검 | `episodes/NNN-slug/episode.yaml` |
| 3. 필재 음성 | Claude (`aw.py tts`) | `audio/raw.wav` → 타이밍 |
| 4. 한 장 콘티 | Claude (`aw.py conti`) | `conti.html` (장면별 / GPT 모음 / Grok 모음 탭, 전체 복사) + `prompts-chatgpt.txt`, `prompts-grok.txt` |
| 5. 이미지·영상 생성 | **사용자** — ChatGPT 이미지, Grok 영상 | `images/sNN.png`, `clips/sNN.mp4` |
| 6. 최종 합성·검수 | Claude (`aw.py compose`) | `output/final.mp4` + 검수 + 유튜브 문구 |

필요하면 단계 4와 5 사이에 `aw.py animatic`(이미지만으로 만든 가편집)으로 템포를 먼저 확인한다.

## 명령

```
python aw.py doctor            # 이 PC 환경 점검
python aw.py new <slug>        # 새 에피소드
python aw.py script <ep>       # 대본 글자 수·예상 길이
python aw.py captions <ep>     # 자막 나눔 미리보기
python aw.py story <ep>        # 스토리 구조 점검 (주인공·시도·실패·깨달음·보상)
python aw.py check-voice       # Typecast 인증·필재 확인 (크레딧 0)
python aw.py tts <ep>          # 필재 생성 (크레딧 사용) → 타이밍
python aw.py voice <ep> --file F   # 다른 곳에서 받은 음성 사용
python aw.py conti <ep>        # 한 장 콘티
python aw.py animatic <ep>     # 가편집 + 검수
python aw.py compose <ep>      # 최종 합성 + 검수
python aw.py status <ep>       # 준비 상태
python aw.py selftest          # 가짜 소스로 전체 흐름 시험 (비용 0)
```

## 반드시 지킬 것

1. **팩트 체크**: 주제마다 신뢰할 근거 2개 이상(대학·박물관·학술지·공공기관). 전승과 검증된 사실을 구분하고 `accuracy_notes`에 적는다. 확인 안 된 수치·인용을 만들지 않는다. → [fact-check.md](docs/fact-check.md)
2. **대본은 스토리형**: 원리를 나열하지 않고 주인공 한 명이 시도 → 실패 → 깨달음 → 보상으로 풀어 간다 ([shorts-story 스킬](.claude/skills/shorts-story/SKILL.md)). 시도 순서·감정은 재구성임을 `accuracy_notes`에 적고, 지어낸 기록·이름·날짜는 쓰지 않는다. `aw.py story`가 통과해야 음성을 만든다.
2-1. **훅은 현대 화자의 연출**이다. "멘탈이 나가버렸습니다"를 당시 기록이나 실제 발언처럼 쓰지 않는다. 같은 반응어를 연달아 쓰지 않는다(사용 기록: [topics.md](docs/topics.md)).
3. **목소리는 Typecast 필재 original + ssfm-v30만** 쓴다. voice_id는 매번 인증된 목록에서 다시 찾고, 다른 목소리로 몰래 바꾸지 않는다.
4. **유료 생성 전 알리기**: `tts`는 대본 글자 수만큼 Typecast 크레딧을 쓴다. 생성 전에 글자 수를 말하고 승인받는다. 기존 음성은 덮어쓰지 않는다(`--force`는 승인 후). 네트워크 오류로 결과가 불명확하면 자동으로 다시 생성하지 않는다.
5. **음성 먼저, 화면은 음성에 맞춘다.** 대사를 빨리 감거나 자르지 않는다. 길면 영상을 늘린다.
6. **텍스트 레이아웃 v7 고정** (`config/project.yaml`): 제목 두 줄(흰색/노란색) 블록 중심 (540,279), 줄 사이 간격 좁게(실제 약 36px), 자막 블록 중심 (540,1360) 64px·최대 두 줄. 에피소드에서 좌표를 바꾸지 않는다.
7. **가로 중앙 정렬 필수**: 모든 제목·자막 줄은 외곽선 포함 실제 픽셀 기준 좌우 여백 차 2px 이내. 렌더 후 `verify`가 오버레이를 다시 측정해 확인한다. 실패하면 납품하지 않는다. 영상 소스도 가운데 기준으로 대칭 크롭한다.
8. **자막 배경 없음**: 패널·띠·박스·블러 금지. 상단 진행 칩·단계 제목·부품 라벨 금지. 화면 텍스트는 고정 제목 + 대사 자막뿐.
9. **자막은 대본의 모든 단어를** 의미 단위로 보여 준다. 자동 나눔이 어색하면 `episode.yaml`의 `captions`로 직접 쓴다.
10. **매 영상마다 유튜브 추천 제목·설명 문구**를 함께 낸다 (`episode.yaml`의 `youtube` → `output/youtube.txt`).
11. **Grok 클립 원음은 효과음으로만 작게** 남긴다 (기본 `audio.sfx_volume: 0.12`, 에피소드·장면별로 바꿀 수 있음). 말소리·음악이 섞인 클립은 그 장면만 `sfx_volume: 0`.
12. **화풍은 프리셋으로** 바꾼다 (`styles/*.yaml`, 기본 3d-cartoon). 프롬프트에 화풍 문구를 직접 박아 넣지 않는다.
13. **Git에는 텍스트만**: 이미지·영상·음성·빌드 결과·키는 올리지 않는다(.gitignore). 에피소드 폴더의 `episode.yaml`, `conti.html`, `prompts.json`, `prompts-chatgpt.txt`, `prompts-grok.txt`, `output/youtube.txt`는 올린다.
14. 납품 전 `output/check/final-sheet.jpg`(360px 폭 장면 모음)를 직접 보고 자막이 핵심 동작을 가리지 않는지 확인한다.

## 환경 메모

- 필요: Python 3.10+, `pip install -r requirements.txt`, ffmpeg, Noto Sans KR(Black·Bold) 폰트. `python aw.py doctor`로 확인.
- Typecast 키는 레포 루트 `.env`의 `TYPECAST_API_KEY` (Git 제외). 음성을 만드는 PC에만 필요.
- claude.ai 클라우드 작업 공간에서는 Typecast API 접속이 막혀 있다. 그때는 사용자 PC에서 `aw.py tts`를 실행하거나, Typecast 웹에서 받은 파일을 `aw.py voice --file`로 넣는다.
- 렌더는 한 번에 하나만 돌린다.
