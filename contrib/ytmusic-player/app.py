#!/usr/bin/env python3
"""LAN web remote for YouTube Music search and playback on a rooted Yandex Station.

Search/player metadata use the unofficial InnerTube protocol. Audio is fetched by
GStreamer's souphttpsrc on the Station, not relayed or stored by this app.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import shlex
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from innertube import InnerTube
from paramiko import RejectPolicy, SSHClient, SSHException
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
WEB_TOKEN = os.environ.get("YTM_WEB_TOKEN") or secrets.token_urlsafe(18)
STATION_HOST = os.environ.get("YTM_STATION_HOST", "").strip()
STATION_PORT = int(os.environ.get("YTM_STATION_PORT", "2222"))
STATION_USER = os.environ.get("YTM_STATION_USER", "root")
PLAYER_PID = "/tmp/ytmusic-player.pid"
PLAYER_LOG = "/data/opt/ytmusic-player.log"
SEARCH_CLIENTS = ("WEB_REMIX", "ANDROID_MUSIC")
PLAYER_CLIENTS = ("WEB_REMIX", "ANDROID_MUSIC", "TVHTML5_AUDIO")

app = FastAPI(title="YT Music → Station", docs_url=None, redoc_url=None)
_clients: dict[str, InnerTube] = {}
_clients_lock = threading.Lock()

# Narrow allow-list: never forward every cookie from a browser export.
_AUTH_COOKIE_NAMES = {
    "SAPISID", "APISID", "SID", "HSID", "SSID", "LOGIN_INFO",
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "PREF", "YSC", "VISITOR_INFO1_LIVE", "__Secure-ROLLOUT_TOKEN",
}
_HASH_COOKIE_PREFIXES = (
    ("SAPISID", "SAPISIDHASH"),
    ("__Secure-1PAPISID", "SAPISID1PHASH"),
    ("__Secure-3PAPISID", "SAPISID3PHASH"),
)
_AUTH_ORIGIN = "https://music.youtube.com"


class PlayRequest(BaseModel):
    video_id: str = Field(min_length=6, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(default="YouTube Music", max_length=300)


def _read_yt_cookies() -> dict[str, str]:
    """Read a browser-exported Netscape cookies.txt without logging its contents."""
    filename = os.environ.get("YTM_COOKIE_FILE", "").strip()
    if not filename:
        return {}
    path = Path(filename).expanduser()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"Не удалось прочитать YTM_COOKIE_FILE ({path}): {exc}") from exc

    cookies: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7:  # Netscape format: domain, flags, path, secure, expiry, name, value
            domain, name, value = fields[0].lower().lstrip("."), fields[5], fields[6]
            try:
                expires = int(fields[4])
            except ValueError:
                expires = 0
            allowed_domain = (
                domain == "youtube.com" or domain.endswith(".youtube.com")
                or domain == "google.com" or domain.endswith(".google.com")
            )
            if expires and expires < time.time():
                continue
            if allowed_domain and name in _AUTH_COOKIE_NAMES:
                cookies[name] = value
        elif "=" in line:  # also accept a raw Cookie header saved as one line
            for part in line.split(";"):
                name, separator, value = part.strip().partition("=")
                if separator and name in _AUTH_COOKIE_NAMES:
                    cookies[name] = value.strip()
    if not any(name in cookies for name, _prefix in _HASH_COOKIE_PREFIXES):
        raise RuntimeError("В YTM_COOKIE_FILE нет SAPISID / __Secure-1PAPISID / __Secure-3PAPISID")
    return cookies


def _auth_headers(cookies: dict[str, str]) -> dict[str, str]:
    """Build the SAPISIDHASH authorization header used by YouTube web clients."""
    timestamp = str(int(time.time()))
    parts: list[str] = []
    # YouTube's web client uses the 3P cookie as a fallback for SAPISID too.
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")
    values = [sapisid, cookies.get("__Secure-1PAPISID"), cookies.get("__Secure-3PAPISID")]
    for (_cookie_name, prefix), value in zip(_HASH_COOKIE_PREFIXES, values):
        if value:
            digest = hashlib.sha1(f"{timestamp} {value} {_AUTH_ORIGIN}".encode()).hexdigest()
            parts.append(f"{prefix} {timestamp}_{digest}")
    headers = {
        "Cookie": "; ".join(f"{key}={value}" for key, value in cookies.items()),
        "X-Goog-AuthUser": os.environ.get("YTM_AUTH_USER", "0"),
        "X-Origin": _AUTH_ORIGIN,
        "Origin": _AUTH_ORIGIN,
    }
    if parts:
        headers["Authorization"] = " ".join(parts)
    return headers


def _client(name: str) -> InnerTube:
    with _clients_lock:
        if name not in _clients:
            client = InnerTube(name)
            cookies = _read_yt_cookies()
            if cookies:
                client.adaptor.session.headers.update(_auth_headers(cookies))
            _clients[name] = client
        return _clients[name]


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _runs_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    runs = value.get("runs")
    if isinstance(runs, list):
        return "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict))
    return ""


def parse_music_results(data: dict[str, Any], limit: int = 30) -> list[dict[str, str]]:
    """Extract song-like rows from WEB_REMIX/ANDROID_MUSIC search responses."""
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in _walk(data):
        renderer = node.get("musicResponsiveListItemRenderer")
        if not isinstance(renderer, dict):
            continue
        video_id = (renderer.get("playlistItemData") or {}).get("videoId")
        if not video_id:
            # Some InnerTube responses expose the ID on the row's navigation endpoint.
            for part in _walk(renderer):
                endpoint = part.get("watchEndpoint") or part.get("watchPlaylistEndpoint")
                if isinstance(endpoint, dict) and endpoint.get("videoId"):
                    video_id = endpoint["videoId"]
                    break
        if not isinstance(video_id, str) or not video_id or video_id in seen:
            continue

        columns = renderer.get("flexColumns") or []
        texts: list[str] = []
        for column in columns:
            inner = column.get("musicResponsiveListItemFlexColumnRenderer", {}) if isinstance(column, dict) else {}
            text = _runs_text(inner.get("text", {}))
            if text:
                texts.append(text)
        title = texts[0] if texts else "Без названия"
        subtitle = " · ".join(texts[1:])
        duration = ""
        for column in renderer.get("fixedColumns") or []:
            inner = column.get("musicResponsiveListItemFixedColumnRenderer", {}) if isinstance(column, dict) else {}
            duration = _runs_text(inner.get("text", {})) or duration

        thumbnails: list[dict[str, Any]] = []
        for part in _walk(renderer.get("thumbnail", {})):
            if isinstance(part.get("thumbnails"), list):
                thumbnails = part["thumbnails"]
        thumbnail = ""
        if thumbnails:
            thumb = thumbnails[-1]
            if isinstance(thumb, dict):
                thumbnail = str(thumb.get("url", ""))

        results.append({
            "video_id": video_id,
            "title": title,
            "subtitle": subtitle,
            "duration": duration,
            "thumbnail": thumbnail,
        })
        seen.add(video_id)
        if len(results) >= limit:
            break
    return results


def _authorize(request: Request) -> None:
    provided = request.headers.get("authorization", "")
    if not provided.startswith("Bearer ") or not secrets.compare_digest(provided[7:], WEB_TOKEN):
        raise HTTPException(status_code=401, detail="Неверный ключ веб-плеера")


def _station_ip() -> str:
    if not STATION_HOST:
        raise HTTPException(status_code=503, detail="Задайте YTM_STATION_HOST — IP колонки")
    try:
        address = ipaddress.ip_address(STATION_HOST)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="YTM_STATION_HOST должен быть IP-адресом колонки") from exc
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise HTTPException(status_code=503, detail="Для безопасности укажите частный LAN-IP колонки")
    return str(address)


def _ssh(command: str) -> str:
    """Execute one command using the user's saved SSH host key and empty root password."""
    host = _station_ip()
    client = SSHClient()
    # Trust only the host key that the user accepted earlier with `ssh -p 2222 ...`.
    client.load_system_host_keys()
    client.set_missing_host_key_policy(RejectPolicy())
    try:
        client.connect(
            hostname=host,
            port=STATION_PORT,
            username=STATION_USER,
            password="",
            allow_agent=False,
            look_for_keys=False,
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=15)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        status = stdout.channel.recv_exit_status()
        if status:
            raise RuntimeError(err.strip() or out.strip() or f"SSH remote command exited {status}")
        return out.strip()
    except (SSHException, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"SSH/колонка: {exc}") from exc
    finally:
        client.close()


