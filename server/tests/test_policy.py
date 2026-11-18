from busvideo_server.config import MediaPolicy
from busvideo_server.services.media_policy import VideoMetadata, check_extension, evaluate
from busvideo_server.services.validation import parse_ffprobe


def _ok():
    return VideoMetadata(container="mov,mp4,m4a,3gp,3g2,mj2", duration_s=60, width=1920, height=1080,
                         video_codec="h264", audio_codec="aac", fps=30, bitrate_kbps=6000, h264_level=40,
                         size_bytes=50_000_000)


def test_compatible():
    r = evaluate(_ok(), MediaPolicy())
    assert r.compatible and r.reasons == []


def test_resolution_and_fps_and_codec():
    m = _ok(); m.width, m.height, m.fps, m.video_codec = 3840, 2160, 60, "hevc"
    r = evaluate(m, MediaPolicy())
    assert not r.compatible
    assert any("Resolução" in x for x in r.reasons)
    assert any("FPS" in x for x in r.reasons)
    assert any("Codec de vídeo" in x for x in r.reasons)


def test_level_bitrate_duration_size():
    m = _ok(); m.h264_level, m.bitrate_kbps, m.duration_s, m.size_bytes = 51, 20000, 7200, 3 * 1024 ** 3
    r = evaluate(m, MediaPolicy())
    assert len(r.reasons) == 4


def test_audio_none_allowed_and_mp3_rejected():
    m = _ok(); m.audio_codec = "none"
    assert evaluate(m, MediaPolicy()).compatible
    m.audio_codec = "mp3"
    assert not evaluate(m, MediaPolicy()).compatible


def test_extension():
    assert check_extension("video.mp4", MediaPolicy()) is None
    assert check_extension("video.avi", MediaPolicy()) is not None
    assert check_extension("noext", MediaPolicy()) is not None


def test_parse_ffprobe():
    data = {"format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.5", "bit_rate": "4000000"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720,
                         "avg_frame_rate": "30000/1001", "level": 31, "profile": "High"},
                        {"codec_type": "audio", "codec_name": "aac"}]}
    m = parse_ffprobe(data, size_bytes=123)
    assert m.width == 1280 and m.fps == 29.97 and m.h264_level == 31 and m.audio_codec == "aac"
    assert m.bitrate_kbps == 4000 and m.size_bytes == 123
