#!/usr/bin/env python3
"""Opt-in, cooperative idle rainbow for Yandex Station Mini 2.

The effect is allowed only after Quasar explicitly reports Alice IDLE/NONE and
all 18 ring channels have remained dark for a grace period. While active, any
Alice busy/unknown/disconnected state or any unexpected LED value makes the
process yield without touching the native renderer's frame.

This is experimental: sysfs has no ownership lock, so a tiny write race remains.
"""
from __future__ import annotations

import colorsys
import fcntl
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path("/data/opt/mini2-web-panel")
PID_FILE = ROOT / ".idle-rainbow.pid"
STATUS_FILE = ROOT / ".idle-rainbow.status"
LOCK_FILE = ROOT / ".idle-rainbow.lock"
LED_DIR = Path("/sys/class/leds")
IPC_HOST = "127.0.0.1"
IPC_PORT = 9875
MAX_FRAME = 512 * 1024
IDLE_DWELL = 6.0
POLL_INTERVAL = 0.025
FRAME_INTERVAL = 0.12
RING_CHANNELS = [(zone, color) for zone in range(1, 7) for color in ("red", "green", "blue")]
_STOP = False


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while pos < len(data) and shift < 70:
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise ValueError("protobuf varint overflow")
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, pos
        shift += 7
    raise ValueError("truncated protobuf varint")


def _fields(data: bytes) -> dict[int, int | bytes]:
    fields: dict[int, int | bytes] = {}
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("invalid protobuf field number")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            end = pos + 8
            if end > len(data):
                raise ValueError("truncated fixed64")
            pos = end
            continue
        elif wire == 2:
            length, pos = _varint(data, pos)
            end = pos + length
            if end > len(data):
                raise ValueError("truncated length-delimited field")
            value = data[pos:end]
            pos = end
        elif wire == 5:
            end = pos + 4
            if end > len(data):
                raise ValueError("truncated fixed32")
            pos = end
            continue
        else:
            raise ValueError("unsupported protobuf wire type")
        fields[number] = value
    return fields


def alice_activity(message: bytes) -> str | None:
    """Return idle/busy/unknown for Quasar AliceState; ignore other messages."""
    try:
        envelope = _fields(message)
        if envelope.get(253) != 3:
            return None
        payload = envelope.get(252)
        if not isinstance(payload, bytes):
            return "unknown"
        state = _fields(payload).get(1)
        if not isinstance(state, int):
            return "unknown"
        if state in (0, 6):  # IDLE / NONE
            return "idle"
        if state in (1, 2, 3, 5):  # LISTENING / SPEAKING / BUSY / SHAZAM
            return "busy"
        return "unknown"
    except (ValueError, OverflowError):
        return "unknown"