def _play_url(video_id: str) -> tuple[str, str]:
    errors: list[str] = []
    for name in PLAYER_CLIENTS:
        try:
            data = _client(name).player(video_id)
            status = data.get("playabilityStatus", {})
            if status.get("status") not in (None, "OK"):
                errors.append(f"{name}: {status.get('reason') or status.get('status')}")
                continue
            streaming = data.get("streamingData", {})
            formats = list(streaming.get("adaptiveFormats", [])) + list(streaming.get("formats", []))
            audio = [f for f in formats if str(f.get("mimeType", "")).startswith("audio/") and f.get("url")]
            if not audio:
                errors.append(f"{name}: не найден прямой audio URL (возможен cipher/ограничение региона)")
                continue
            # Favor an audio/mp4 stream where available; it is usually the safest
            # GStreamer codec choice on the Station, then choose higher bitrate.
            audio.sort(key=lambda f: ("audio/mp4" in f.get("mimeType", ""), int(f.get("bitrate", 0))), reverse=True)
            return str(audio[0]["url"]), str(audio[0].get("mimeType", "audio/*"))
        except Exception as exc:  # upstream client failures vary as InnerTube evolves
            errors.append(f"{name}: {exc}")
    raise HTTPException(status_code=502, detail="Не удалось получить поток: " + "; ".join(errors[-3:]))


