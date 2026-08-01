from __future__ import annotations

import unittest

from lavatune.media import MediaInfo, parse_playerctl


class MediaTests(unittest.TestCase):
    def test_playing_youtube_wins_over_paused_player(self) -> None:
        output = (
            "spotify\tPaused\tOlder song\tSome artist\thttps://open.spotify.com/track/1\n"
            "chromium.instance1\tPlaying\tA useful video\tExample Channel\thttps://youtube.com/watch?v=1\n"
        )

        info = parse_playerctl(output)

        self.assertEqual(info.source, "YouTube")
        self.assertEqual(info.title, "A useful video")
        self.assertEqual(info.artist, "Example Channel")
        self.assertEqual(info.display(), "YouTube | A useful video - Example Channel")

    def test_spotify_metadata_uses_track_and_artist(self) -> None:
        info = parse_playerctl(
            "spotify\tPlaying\tNight Drive\tThe Signals\thttps://open.spotify.com/track/2\n"
        )

        self.assertEqual(info.display(), "Spotify | Night Drive - The Signals")

    def test_paused_state_is_visible(self) -> None:
        info = MediaInfo(title="A video", source="YouTube", status="Paused")

        self.assertEqual(info.display(), "YouTube [paused] | A video")

    def test_metadata_strips_terminal_and_bidi_controls(self) -> None:
        info = parse_playerctl(
            "chromium\tPlaying\tSafe\x1b]0;spoofed\x07 title\u202eevil\tArtist\u200bName\t"
            "https://youtube.com/watch?v=1\n"
        )

        self.assertEqual(info.title, "Safe ]0;spoofed title evil")
        self.assertEqual(info.artist, "Artist Name")
        self.assertNotIn("\x1b", info.display())

    def test_metadata_fields_are_bounded(self) -> None:
        info = parse_playerctl(f"spotify\tPlaying\t{'x' * 500}\tartist\turl\n")

        self.assertEqual(len(info.title), 240)


if __name__ == "__main__":
    unittest.main()
