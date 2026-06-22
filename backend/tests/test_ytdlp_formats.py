"""Tests for ytdlp_service format handling (audio extraction vs video download)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.ytdlp_service import (
    AUDIO_FORMATS,
    VIDEO_FORMATS,
    _codec_args_for,
    _download_postprocessor_args,
    _format_selector,
    _postprocessors_for,
    _effective_ffmpeg_memory_limit_mb,
    _silence_trim_filter,
    is_video_format,
    retrim_audio_file,
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


class TestCodecArgsFor:
    def test_mp3_uses_libmp3lame(self):
        assert _codec_args_for("mp3") == ["-codec:a", "libmp3lame", "-q:a", "2"]

    def test_flac_is_lossless(self):
        assert _codec_args_for("flac") == ["-codec:a", "flac"]

    def test_aac_and_m4a_share_codec(self):
        assert _codec_args_for("aac") == _codec_args_for("m4a")

    def test_ogg_uses_libvorbis(self):
        assert _codec_args_for("ogg")[0:2] == ["-codec:a", "libvorbis"]


class TestDownloadPostprocessorArgs:
    def test_can_skip_trailing_trim_for_retry(self):
        args = _download_postprocessor_args(
            is_video=False,
            gain_percent=10.0,
            silence_trim_start_secs=2.0,
            silence_trim_end_secs=3.0,
            include_end_trim=False,
        )

        filter_str = args[args.index("-af") + 1]
        assert filter_str.startswith("volume=")
        assert "start_duration=2.0" in filter_str
        assert "start_duration=3.0" not in filter_str
        assert "areverse" not in filter_str


class TestRetrimAudioFile:
    def test_returns_none_when_no_trim_configured(self, tmp_path):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"fake audio")
        assert retrim_audio_file(str(f), "mp3", 0, 0) is None

    def test_returns_none_for_video_format(self, tmp_path):
        f = tmp_path / "song.mp4"
        f.write_bytes(b"fake video")
        assert retrim_audio_file(str(f), "mp4", 1.0, 1.0) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        missing = tmp_path / "missing.mp3"
        assert retrim_audio_file(str(missing), "mp3", 1.0, 1.0) is None

    def test_runs_ffmpeg_and_replaces_file_in_place(self, tmp_path):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"original audio bytes")

        def fake_run(cmd, check, capture_output, preexec_fn=None):
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"shorter retrimmed audio")
            return MagicMock()

        with patch("app.services.ytdlp_service.subprocess.run", side_effect=fake_run) as mock_run:
            new_size = retrim_audio_file(str(f), "mp3", 1.0, 1.0)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-af" in cmd
        assert f.read_bytes() == b"shorter retrimmed audio"
        assert new_size == len(b"shorter retrimmed audio")

    def test_raises_and_cleans_up_tmp_file_on_ffmpeg_failure(self, tmp_path):
        import subprocess
        f = tmp_path / "song.mp3"
        f.write_bytes(b"original audio bytes")

        def fake_run(cmd, check, capture_output, preexec_fn=None):
            Path(cmd[-1]).write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, cmd)

        with patch("app.services.ytdlp_service.subprocess.run", side_effect=fake_run) as mock_run:
            with pytest.raises(subprocess.CalledProcessError):
                retrim_audio_file(str(f), "mp3", 1.0, 1.0)

        assert f.read_bytes() == b"original audio bytes"
        assert not (tmp_path / "song.trim.mp3").exists()
        assert mock_run.call_count == 1


class TestDownloadTrackOptions:
    def _capture_opts(self, audio_format, gain_percent=0.0, silence_trim_start_secs=0.0,
                       silence_trim_end_secs=0.0, tmp_path=None):
        from app.services import ytdlp_service

        captured = {}

        def fake_ydl(opts):
            captured.update(opts)
            if opts.get("ffmpeg_location"):
                captured["wrapper_script"] = Path(opts["ffmpeg_location"]).read_text()
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


    def test_custom_ffmpeg_threads_applied(self, tmp_path):
        opts, _ = self._capture_opts("mp3", tmp_path=tmp_path)
        assert opts["postprocessor_args"][0:2] == ["-threads", "1"]

    def test_ffmpeg_memory_limit_is_divided_by_concurrent_processes(self):
        assert _effective_ffmpeg_memory_limit_mb(512, 3) == 170
        assert _effective_ffmpeg_memory_limit_mb(512, 1) == 512
        assert _effective_ffmpeg_memory_limit_mb(0, 3) == 0

    def test_ffmpeg_memory_limit_uses_wrapper_location(self, tmp_path):
        from app.services import ytdlp_service

        captured = {}

        def fake_ydl(opts):
            captured.update(opts)
            if opts.get("ffmpeg_location"):
                captured["wrapper_script"] = Path(opts["ffmpeg_location"]).read_text()
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            mock.extract_info = MagicMock(return_value={
                "id": "vid1", "title": "Title", "uploader": "Up", "duration": 10,
            })
            return mock

        with patch("app.services.ytdlp_service.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("app.services.ytdlp_service.yt_dlp.YoutubeDL", side_effect=fake_ydl):
                ytdlp_service.download_track(
                    youtube_id="vid1",
                    audio_format="mp3",
                    audio_quality="192",
                    gain_percent=0,
                    base_path=tmp_path,
                    ffmpeg_memory_limit_mb=512,
                    ffmpeg_concurrent_processes=2,
                )

        assert captured["ffmpeg_location"].endswith("ffmpeg")
        assert "ulimit -v 262144" in captured["wrapper_script"]

    def test_no_silence_trim_when_secs_zero(self, tmp_path):
        opts, _ = self._capture_opts("mp3", tmp_path=tmp_path)
        assert "-af" not in opts.get("postprocessor_args", [])

    def test_retries_without_trailing_trim_on_postprocessing_conversion_failure(self, tmp_path):
        from app.services import ytdlp_service

        captured_opts = []
        calls = {"count": 0}

        def fake_ydl(opts):
            captured_opts.append(dict(opts))
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)

            def extract_info(url, download):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise ytdlp_service.yt_dlp.utils.DownloadError(
                        "ERROR: Postprocessing: audio conversion failed: Conversion failed!"
                    )
                return {"id": "vid1", "title": "Title", "uploader": "Up", "duration": 10}

            mock.extract_info = MagicMock(side_effect=extract_info)
            return mock

        with patch("app.services.ytdlp_service.yt_dlp.YoutubeDL", side_effect=fake_ydl):
            meta = ytdlp_service.download_track(
                youtube_id="vid1",
                audio_format="mp3",
                audio_quality="192",
                gain_percent=0,
                silence_trim_start_secs=2.0,
                silence_trim_end_secs=3.0,
                base_path=tmp_path,
            )

        assert meta["file_format"] == "mp3"
        assert calls["count"] == 2
        first_filter = captured_opts[0]["postprocessor_args"][captured_opts[0]["postprocessor_args"].index("-af") + 1]
        retry_filter = captured_opts[1]["postprocessor_args"][captured_opts[1]["postprocessor_args"].index("-af") + 1]
        assert "areverse" in first_filter
        assert "areverse" not in retry_filter
        assert "start_duration=2.0" in retry_filter
        assert "start_duration=3.0" not in retry_filter
