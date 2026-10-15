"""Typecast 필재 TTS (checkvalve-shorts-production 의 검증된 연동 방식을 그대로 따른다).

- 키는 환경 변수 TYPECAST_API_KEY 또는 레포 루트 .env 에서만 읽는다. 키/오류 본문은 출력하지 않는다.
- voice_id 는 매번 인증된 /v3/voices 목록에서 '필재' original + ssfm-v30 으로 다시 찾는다.
- 기존 출력은 덮어쓰지 않는다. 네트워크 오류로 결과가 불명확하면 자동 재시도하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from .common import Episode, ShortsError, load_env_file, write_json

BASE = "https://api.typecast.ai"


def api_key() -> str:
    load_env_file()
    key = os.environ.get("TYPECAST_API_KEY", "").strip()
    if not key and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                key = str(winreg.QueryValueEx(reg, "TYPECAST_API_KEY")[0]).strip()
        except OSError:
            pass
    if not key:
        raise ShortsError("TYPECAST_API_KEY 가 없습니다. 레포 루트에 .env 를 만들고 TYPECAST_API_KEY=... 를 넣으세요.")
    return key


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _request(path: str, key: str, payload: dict | None = None) -> bytes:
    raw = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=raw,
                                 headers={"X-API-KEY": key, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        raise ShortsError(f"TYPECAST_HTTP_{exc.code}") from None
    except urllib.error.URLError:
        raise ShortsError("TYPECAST_NETWORK_ERROR — 제출 여부가 불명확합니다. 자동으로 다시 생성하지 마세요. "
                          "Typecast 사용량을 확인한 뒤 진행하세요.") from None


def resolve_voice(project: dict, key: str) -> dict:
    vc = project["voice"]
    voices = json.loads(_request("/v3/voices", key))
    matches = [v for v in voices if isinstance(v.get("voice_name"), dict)
               and v["voice_name"].get("kor") == vc["name_kor"] and v.get("voice_type") == vc["voice_type"]]
    if len(matches) != 1:
        raise ShortsError(f"필재 음성을 하나로 특정할 수 없습니다 (찾은 수: {len(matches)}). 다른 목소리로 대체하지 않습니다.")
    v = matches[0]
    models = {m.get("version") for m in v.get("models", [])}
    if vc["model"] not in models:
        raise ShortsError(f"필재가 {vc['model']} 를 지원하지 않습니다: {sorted(models)}")
    return v


def check(project: dict) -> dict:
    """생성 없이 인증과 필재 확인만."""
    key = api_key()
    v = resolve_voice(project, key)
    return {"status": "piljae_verified", "voice_id": v["voice_id"], "models": [m.get("version") for m in v.get("models", [])]}


def _wav_ok(data: bytes) -> None:
    if not (data.startswith(b"RIFF") and data[8:12] == b"WAVE"):
        raise ShortsError("Typecast 응답이 WAV 가 아닙니다")


def _backup_existing(ep: Episode) -> None:
    """--force 로 다시 만들 때 이전 음성을 지우지 않고 audio/prev/ 로 옮긴다."""
    if not ep.raw_voice.exists():
        return
    prev = ep.audio_dir / "prev"
    prev.mkdir(exist_ok=True)
    for name in ("raw.wav", "voice.wav", "timing.json", "tts.json", "lines.json"):
        f = ep.audio_dir / name
        if f.exists():
            f.replace(prev / name)


def generate(ep: Episode, force: bool = False, per_line: bool | None = None) -> dict:
    vc = ep.project["voice"]
    text = ep.script_text()
    if len(text) > int(vc["max_script_chars"]):
        raise ShortsError(f"대본이 너무 깁니다 ({len(text)}자)")
    out = ep.raw_voice
    if out.exists() and not force:
        raise ShortsError(f"이미 음성이 있습니다: {out} (다시 만들려면 --force, 크레딧이 사용됩니다)")
    per_line = bool(vc.get("per_line", False)) if per_line is None else per_line
    if per_line:
        raise ShortsError("문장별 생성은 쓰지 않습니다 — 음성은 대본 전체를 파일 하나로 받습니다 (voice.per_line: false)")
    key = api_key()
    v = resolve_voice(ep.project, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    _backup_existing(ep)

    def synth(t: str) -> bytes:
        payload = {"model": vc["model"], "voice_id": v["voice_id"], "text": t,
                   "output": {"audio_format": vc["format"], "audio_tempo": float(vc["tempo"])}}
        data = _request("/v1/text-to-speech", key, payload)
        _wav_ok(data)
        return data

    if per_line:
        from .lines_audio import assemble
        parts_dir = ep.audio_dir / "lines"
        parts_dir.mkdir(exist_ok=True)
        files = []
        for line in ep.lines:
            f = parts_dir / f"{line.index:02d}.wav"
            if not f.exists():          # 중간에 끊겼다면 이미 받은 문장은 다시 만들지 않는다
                f.write_bytes(synth(line.text))
            files.append(f)
        assemble(ep, files)
        n_bytes = sum(f.stat().st_size for f in files)
    else:
        data = synth(text)
        out.write_bytes(data)
        n_bytes = len(data)
        (ep.audio_dir / "lines.json").unlink(missing_ok=True)
    info = {"provider": "typecast", "voice": vc["name_kor"], "voice_id": v["voice_id"], "model": vc["model"],
            "tempo": vc["tempo"], "characters": len(text), "bytes": n_bytes, "per_line": per_line}
    write_json(ep.audio_dir / "tts.json", info)
    return info
