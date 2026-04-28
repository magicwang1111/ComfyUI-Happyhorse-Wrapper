import time
from urllib.parse import urljoin

import requests


CREATE_TASK_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"
QUERY_TASK_PATH_TEMPLATE = "/api/v1/tasks/{task_id}"
OPENAI_VIDEOS_PATH = "/videos"


class HappyHorseAPIError(RuntimeError):
    def __init__(self, message, code=None, request_id=None, status_code=None):
        parts = [message]
        if code:
            parts.append(f"code={code}")
        if request_id:
            parts.append(f"request_id={request_id}")
        if status_code:
            parts.append(f"http_status={status_code}")
        super().__init__(" | ".join(parts))
        self.code = code
        self.request_id = request_id
        self.status_code = status_code


def _join_endpoint(endpoint, path):
    normalized = str(endpoint or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("endpoint is required.")
    if normalized.endswith("/api/v1") and path.startswith("/api/v1/"):
        path = path[len("/api/v1"):]
    elif normalized.endswith("/v1") and path.startswith("/api/v1/"):
        path = path[len("/api/v1"):]
    return urljoin(normalized + "/", path.lstrip("/"))


class DashScopeClient:
    def __init__(self, api_key, endpoint, timeout=60, poll_interval=15, session=None):
        api_key = str(api_key or "").strip()
        if not api_key:
            raise ValueError(
                "api_key is required. Add api_key to config.local.json or set DASHSCOPE_API_KEY/AIHUBMIX_API_KEY."
            )
        self.api_key = api_key
        self.endpoint = str(endpoint or "").strip().rstrip("/")
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self.session = session or requests.Session()

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

    def close(self):
        self.session.close()

    @property
    def _uses_openai_video_api(self):
        return self.endpoint.rstrip("/").endswith("/v1")

    def _request_json(self, method, path, **kwargs):
        url = _join_endpoint(self.endpoint, path)
        headers = dict(self._headers)
        if method.upper() == "GET":
            headers.pop("X-DashScope-Async", None)

        try:
            response = self.session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ConnectionError(f"HappyHorse API request failed for {method} {url}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HappyHorseAPIError(
                f"HappyHorse API returned non-JSON response for {method} {url}",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400 or payload.get("code"):
            raise HappyHorseAPIError(
                payload.get("message") or f"HappyHorse API request failed for {method} {url}",
                code=payload.get("code"),
                request_id=payload.get("request_id"),
                status_code=response.status_code,
            )
        return payload

    def create_video_task(self, payload):
        if self._uses_openai_video_api:
            response = self._create_openai_video_task(payload)
            video_id = response.get("id")
            if not video_id:
                raise HappyHorseAPIError("AIHubMix video response did not include id.")
            return {"task_id": video_id, "task_status": response.get("status") or "queued"}

        response = self._request_json("POST", CREATE_TASK_PATH, json=payload)
        output = response.get("output") or {}
        task_id = output.get("task_id")
        if not task_id:
            raise HappyHorseAPIError(
                "HappyHorse create task response did not include output.task_id.",
                request_id=response.get("request_id"),
            )
        return output

    def retrieve_task(self, task_id):
        if not str(task_id or "").strip():
            raise ValueError("task_id is required.")
        if self._uses_openai_video_api:
            response = self._request_json("GET", f"{OPENAI_VIDEOS_PATH}/{task_id}")
            status = str(response.get("status") or "").lower()
            mapped_status = {
                "queued": "PENDING",
                "in_progress": "RUNNING",
                "processing": "RUNNING",
                "completed": "SUCCEEDED",
                "failed": "FAILED",
                "cancelled": "CANCELED",
                "canceled": "CANCELED",
            }.get(status, status.upper())
            output = {
                "task_id": response.get("id") or task_id,
                "task_status": mapped_status,
            }
            if mapped_status == "SUCCEEDED":
                output["video_url"] = _join_endpoint(self.endpoint, f"{OPENAI_VIDEOS_PATH}/{task_id}/content")
            if mapped_status == "FAILED":
                error = response.get("error") or {}
                if isinstance(error, dict):
                    output["code"] = error.get("code") or error.get("type")
                    output["message"] = error.get("message")
            return {"request_id": response.get("request_id"), "output": output}

        return self._request_json("GET", QUERY_TASK_PATH_TEMPLATE.format(task_id=task_id))

    def wait_for_video(self, task_id):
        active_statuses = {"PENDING", "RUNNING"}
        failure_statuses = {"FAILED", "CANCELED", "UNKNOWN"}

        while True:
            response = self.retrieve_task(task_id)
            output = response.get("output") or {}
            status = str(output.get("task_status") or "").upper()

            if status == "SUCCEEDED":
                video_url = str(output.get("video_url") or "").strip()
                if not video_url:
                    raise HappyHorseAPIError(
                        "HappyHorse task succeeded but did not include output.video_url.",
                        request_id=response.get("request_id"),
                    )
                return response

            if status in failure_statuses:
                raise HappyHorseAPIError(
                    output.get("message") or f"HappyHorse task ended with status {status}.",
                    code=output.get("code") or status,
                    request_id=response.get("request_id"),
                )

            if status not in active_statuses:
                raise HappyHorseAPIError(
                    f"HappyHorse task returned unexpected status {status!r}.",
                    request_id=response.get("request_id"),
                )

            print(f"[ComfyUI-Happyhorse-Wrapper] task {task_id}: {status}")
            time.sleep(self.poll_interval)

    def _create_openai_video_task(self, payload):
        openai_payload = _to_openai_video_payload(payload)
        media = (payload.get("input") or {}).get("media") or []
        first_frame = next((item for item in media if item.get("type") == "first_frame"), None)
        if first_frame:
            file_url = str(first_frame.get("url") or "").strip()
            if not file_url:
                raise ValueError("first_frame media URL is required.")
            image_response = self.session.get(file_url, timeout=self.timeout)
            image_response.raise_for_status()

            data = {key: str(value) for key, value in openai_payload.items() if key != "media" and value is not None}
            files = {
                "input_reference": (
                    "first_frame.png",
                    image_response.content,
                    image_response.headers.get("Content-Type") or "image/png",
                )
            }
            return self._request_form("POST", OPENAI_VIDEOS_PATH, data=data, files=files)

        return self._request_json("POST", OPENAI_VIDEOS_PATH, json=openai_payload)

    def _request_form(self, method, path, **kwargs):
        url = _join_endpoint(self.endpoint, path)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = self.session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ConnectionError(f"HappyHorse API request failed for {method} {url}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HappyHorseAPIError(
                f"HappyHorse API returned non-JSON response for {method} {url}",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400 or payload.get("code"):
            raise HappyHorseAPIError(
                payload.get("message") or f"HappyHorse API request failed for {method} {url}",
                code=payload.get("code"),
                request_id=payload.get("request_id"),
                status_code=response.status_code,
            )
        return payload


def _duration_to_seconds(duration):
    if duration is None:
        return None
    text = str(duration).strip()
    return text if text.endswith("s") else f"{text}s"


def _dashscope_resolution_to_openai_size(parameters):
    resolution = str(parameters.get("resolution") or "").upper()
    ratio = str(parameters.get("ratio") or "16:9")
    size_by_resolution = {
        ("720P", "16:9"): "1280x720",
        ("720P", "9:16"): "720x1280",
        ("720P", "1:1"): "960x960",
        ("720P", "4:3"): "960x720",
        ("720P", "3:4"): "720x960",
        ("1080P", "16:9"): "1920x1080",
        ("1080P", "9:16"): "1080x1920",
        ("1080P", "1:1"): "1440x1440",
        ("1080P", "4:3"): "1440x1080",
        ("1080P", "3:4"): "1080x1440",
    }
    return size_by_resolution.get((resolution, ratio)) or resolution or None


def _to_openai_video_payload(payload):
    input_data = payload.get("input") or {}
    parameters = payload.get("parameters") or {}
    result = {
        "model": payload.get("model"),
        "prompt": input_data.get("prompt") or "",
    }
    seconds = _duration_to_seconds(parameters.get("duration"))
    if seconds:
        result["seconds"] = seconds
    size = _dashscope_resolution_to_openai_size(parameters)
    if size:
        result["size"] = size
    seed = parameters.get("seed")
    if seed is not None:
        result["seed"] = seed
    media = input_data.get("media") or []
    if media:
        # AiHubMix's OpenAI-compatible video endpoint uses provider-specific
        # support for non-text generation. Keep the DashScope media payload
        # available without losing the simple /v1/videos shape.
        result["media"] = media
    return result
