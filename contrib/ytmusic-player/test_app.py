import shlex
import subprocess
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
