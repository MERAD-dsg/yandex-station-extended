import importlib.util
import struct
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "idle-rainbow.py"
SPEC = importlib.util.spec_from_file_location("idle_rainbow", SCRIPT)
assert SPEC and SPEC.loader
idle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(idle)

AUDIO_SCRIPT = Path(__file__).resolve().parents[1] / "audio-player.py"
AUDIO_SPEC = importlib.util.spec_from_file_location("audio_player", AUDIO_SCRIPT)
assert AUDIO_SPEC and AUDIO_SPEC.loader
audio = importlib.util.module_from_spec(AUDIO_SPEC)
AUDIO_SPEC.loader.exec_module(audio)


def varint(value):
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def number_field(number, value):
    return varint(number << 3) + varint(value)


def bytes_field(number, value):
    return varint((number << 3) | 2) + varint(len(value)) + value


def alice_message(state):
    nested = number_field(1, state)
    message = bytes_field(252, nested) + number_field(253, 3)
    return struct.pack("<I", len(message)) + message


class IdleRainbowTests(unittest.TestCase):
    def test_alice_state_mapping_fails_closed(self):
        for state in (0, 6):
            self.assertEqual(idle.alice_activity(alice_message(state)[4:]), "idle")
        for state in (1, 2, 3, 5):
            self.assertEqual(idle.alice_activity(alice_message(state)[4:]), "busy")
        self.assertEqual(idle.alice_activity(alice_message(99)[4:]), "unknown")
        self.assertIsNone(idle.alice_activity(b""))
        self.assertEqual(idle.alice_activity(number_field(253, 3)), "unknown")

    def test_frame_decoder_handles_fragmented_and_joined_messages(self):
        decoder = idle.FrameDecoder()
        first = alice_message(1)
        second = alice_message(0)
        self.assertEqual(decoder.feed(first[:3]), [])
        self.assertEqual(decoder.feed(first[3:] + second), ["busy", "idle"])

    def test_rainbow_frame_has_six_rgb_triplets_with_bounded_values(self):
        frame = idle.rainbow_frame(43)
        self.assertEqual(len(frame), 18)
        self.assertTrue(all(isinstance(value, int) and 0 <= value <= 255 for value in frame))
        self.assertNotEqual(frame, [0] * 18)

    def test_dark_requires_every_channel_to_be_readable_and_zero(self):
        self.assertTrue(idle.is_dark([0] * 18))
        self.assertFalse(idle.is_dark([0] * 17 + [1]))
        self.assertFalse(idle.is_dark(None))

    def test_audio_upload_requires_allowed_extension_and_matching_signature(self):
        self.assertEqual(audio.detect_format("track.mp3", b"ID3" + b"x" * 20), ".mp3")
        self.assertEqual(audio.detect_format("track.wav", b"RIFF" + b"x" * 4 + b"WAVE"), ".wav")
        with self.assertRaises(ValueError):
            audio.detect_format("payload.bin", b"ID3" + b"x" * 20)
        with self.assertRaises(ValueError):
            audio.detect_format("wrong.wav", b"ID3" + b"x" * 20)

    def test_uploaded_display_name_is_reduced_to_a_safe_basename(self):
        self.assertEqual(audio.safe_display_name(r"C:\\fakepath\\my song &.mp3", ".mp3"), "my song _.mp3")


if __name__ == "__main__":
    unittest.main()
