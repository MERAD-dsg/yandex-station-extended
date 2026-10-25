#!/usr/bin/env python3
"""Authenticated-panel helper for one bounded MP3/WAV upload and local playback."""
from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path("/data/opt/mini2-web-panel")
PID_FILE = ROOT / ".audio-player.pid"
LOCK_FILE = ROOT / ".audio-player.lock"
META_FILE = ROOT / ".audio-upload.json"
LOG_FILE = ROOT / "audio-player.log"
QUASAR_DIR = Path("/system/vendor/quasar")
MAIND = QUASAR_DIR / "maind"
MAX_UPLOAD = 10 * 1024 * 1024
RESERVE_BYTES = 5 * 1024 * 1024
ALLOWED = {".mp3", ".wav"}


def _json(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")))


def _file_for(ext: str) -> Path:
    if ext not in ALLOWED:
        raise ValueError("Поддерживаются только MP3 и WAV")
    return ROOT / f".audio-track{ext}"


def detect_format(filename: str, data: bytes) -> str:
    """Validate a narrow extension/signature allow-list; never trust MIME headers."""
    ext = Path(filename.replace("\\", "/")).suffix.lower()
    if ext not in ALLOWED:
        raise ValueError("Выберите файл MP3 или WAV")
    if ext == ".wav":
        valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    else:
        valid = len(data) >= 4 and (
            data[:3] == b"ID3"
            or any(
                data[i] == 0xFF and data[i + 1] & 0xE0 == 0xE0 and data[i + 1] & 0x06 != 0
                for i in range(min(len(data) - 1, 4096))
            )
        )
    if not valid:
        raise ValueError("Содержимое не похоже на заявленный MP3/WAV файл")
    return ext


def safe_display_name(filename: str, ext: str) -> str:
    base = Path(filename.replace("\\", "/")).name
    base = re.sub(r"[^\w .()\-]", "_", base, flags=re.UNICODE).strip(" .")[:120]
    if not base or Path(base).suffix.lower() != ext:
        base = (Path(base).stem or "audio") + ext
    return base


def _metadata() -> dict[str, object]:
    try:
        value = json.loads(META_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("ext") in ALLOWED and isinstance(value.get("name"), str):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _player_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        joined = b" ".join(args)
        return (
            any(b"maind" in arg for arg in args)
            and b"--gst-launch" in args
            and b"filesrc location=/data/opt/mini2-web-panel/.audio-track" in joined
        )
    except OSError:
        return False


def _read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        return pid if pid > 1 else None
    except (OSError, ValueError):
        return None


def _stop_player() -> None:
    pid = _read_pid()
    if pid is not None and _player_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and _player_alive(pid):
            time.sleep(0.05)
        if _player_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def _locked(function):
    def wrapped(*args: object) -> dict[str, object]:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return function(*args)
        finally:
            os.close(fd)
    return wrapped


def command_status() -> dict[str, object]:
    meta = _metadata()
    path = _file_for(str(meta["ext"])) if meta else None
    if path is not None and not path.is_file():
        meta = {}
        path = None
    pid = _read_pid()
    playing = pid is not None and _player_alive(pid)
    if not playing and pid is not None:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    size = path.stat().st_size if path is not None else 0
    return {
        "available": True,
        "uploaded": path is not None,
        "filename": meta.get("name", ""),
        "size": size,
        "playing": playing,
    }


def command_upload() -> dict[str, object]:
    try:
        length = int(os.environ.get("CONTENT_LENGTH", ""))
    except ValueError:
        raise ValueError("Не удалось определить размер загрузки") from None
    if length <= 0:
        raise ValueError("Файл пуст или запрос загрузки некорректен")
    if length > MAX_UPLOAD:
        raise ValueError("Максимальный размер файла — 10 МиБ")
    data = sys.stdin.buffer.read(length)
    if len(data) != length:
        raise ValueError("Загрузка оборвалась до получения всего файла")

    query = parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)
    filename = query.get("name", [""])[0]
    if not filename or len(filename) > 240:
        raise ValueError("Имя файла отсутствует или слишком длинное")
    ext = detect_format(filename, data)
    display_name = safe_display_name(filename, ext)
    available = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
    if available < len(data) + RESERVE_BYTES:
        raise ValueError("Недостаточно свободного места в /data")

    _stop_player()
    destination = _file_for(ext)
    fd, temporary = tempfile.mkstemp(prefix=".audio-upload-", dir=ROOT)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    for old_ext in ALLOWED - {ext}:
        try:
            _file_for(old_ext).unlink()
        except FileNotFoundError:
            pass
    meta_temp = META_FILE.with_name(META_FILE.name + ".tmp")
    meta_temp.write_text(json.dumps({"ext": ext, "name": display_name}), encoding="utf-8")
    os.chmod(meta_temp, 0o600)
    os.replace(meta_temp, META_FILE)
    return {"ok": True, **command_status()}


@_locked
def locked_upload() -> dict[str, object]:
    return command_upload()


@_locked
def command_play() -> dict[str, object]:
    meta = _metadata()
    if not meta:
        raise ValueError("Сначала загрузите MP3 или WAV файл")
    track = _file_for(str(meta["ext"]))
    if not track.is_file():
        raise ValueError("Загруженный файл не найден")
    if not MAIND.is_file():
        raise ValueError("На прошивке не найден Quasar GStreamer player (maind)")
    _stop_player()
    pipeline = f'filesrc location="{track}" ! decodebin ! audioconvert ! audioresample ! alsasink'
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{QUASAR_DIR}:{QUASAR_DIR / 'libs'}"
    try:
        with LOG_FILE.open("wb") as log:
            child = subprocess.Popen(
                [str(MAIND), "--gst-launch", pipeline],
                cwd=QUASAR_DIR,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
                env=env,
            )
        pid_temp = PID_FILE.with_name(PID_FILE.name + ".tmp")
        pid_temp.write_text(f"{child.pid}\n", encoding="ascii")
        os.chmod(pid_temp, 0o600)
        os.replace(pid_temp, PID_FILE)
    except OSError as exc:
        raise ValueError(f"Не удалось запустить плеер ({exc.__class__.__name__})") from None
    time.sleep(1.0)
    if not _player_alive(child.pid):
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        try:
            tail = LOG_FILE.read_bytes()[-1200:].decode("utf-8", "replace").strip()
        except OSError:
            tail = ""
        detail = re.sub(r"[\r\n]+", " ", tail)[-500:]
        raise ValueError("Плеер не запустился; проверьте MP3/WAV декодер и ALSA. " + detail)
    return {"ok": True, **command_status()}


@_locked
def command_stop() -> dict[str, object]:
    _stop_player()
    return {"ok": True, **command_status()}


@_locked
def command_delete() -> dict[str, object]:
    _stop_player()
    for ext in ALLOWED:
        try:
            _file_for(ext).unlink()
        except FileNotFoundError:
            pass
    try:
        META_FILE.unlink()
    except FileNotFoundError:
        pass
    return {"ok": True, **command_status()}


def main() -> int:
    if os.geteuid() != 0:
        _json({"error": "Для управления плеером требуется root"})
        return 0
    if len(sys.argv) != 2 or sys.argv[1] not in {"status", "upload", "play", "stop", "delete"}:
        _json({"error": "Неизвестная команда плеера"})
        return 0
    command = sys.argv[1]
    try:
        if command == "status":
            result = command_status()
        elif command == "upload":
            result = locked_upload()
        elif command == "play":
            result = command_play()
        elif command == "stop":
            result = command_stop()
        else:
            result = command_delete()
    except (OSError, ValueError) as exc:
        result = {"error": str(exc)}
    _json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
