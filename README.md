# ancient-wisdom-shorts

과거 사람들이 난관을 지혜롭게 해결한 이야기를 45~60초 유튜브 쇼츠로 만드는 제작 레포.

> 이집트 사람들은 멘탈이 나가버렸습니다. 석상이 모래에 파묻혀 꿈쩍도 안 했거든요…

**Claude** 주제·대본·Typecast 필재 음성·한 장 콘티 → **사용자** ChatGPT 이미지·Grok 영상 → **Claude** 최종 합성·검수·유튜브 문구

## 시작하기

```
git clone https://github.com/smhotkdg/ancient-wisdom-shorts.git
cd ancient-wisdom-shorts
pip install -r requirements.txt
python aw.py doctor      # ffmpeg, 한글 폰트, 패키지 확인
python aw.py selftest    # 가짜 소스로 전체 흐름 시험 (비용 0)
```

음성을 만들 PC에서는 `.env.example`을 `.env`로 복사해 `TYPECAST_API_KEY`를 넣는다.

## 구성

```
aw.py                 명령 도구 (python aw.py -h)
CLAUDE.md             Claude 작업 규칙 — 어느 PC에서든 이 기준으로 작업
config/project.yaml   공통 설정: 화면, 필재, 음량, 텍스트 레이아웃 v6
styles/*.yaml         화풍 프리셋 (기본 3d-cartoon)
templates/episode/    새 에피소드 틀
episodes/NNN-slug/    에피소드별 episode.yaml · conti.html · images/ · clips/ · output/
docs/                 작업 흐름 · 대본 형식 · 프롬프트 · 팩트 체크 · 주제 기록
shorts/               파이프라인 코드
```

미디어(이미지·영상·음성·결과물)는 Git에 올리지 않는다.

## 출력

`output/final.mp4` 1080×1920 · 24fps · 7Mbps · 필재 내레이션 + 작은 효과음, 고정 제목 + 대사 자막(패널 없음),
`final.srt`, `youtube.txt`(추천 제목·설명), `final-verification.json`(가로 중앙 정렬 등 검수), `check/final-sheet.jpg`.
