"""Tests for ytdlp_service format handling (audio extraction vs video download)."""
from unittest.mock import MagicMock, patch

from app.services.ytdlp_service import (
    AUDIO_FORMATS,
    VIDEO_FORMATS,
    _format_selector,
    _postprocessors_for,
    _silence_trim_filter,
    is_video_format,
)


class TestFormatClassification:
    def test_video_formats(self):
        assert is_video_format("mp4")
        assert is_video_format("webm")

    def test_audio_formats(self):
        for fmt in AUDIO_FORMATS:
            assert not is_video_format(fmt)


class TestPostprocessors:
    def test_video_uses_remuxer(self):
        pps = _postprocessors_for("mp4", "192")
        assert pps == [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]

    def test_m4a_extracts_audio(self):
        pps = _postprocessors_for("m4a", "192")
        assert pps == [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]

    def test_mp3_keeps_quality(self):
        pps = _postprocessors_for("mp3", "320")
        assert pps[0]["preferredcodec"] == "mp3"
        assert pps[0]["preferredquality"] == "320"


class TestFormatSelector:
    def test_audio_selects_bestaudio(self):
        assert _format_selector("mp3") == "bestaudio/best"

    def test_video_prefers_matching_container(self):
        sel = _format_selector("mp4")
        assert sel.startswith("bestvideo[ext=mp4]+bestaudio")
        assert "bestvideo+bestaudio" in sel


class TestSilenceTrimFilter:
    def test_no_trim_returns_none(self):
        assert _silence_trim_filter(0, 0) is None

    def test_start_only(self):
        f = _silence_trim_filter(2.5, 0)
        assert f == "silenceremove=start_periods=1:start_duration=2.5:start_threshold=-50dB:detection=peak"

    def test_end_only_uses_reverse_trick(self):
        f = _silence_trim_filter(0, 2.5)
        assert f.startswith("areverse,silenceremove=")
        assert f.endswith(",areverse")

    def test_both_sides(self):
        f = _silence_trim_filter(2.0, 3.0)
        parts = f.split(",")
        assert parts[0].startswith("silenceremove=start_periods=1:start_duration=2.0")
        assert parts[1] == "areverse"
        assert parts[2].startswith("silenceremove=start_periods=1:start_duration=3.0")
        assert parts[3] == "areverse"


class TestDownloadTrackOptions:
    def _capture_opts(self, audio_format, gain_percent=0.0, silence_trim_start_secs=0.0,
                       silence_trim_end_secs=0.0, tmp_path=None):
        from app.services import ytdlp_service

        captured = {}

        def fake_ydl(opts):
            captured.update(opts)
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            mock.extract_info = MagicMock(return_value={
                "id": "vid1", "title": "Title", "uploader": "Up", "duration": 10,
            })
            return mock

        with patch("app.services.ytdlp_service.yt_dlp.YoutubeDL", side_effect=fake_ydl):
            meta = ytdlp_service.download_track(
                youtube_id="vid1",
                audio_format=audio_format,
                audio_quality="192",
                gain_percent=gain_percent,
                silence_trim_start_secs=silence_trim_start_secs,
                silence_trim_end_secs=silence_trim_end_secs,
                base_path=tmp_path,
            )
        return captured, meta

    def test_mp4_sets_merge_output_format(self, tmp_path):
        opts, meta = self._capture_opts("mp4", tmp_path=tmp_path)
        assert opts["merge_output_format"] == "mp4"
        assert opts["format"].startswith("bestvideo[ext=mp4]")
        assert meta["file_format"] == "mp4"
        assert meta["file_path"].endswith(".mp4")

    def test_audio_has_no_merge_output_format(self, tmp_path):
        opts, meta = self._capture_opts("mp3", tmp_path=tmp_path)
        assert "merge_output_format" not in opts
        assert opts["format"] == "bestaudio/best"
        assert meta["file_format"] == "mp3"

    def test_gain_skipped_for_video(self, tmp_path):
        opts, _ = self._capture_opts("mp4", gain_percent=10.0, tmp_path=tmp_path)
        assert "-af" not in opts.get("postprocessor_args", [])

    def test_gain_applied_for_audio(self, tmp_path):
        opts, _ = self._capture_opts("mp3", gain_percent=10.0, tmp_path=tmp_path)
        assert "-af" in opts["postprocessor_args"]

    def test_m4a_file_extension(self, tmp_path):
        _, meta = self._capture_opts("m4a", tmp_path=tmp_path)
        assert meta["file_format"] == "m4a"
        assert meta["file_path"].endswith(".m4a")

    def test_silence_trim_skipped_for_video(self, tmp_path):
        opts, _ = self._capture_opts(
            "mp4", silence_trim_start_secs=2.5, silence_trim_end_secs=2.5, tmp_path=tmp_path
        )
        assert "-af" not in opts.get("postprocessor_args", [])

    def test_silence_trim_applied_for_audio(self, tmp_path):
        opts, _ = self._capture_opts(
            "mp3", silence_trim_start_secs=2.5, silence_trim_end_secs=2.5, tmp_path=tmp_path
        )
        af_args = opts["postprocessor_args"]
        assert "-af" in af_args
        filter_str = af_args[af_args.index("-af") + 1]
        assert "silenceremove" in filter_str

    def test_gain_and_silence_trim_combined(self, tmp_path):
        opts, _ = self._capture_opts(
            "mp3", gain_percent=10.0, silence_trim_start_secs=2.5,
            silence_trim_end_secs=2.5, tmp_path=tmp_path,
        )
        af_args = opts["postprocessor_args"]
        filter_str = af_args[af_args.index("-af") + 1]
        assert filter_str.startswith("volume=")
        assert "silenceremove" in filter_str

    def test_no_silence_trim_when_secs_zero(self, tmp_path):
        opts, _ = self._capture_opts("mp3", tmp_path=tmp_path)
        assert "-af" not in opts.get("postprocessor_args", [])
