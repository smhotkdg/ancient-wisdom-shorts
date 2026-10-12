# episodes/

`python aw.py new <slug>` 로 만든다. 폴더 구조:

    NNN-slug/
      episode.yaml     대본·장면·프롬프트·근거·유튜브 문구 (Git)
      conti.html       한 장 콘티 (Git)
      prompts.json     조립된 프롬프트 (Git)
      audio/           필재 음성·타이밍 (로컬)
      images/          char_<id>.png, sNN.png (로컬)
      clips/           sNN.mp4 (로컬)
      build/           중간 파일 (로컬)
      output/          final.mp4 등 (로컬) — youtube.txt 만 Git
