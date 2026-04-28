from py.api.client import _join_endpoint, _to_openai_video_payload


def test_dashscope_endpoint_join():
    assert _join_endpoint("https://dashscope.aliyuncs.com", "/api/v1/tasks/abc") == (
        "https://dashscope.aliyuncs.com/api/v1/tasks/abc"
    )


def test_api_v1_endpoint_join():
    assert _join_endpoint("https://aihubmix.com/v1", "/api/v1/tasks/abc") == (
        "https://aihubmix.com/v1/tasks/abc"
    )


def test_openai_video_payload_mapping():
    payload = _to_openai_video_payload(
        {
            "model": "happyhorse-1.0-t2v",
            "input": {"prompt": "hello"},
            "parameters": {"resolution": "720P", "ratio": "16:9", "duration": 3, "seed": 7},
        }
    )
    assert payload == {
        "model": "happyhorse-1.0-t2v",
        "prompt": "hello",
        "seconds": "3s",
        "size": "1280x720",
        "seed": 7,
    }
