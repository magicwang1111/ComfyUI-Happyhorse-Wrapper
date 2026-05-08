import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMFY_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(COMFY_ROOT))

from py.nodes import (  # noqa: E402
    _build_oss_object_name,
    _normalize_oss_endpoint,
    _parse_env_line,
    _parse_oss_uri,
    _tensor_to_pil_images,
    build_image_to_video_payload,
    build_reference_to_video_payload,
    build_text_to_video_payload,
    build_video_edit_payload,
)


def test_text_to_video_payload():
    payload = build_text_to_video_payload("hello", "720P", "16:9", "5", False, 123)
    assert payload["model"] == "happyhorse-1.0-t2v"
    assert payload["input"]["prompt"] == "hello"
    assert payload["parameters"] == {
        "resolution": "720P",
        "watermark": False,
        "duration": 5,
        "ratio": "16:9",
        "seed": 123,
    }


def test_image_to_video_payload_has_first_frame_only():
    payload = build_image_to_video_payload("", "https://example.com/a.png", "1080P", "3", True, -1)
    assert payload["model"] == "happyhorse-1.0-i2v"
    assert payload["input"]["media"] == [{"type": "first_frame", "url": "https://example.com/a.png"}]
    assert "ratio" not in payload["parameters"]
    assert "seed" not in payload["parameters"]


def test_reference_to_video_payload_order():
    payload = build_reference_to_video_payload(
        "character1 waves to character2",
        ["https://example.com/1.png", "https://example.com/2.png"],
        "720P",
        "9:16",
        6,
        True,
        -1,
    )
    assert payload["model"] == "happyhorse-1.0-r2v"
    assert [item["type"] for item in payload["input"]["media"]] == ["reference_image", "reference_image"]
    assert payload["input"]["media"][1]["url"].endswith("2.png")


def test_video_edit_payload():
    payload = build_video_edit_payload(
        "change clothes",
        "https://example.com/input.mp4",
        ["https://example.com/ref.webp"],
        "1080P",
        False,
        "origin",
        0,
    )
    assert payload["model"] == "happyhorse-1.0-video-edit"
    assert payload["input"]["media"][0] == {"type": "video", "url": "https://example.com/input.mp4"}
    assert payload["input"]["media"][1]["type"] == "reference_image"
    assert payload["parameters"]["audio_setting"] == "origin"


def test_numpy_image_batch_to_pil():
    import numpy as np

    images = _tensor_to_pil_images(np.zeros((1, 4, 4, 3), dtype=np.float32))
    assert len(images) == 1
    assert images[0].size == (4, 4)


def test_oss_uri_parsing_and_endpoint_normalization():
    assert _parse_oss_uri("oss://goumee-coze/Happyhorse/") == ("goumee-coze", "Happyhorse/")
    assert _normalize_oss_endpoint("oss-cn-hangzhou.aliyuncs.com") == "https://oss-cn-hangzhou.aliyuncs.com"


def test_oss_object_name_keeps_prefix_and_filename():
    object_name = _build_oss_object_name("Happyhorse", "first frame.png")
    assert object_name.startswith("Happyhorse/")
    assert object_name.endswith("_first%20frame.png")


def test_env_line_parser_accepts_exports_and_quotes():
    assert _parse_env_line('export OSS_BUCKET="goumee-coze"') == ("OSS_BUCKET", "goumee-coze")
    assert _parse_env_line("# comment") is None
