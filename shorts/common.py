"""공통: 설정 로딩, 에피소드 경로, ffmpeg 실행 도우미."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class ShortsError(RuntimeError):
    pass


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}


def load_project() -> dict:
    return load_yaml(ROOT / "config" / "project.yaml")


def load_style(name: str) -> dict:
    path = ROOT / "styles" / f"{name}.yaml"
    if not path.exists():
        names = ", ".join(p.stem for p in (ROOT / "styles").glob("*.yaml"))
        raise ShortsError(f"화풍 프리셋 없음: {name} (사용 가능: {names})")
    return load_yaml(path)


def load_env_file() -> None:
    """레포 루트의 .env 를 읽어 환경 변수에 넣는다 (이미 설정된 값은 유지)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for raw in env.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


@dataclass
class Line:
    scene: str
    index: int          # 전체 대사 순번 (0부터)
    text: str
    captions: list[str] | None = None


@dataclass
class Episode:
    dir: Path
    data: dict
    project: dict
    style: dict
    lines: list[Line] = field(default_factory=list)

    # ── 경로 ──
    @property
    def audio_dir(self) -> Path: return self.dir / "audio"
    @property
    def images_dir(self) -> Path: return self.dir / "images"
    @property
    def clips_dir(self) -> Path: return self.dir / "clips"
    @property
    def build_dir(self) -> Path: return self.dir / "build"
    @property
    def output_dir(self) -> Path: return self.dir / "output"
    @property
    def raw_voice(self) -> Path: return self.audio_dir / "raw.wav"
    @property
    def voice(self) -> Path: return self.audio_dir / "voice.wav"
    @property
    def timing_path(self) -> Path: return self.audio_dir / "timing.json"

    @property
    def scenes(self) -> list[dict]:
        return self.data.get("scenes") or []

    @property
    def slug(self) -> str:
        return self.dir.name

    def sfx_volume(self) -> float:
        v = self.data.get("sfx_volume")
        return float(self.project["audio"]["sfx_volume"] if v is None else v)

    def script_text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def timing(self) -> dict | None:
        if self.timing_path.exists():
            return json.loads(self.timing_path.read_text(encoding="utf-8"))
        return None


SCENE_ID = re.compile(r"^s\d{2}$")


def clip_parts(scene: dict) -> list[dict]:
    """Grok 장면의 클립 목록. 1번은 장면 자체의 motion_prompt, 2번부터 extra_clips.

    파일명: clips/s01.mp4, clips/s01-2.mp4, clips/s01-3.mp4 …
    """
    if (scene.get("source") or "grok") != "grok":
        return []
    keys = ("motion_prompt", "camera", "trim_start", "sfx_volume", "punch_in", "extras")
    sid = scene["id"]
    parts = [{"n": 1, "file": f"{sid}.mp4", "image": sid, "own_image": False, **{k: scene.get(k) for k in keys}}]
    for i, extra in enumerate(scene.get("extra_clips") or [], start=2):
        own = bool(extra.get("image_prompt"))   # 자기 이미지가 있으면 images/s01-2.png 에서 시작
        parts.append({"n": i, "file": f"{sid}-{i}.mp4", "image": f"{sid}-{i}" if own else sid, "own_image": own,
                      "image_prompt": extra.get("image_prompt"),
                      "characters": extra.get("characters", scene.get("characters")),
                      **{k: extra.get(k) for k in keys}})
    return parts


def load_episode(path: str | Path) -> Episode:
    d = Path(path).resolve()
    if d.is_file():
        d = d.parent
    spec = d / "episode.yaml"
    if not spec.exists():
        raise ShortsError(f"episode.yaml 이 없습니다: {d}")
    data = load_yaml(spec)
    project = load_project()
    style = load_style(data.get("style") or project["style"]["default"])
    ep = Episode(dir=d, data=data, project=project, style=style)
    seen = set()
    idx = 0
    for sc in ep.scenes:
        sid = str(sc.get("id", ""))
        if not SCENE_ID.match(sid):
            raise ShortsError(f"장면 id는 s01 형식이어야 합니다: {sid!r}")
        if sid in seen:
            raise ShortsError(f"장면 id 중복: {sid}")
        seen.add(sid)
        lines = sc.get("lines") or []
        if not lines:
            raise ShortsError(f"{sid}: lines(대사)가 비어 있습니다")
        for item in lines:
            if isinstance(item, str):
                text, caps = item, None
            else:
                text, caps = item.get("text", ""), item.get("captions")
            text = " ".join(str(text).split())
            if not text:
                raise ShortsError(f"{sid}: 빈 대사가 있습니다")
            ep.lines.append(Line(scene=sid, index=idx, text=text, captions=caps))
            idx += 1
    if not ep.lines:
        raise ShortsError("대사가 하나도 없습니다")
    return ep


# ── 외부 도구 ──

def need_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        hint = {
            "ffmpeg": "Windows: winget install Gyan.FFmpeg / Mac: brew install ffmpeg",
            "ffprobe": "ffmpeg 를 설치하면 함께 설치됩니다",
        }.get(name, "")
        raise ShortsError(f"{name} 을(를) 찾을 수 없습니다. {hint}")
    return path


def run(cmd: list, quiet: bool = True, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    proc = subprocess.run(cmd, input=input_bytes, capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-3000:]
        raise ShortsError(f"명령 실패: {' '.join(cmd[:6])} ...\n{err}")
    return proc


def ffprobe_json(path: Path) -> dict:
    need_tool("ffprobe")
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    return json.loads(p.stdout.decode("utf-8"))


def media_duration(path: Path) -> float:
    info = ffprobe_json(path)
    return float(info["format"]["duration"])


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in ffprobe_json(path).get("streams", []))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def say(msg: str) -> None:
    print(msg, flush=True)


def fail(msg: str) -> None:
    print(f"[오류] {msg}", file=sys.stderr, flush=True)
    sys.exit(2)