class FrameDecoder:
    """Decode Quasar's little-endian length-prefixed protobuf stream."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        self.buffer.extend(data)
        states: list[str] = []
        while len(self.buffer) >= 4:
            size = struct.unpack_from("<I", self.buffer)[0]
            if size == 0 or size > MAX_FRAME:
                self.buffer.clear()
                raise ValueError("invalid Quasar frame size")
            if len(self.buffer) < 4 + size:
                break
            message = bytes(self.buffer[4 : 4 + size])
            del self.buffer[: 4 + size]
            state = alice_activity(message)
            if state is not None:
                states.append(state)
        if len(self.buffer) > MAX_FRAME + 4:
            self.buffer.clear()
            raise ValueError("Quasar frame buffer limit exceeded")
        return states


def channel_path(zone: int, color: str) -> Path:
    return LED_DIR / f"mini2:{color}:ring{zone}" / "brightness"


def read_ring() -> list[int] | None:
    values: list[int] = []
    try:
        for zone, color in RING_CHANNELS:
            raw = channel_path(zone, color).read_text(encoding="ascii").strip()
            value = int(raw)
            if not 0 <= value <= 255:
                return None
            values.append(value)
    except (OSError, ValueError, UnicodeError):
        return None
    return values


def is_dark(values: list[int] | None) -> bool:
    return values is not None and all(value == 0 for value in values)


def rainbow_frame(phase: int, brightness: int = 64) -> list[int]:
    values: list[int] = []
    for zone in range(6):
        hue = ((phase * 3) + (zone * 256 // 6)) % 256
        red, green, blue = colorsys.hsv_to_rgb(hue / 256.0, 1.0, brightness / 255.0)
        values.extend((round(red * 255), round(green * 255), round(blue * 255)))
    return values


def _write_status(state: str, activity: str, detail: str = "") -> None:
    payload = {"state": state, "alice": activity, "detail": detail}
    temp = STATUS_FILE.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="ascii")
        os.chmod(temp, 0o600)
        temp.replace(STATUS_FILE)
    except OSError:
        pass


def _write_frame(values: list[int]) -> bool:
    try:
        for (zone, color), value in zip(RING_CHANNELS, values):
            channel_path(zone, color).write_text(f"{value}\n", encoding="ascii")
        return True
    except OSError:
        return False


def _release_if_owned(last_frame: list[int] | None, clear: bool) -> None:
    if last_frame is None:
        return
    current = read_ring()
    # Only clear the ring if every value is still exactly ours. If Quasar has
    # changed even one channel, leave the whole frame untouched.
    if current == last_frame and clear:
        _write_frame([0] * 18)


def _signal_stop(_signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True


def run_monitor() -> int:
    global _STOP
    if os.geteuid() != 0:
        print("Run the idle rainbow test as root.", file=sys.stderr)
        return 1

    signal.signal(signal.SIGTERM, _signal_stop)
    signal.signal(signal.SIGINT, _signal_stop)
    activity: str | None = None
    sock: socket.socket | None = None
    decoder = FrameDecoder()
    retry_at = 0.0
    dark_since: float | None = None
    last_frame: list[int] | None = None
    phase = 0
    next_frame = 0.0
    state = "waiting-for-quasar"
    _write_status(state, "unknown", "No LED or .led files changed")

    try:
        while not _STOP:
            now = time.monotonic()
            if sock is None and now >= retry_at:
                activity = None
                dark_since = None
                decoder = FrameDecoder()
                try:
                    sock = socket.create_connection((IPC_HOST, IPC_PORT), timeout=1.0)
                    sock.setblocking(False)
                    state = "waiting-for-alice-state"
                except OSError:
                    retry_at = now + 2.0
                    state = "quasar-ipc-unavailable"
                    _release_if_owned(last_frame, clear=False)
                    last_frame = None
                _write_status(state, "unknown", "Waiting for Quasar IPC on 127.0.0.1:9875")

            if sock is not None:
                try:
                    readable, _, _ = select.select([sock], [], [], POLL_INTERVAL)
                    if readable:
                        chunk = sock.recv(65536)
                        if not chunk:
                            raise ConnectionError("Quasar IPC disconnected")
                        for new_activity in decoder.feed(chunk):
                            activity = new_activity
                            if activity == "busy":
                                _release_if_owned(last_frame, clear=False)
                                last_frame = None
                                dark_since = None
                                state = "yielded-to-alice"
                            elif activity == "unknown":
                                _release_if_owned(last_frame, clear=False)
                                last_frame = None
                                dark_since = None
                                state = "waiting-for-alice-state"
                except (OSError, ValueError, ConnectionError):
                    try:
                        sock.close()
                    except OSError:
                        pass
                    sock = None
                    activity = None
                    retry_at = time.monotonic() + 2.0
                    _release_if_owned(last_frame, clear=False)
                    last_frame = None
                    dark_since = None
                    state = "quasar-ipc-unavailable"

            if _STOP:
                break

            now = time.monotonic()
            current = read_ring()
            if activity != "idle":
                dark_since = None
                if last_frame is not None and activity == "busy":
                    _release_if_owned(last_frame, clear=False)
                    last_frame = None
                    state = "yielded-to-alice"
                elif last_frame is not None and current != last_frame:
                    _release_if_owned(last_frame, clear=False)
                    last_frame = None
                if state not in ("quasar-ipc-unavailable", "yielded-to-alice"):
                    state = "waiting-for-alice-state"
                _write_status(state, activity or "unknown", "Requires an explicit Alice IDLE/NONE event")
                time.sleep(POLL_INTERVAL)
                continue

            if current is None:
                dark_since = None
                last_frame = None
                state = "led-read-unavailable"
                _write_status(state, activity, "Cannot read all 18 Mini 2 ring channels")
                time.sleep(POLL_INTERVAL)
                continue

            if last_frame is not None and current != last_frame:
                # Quasar or another renderer owns the ring now. Never restore
                # the old values over its new frame.
                last_frame = None
                dark_since = None
                state = "yielded-to-quasar"
                _write_status(state, activity, "A native LED value changed; yielded without restoring")
                time.sleep(POLL_INTERVAL)
                continue

            if last_frame is None:
                if not is_dark(current):
                    dark_since = None
                    state = "waiting-for-dark-ring"
                    _write_status(state, activity, "Waiting for all 18 channels to remain at zero")
                    time.sleep(POLL_INTERVAL)
                    continue
                if dark_since is None:
                    dark_since = now
                if now - dark_since < IDLE_DWELL:
                    state = "waiting-for-dark-ring"
                    _write_status(state, activity, "Ring must stay dark for 6 seconds")
                    time.sleep(POLL_INTERVAL)
                    continue
                last_frame = [0] * 18
                state = "rainbow-active"

            if now >= next_frame:
                frame = rainbow_frame(phase)
                if not _write_frame(frame):
                    _release_if_owned(last_frame, clear=False)
                    last_frame = None
                    dark_since = None
                    state = "led-write-unavailable"
                    _write_status(state, activity, "LED write failed; waiting for native idle state")
                else:
                    last_frame = frame
                    phase = (phase + 1) % 256
                    next_frame = now + FRAME_INTERVAL
                    # Close the race window: if Quasar changed anything while
                    # the 18 values were being written, stop at once.
                    after = read_ring()
                    if after != last_frame:
                        last_frame = None
                        dark_since = None
                        state = "yielded-to-quasar"
                        _write_status(state, activity, "Native LED values won the ownership check")
                    else:
                        _write_status(state, activity, "Rainbow active; no stock .led files are modified")
            time.sleep(POLL_INTERVAL)
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        _release_if_owned(last_frame, clear=True)
        _write_status("stopped", activity or "unknown", "Monitor stopped")
    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return any(b"idle-rainbow.py" in part for part in command) and b"run" in command
    except OSError:
        return False


def _read_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        return pid if pid > 1 else None
    except (OSError, ValueError):
        return None


def _control_locked(function):
    def wrapped(*args, **kwargs):
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return function(*args, **kwargs)
        finally:
            os.close(fd)
    return wrapped


def command_status() -> int:
    pid = _read_pid()
    running = pid is not None and _pid_alive(pid)
    if not running:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        result = {"available": True, "running": False, "state": "stopped", "alice": "unknown"}
    else:
        try:
            state = json.loads(STATUS_FILE.read_text(encoding="ascii"))
        except (OSError, json.JSONDecodeError):
            state = {"state": "starting", "alice": "unknown", "detail": "Waiting for monitor status"}
        result = {"available": True, "running": True, **state}
    print(json.dumps(result, separators=(",", ":")))
    return 0


@_control_locked
def command_start() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "root_required"}))
        return 1
    if not Path(sys.executable).exists():
        print(json.dumps({"error": "python3_missing"}))
        return 1
    pid = _read_pid()
    if pid is not None and _pid_alive(pid):
        return command_status()
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.unlink(missing_ok=True)
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "run"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        temp_pid = PID_FILE.with_suffix(".tmp")
        temp_pid.write_text(f"{child.pid}\n", encoding="ascii")
        os.chmod(temp_pid, 0o600)
        temp_pid.replace(PID_FILE)
        time.sleep(0.15)
        if not _pid_alive(child.pid):
            PID_FILE.unlink(missing_ok=True)
            print(json.dumps({"error": "monitor_failed_to_start"}))
            return 1
        return command_status()
    except OSError as exc:
        print(json.dumps({"error": f"start_failed:{exc.__class__.__name__}"}))
        return 1


@_control_locked
def command_stop() -> int:
    pid = _read_pid()
    if pid is None or not _pid_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        print(json.dumps({"available": True, "running": False, "state": "stopped", "alice": "unknown"}))
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.05)
    if _pid_alive(pid):
        print(json.dumps({"error": "monitor_did_not_stop_gracefully"}))
        return 1
    PID_FILE.unlink(missing_ok=True)
    print(json.dumps({"available": True, "running": False, "state": "stopped", "alice": "unknown"}))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"start", "stop", "status", "run"}:
        print("Usage: idle-rainbow.py {start|stop|status|run}", file=sys.stderr)
        return 2
    command = sys.argv[1]
    if command == "run":
        return run_monitor()
    if command == "start":
        return command_start()
    if command == "stop":
        return command_stop()
    return command_status()


if __name__ == "__main__":
    raise SystemExit(main())