def _start_station_stream(url: str) -> None:
    # GStreamer parses its own quoted property value; the whole remote shell command
    # is separately quoted so URL query strings cannot become shell syntax.
    safe_url = url.replace("\\", "\\\\").replace('"', '\\"')
    pipeline = f'souphttpsrc location="{safe_url}" ! decodebin ! audioconvert ! audioresample ! alsasink'
    remote_script = f'''set -e
mkdir -p /data/opt
if [ -s {shlex.quote(PLAYER_PID)} ]; then
  old=$(cat {shlex.quote(PLAYER_PID)})
  case "$old" in *[!0-9]*|"") old="" ;; esac
  if [ -n "$old" ] && [ -r "/proc/$old/cmdline" ]; then
    oldcmd=$(tr '\\000' ' ' < "/proc/$old/cmdline")
    case "$oldcmd" in *" --gst-launch "*) kill "$old" 2>/dev/null || true ;; esac
  fi
  rm -f {shlex.quote(PLAYER_PID)}
fi
cd /system/vendor/quasar
export LD_LIBRARY_PATH=/system/vendor/quasar:/system/vendor/quasar/libs
nohup ./maind --gst-launch {shlex.quote(pipeline)} >{shlex.quote(PLAYER_LOG)} 2>&1 </dev/null &
pid=$!
echo "$pid" >{shlex.quote(PLAYER_PID)}
sleep 1
if kill -0 "$pid" 2>/dev/null; then echo started; else cat {shlex.quote(PLAYER_LOG)}; exit 1; fi
'''
    _ssh("sh -c " + shlex.quote(remote_script))


def _stop_station_stream() -> None:
    remote_script = f'''if [ -s {shlex.quote(PLAYER_PID)} ]; then
  p=$(cat {shlex.quote(PLAYER_PID)})
  case "$p" in *[!0-9]*|"") p="" ;; esac
  if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ]; then
    cmd=$(tr '\\000' ' ' < "/proc/$p/cmdline")
    case "$cmd" in *" --gst-launch "*) kill "$p" 2>/dev/null || true ;; esac
  fi
  rm -f {shlex.quote(PLAYER_PID)}
fi
echo stopped
'''
    _ssh("sh -c " + shlex.quote(remote_script))


@app.get("/")
def index(request: Request):
    # The access token is deliberately required in the URL; do not expose this LAN
    # control surface to the Internet or forward its port from the router.
    if not secrets.compare_digest(request.query_params.get("key", ""), WEB_TOKEN):
        raise HTTPException(status_code=403, detail="Откройте ссылку с ключом, показанную в консоли сервера")
    return FileResponse(
        APP_DIR / "static" / "index.html",
        headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"},
    )


@app.get("/api/status")
def status(request: Request):
    _authorize(request)
    try:
        cookies = _read_yt_cookies()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cookie_auth": bool(cookies), "account_index": os.environ.get("YTM_AUTH_USER", "0")}


@app.get("/api/search")
def search(request: Request, q: str):
    _authorize(request)
    query = q.strip()
    if not query or len(query) > 200:
        raise HTTPException(status_code=400, detail="Введите запрос (до 200 символов)")
    errors: list[str] = []
    for name in SEARCH_CLIENTS:
        try:
            results = parse_music_results(_client(name).search(query), limit=30)
            if results:
                return {"query": query, "results": results}
            errors.append(f"{name}: пустой результат")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise HTTPException(status_code=502, detail="Поиск InnerTube не удался: " + "; ".join(errors[-2:]))


@app.post("/api/play")
def play(payload: PlayRequest, request: Request):
    _authorize(request)
    url, _mime = _play_url(payload.video_id)
    _start_station_stream(url)
    return {"ok": True, "title": payload.title}


@app.post("/api/stop")
def stop(request: Request):
    _authorize(request)
    _stop_station_stream()
    return {"ok": True}


def _lan_ipv4() -> list[str]:
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


if __name__ == "__main__":
    print("YT Music → Station: сервер будет доступен только в вашей локальной сети.")
    print(f"Колонка: {STATION_HOST or '(задайте YTM_STATION_HOST)'}:{STATION_PORT}")
    for address in _lan_ipv4():
        print(f"Откройте на телефоне/ПК: http://{address}:8788/?key={quote(WEB_TOKEN)}")
    print("Не публикуйте этот порт в Интернет; для входа в колонку нужен root SSH с пустым паролем.")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("YTM_PORT", "8788")),
        log_level="info",
        access_log=False,
    )
