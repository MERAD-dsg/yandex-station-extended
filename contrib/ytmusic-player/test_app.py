import os
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import app


class ParseMusicResultsTests(unittest.TestCase):
    def test_extracts_track_metadata(self):
        response = {
            "contents": {
                "musicResponsiveListItemRenderer": {
                    "playlistItemData": {"videoId": "aBcDeFgH123"},
                    "flexColumns": [
                        {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "Песня"}]}}},
                        {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "Исполнитель"}]}}},
                    ],
                    "fixedColumns": [
                        {"musicResponsiveListItemFixedColumnRenderer": {"text": {"simpleText": "3:21"}}}
                    ],
                    "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": [{"url": "https://img.test/cover"}]}}},
                }
            }
        }
        self.assertEqual(
            app.parse_music_results(response),
            [{
                "video_id": "aBcDeFgH123",
                "title": "Песня",
                "subtitle": "Исполнитель",
                "duration": "3:21",
                "thumbnail": "https://img.test/cover",
            }],
        )

    def test_deduplicates_rows(self):
        row = {
            "musicResponsiveListItemRenderer": {
                "playlistItemData": {"videoId": "aBcDeFgH123"},
                "flexColumns": [],
            }
        }
        results = app.parse_music_results({"contents": [row, row]})
        self.assertEqual(len(results), 1)


class CookieAuthTests(unittest.TestCase):
    def test_reads_only_youtube_google_cookies_and_signs_request(self):
        tab = "\t"
        newline = "\n"
        content = (
            f".youtube.com{tab}TRUE{tab}/{tab}TRUE{tab}0{tab}SAPISID{tab}secret-cookie{newline}"
            f".google.com{tab}TRUE{tab}/{tab}TRUE{tab}0{tab}__Secure-3PAPISID{tab}secure-cookie{newline}"
            f".notyoutube.com{tab}TRUE{tab}/{tab}TRUE{tab}0{tab}SAPISID{tab}should-not-load{newline}"
        )
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as file:
            file.write(content)
            path = file.name
        try:
            with patch.dict(os.environ, {"YTM_COOKIE_FILE": path}):
                cookies = app._read_yt_cookies()
            self.assertEqual(cookies["SAPISID"], "secret-cookie")
            self.assertNotIn("should-not-load", cookies.values())
            headers = app._auth_headers(cookies)
            self.assertIn("SAPISIDHASH ", headers["Authorization"])
            self.assertIn("SAPISID3PHASH ", headers["Authorization"])
            self.assertEqual(headers["X-Origin"], "https://music.youtube.com")
        finally:
            os.unlink(path)


class RemoteCommandTests(unittest.TestCase):
    def test_player_shell_script_is_quoted_and_valid(self):
        captured = []
        with patch.object(app, "_ssh", side_effect=captured.append):
            app._start_station_stream("https://example.test/audio?x=1&y=2")
        command = shlex.split(captured[0])
        self.assertEqual(command[:2], ["sh", "-c"])
        proc = subprocess.run(["sh", "-n"], input=command[2], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("souphttpsrc", command[2])
        self.assertIn("https://example.test/audio?x=1&y=2", command[2])

    def test_stop_script_is_valid(self):
        captured = []
        with patch.object(app, "_ssh", side_effect=captured.append):
            app._stop_station_stream()
        command = shlex.split(captured[0])
        proc = subprocess.run(["sh", "-n"], input=command[2], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
