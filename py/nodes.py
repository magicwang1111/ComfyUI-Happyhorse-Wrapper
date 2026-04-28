import configparser
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse

import numpy
from PIL import Image
import requests

try:
    import folder_paths
except ImportError:
    comfy_root = Path(__file__).resolve().parents[3]
    if str(comfy_root) not in sys.path:
        sys.path.insert(0, str(comfy_root))
    import folder_paths

from .api import DashScopeClient


NODE_PREFIX = "ComfyUI-Happyhorse-Wrapper"
NODE_CATEGORY = NODE_PREFIX

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_JSON_PATH = ROOT_DIR / "config.local.json"
LEGACY_CONFIG_PATH = ROOT_DIR / "config.ini"
LEGACY_CONFIG_SECTION = "API"

DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com"
DEFAULT_POLL_INTERVAL = 15.0
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_UPLOAD_TIMEOUT = 120
DEFAULT_FILENAME_PREFIX = NODE_PREFIX

TMPFILES_UPLOAD_API_URL = "https://tmpfiles.org/api/v1/upload"
TMPFILES_MAX_SIZE_BYTES = 100 * 1024 * 1024
TMPFILES_UPLOAD_RETRY_COUNT = 3
TMPFILES_UPLOAD_RETRY_DELAY = 1.0

RESOLUTIONS = ["720P", "1080P"]
RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4"]
DURATIONS = [str(value) for value in range(3, 16)]
AUDIO_SETTINGS = ["auto", "origin"]
SEED_MAX = 2147483647


def _load_json_config():
    if not CONFIG_JSON_PATH.exists():
        return {}
    try:
        with CONFIG_JSON_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{CONFIG_JSON_PATH.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_JSON_PATH.name} must contain a JSON object.")
    return data


def _present(data, key):
    value = data.get(key)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _env_value(*keys):
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _legacy_value(*keys):
    if not LEGACY_CONFIG_PATH.exists():
        return ""
    config = configparser.ConfigParser()
    config.read(LEGACY_CONFIG_PATH, encoding="utf-8")
    for key in keys:
        value = config.get(LEGACY_CONFIG_SECTION, key, fallback="").strip()
        if value:
            return value
    return ""


def _number(value, default, minimum=None, name="value"):
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be greater than or equal to {minimum}.")
    return parsed


def _resolve_config():
    data = _load_json_config()
    api_key = (
        str(data["api_key"]).strip()
        if _present(data, "api_key")
        else _env_value("DASHSCOPE_API_KEY", "AIHUBMIX_API_KEY")
        or _legacy_value("DASHSCOPE_API_KEY", "AIHUBMIX_API_KEY")
    )
    endpoint = (
        str(data["endpoint"]).strip()
        if _present(data, "endpoint")
        else _env_value("DASHSCOPE_ENDPOINT", "AIHUBMIX_ENDPOINT", "AIHUBMIX_BASE_URL")
        or _legacy_value("DASHSCOPE_ENDPOINT", "AIHUBMIX_ENDPOINT", "AIHUBMIX_BASE_URL")
        or DEFAULT_ENDPOINT
    )
    poll_interval = _number(data.get("poll_interval"), DEFAULT_POLL_INTERVAL, 1, "poll_interval")
    request_timeout = _number(data.get("request_timeout"), DEFAULT_REQUEST_TIMEOUT, 5, "request_timeout")
    upload_timeout = _number(data.get("upload_timeout"), DEFAULT_UPLOAD_TIMEOUT, 5, "upload_timeout")
    return {
        "api_key": api_key,
        "endpoint": endpoint,
        "poll_interval": poll_interval,
        "request_timeout": request_timeout,
        "upload_timeout": upload_timeout,
    }


@contextmanager
def _runtime_client():
    config = _resolve_config()
    client = DashScopeClient(
        config["api_key"],
        config["endpoint"],
        timeout=config["request_timeout"],
        poll_interval=config["poll_interval"],
    )
    try:
        yield client
    finally:
        client.close()


def _clean_prompt(prompt, required=True):
    value = str(prompt or "").strip()
    if required and not value:
        raise ValueError("prompt is required.")
    return value


def _normalize_duration(duration):
    try:
        parsed = int(duration)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be an integer between 3 and 15.") from exc
    if parsed < 3 or parsed > 15:
        raise ValueError("duration must be an integer between 3 and 15.")
    return parsed


def _normalize_seed(seed):
    try:
        parsed = int(seed)
    except (TypeError, ValueError) as exc:
        raise ValueError("seed must be an integer.") from exc
    if parsed < -1 or parsed > SEED_MAX:
        raise ValueError(f"seed must be -1 or an integer between 0 and {SEED_MAX}.")
    return None if parsed < 0 else parsed


def _build_parameters(resolution="1080P", duration=None, ratio=None, watermark=True, seed=-1, audio_setting=None):
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of: {', '.join(RESOLUTIONS)}.")
    parameters = {"resolution": resolution, "watermark": bool(watermark)}
    if duration is not None:
        parameters["duration"] = _normalize_duration(duration)
    if ratio is not None:
        if ratio not in RATIOS:
            raise ValueError(f"ratio must be one of: {', '.join(RATIOS)}.")
        parameters["ratio"] = ratio
    if audio_setting is not None:
        if audio_setting not in AUDIO_SETTINGS:
            raise ValueError(f"audio_setting must be one of: {', '.join(AUDIO_SETTINGS)}.")
        parameters["audio_setting"] = audio_setting
    normalized_seed = _normalize_seed(seed)
    if normalized_seed is not None:
        parameters["seed"] = normalized_seed
    return parameters


def _submit_and_wait(payload):
    with _runtime_client() as client:
        task = client.create_video_task(payload)
        task_id = task["task_id"]
        print(f"[{NODE_PREFIX}] created task: {task_id}")
        result = client.wait_for_video(task_id)
    output = result.get("output") or {}
    video_url = str(output.get("video_url") or "").strip()
    task_id = str(output.get("task_id") or task_id).strip()
    print(f"[{NODE_PREFIX}] output video: task_id={task_id}, video_url={video_url}")
    return video_url, task_id


def build_text_to_video_payload(prompt, resolution, ratio, duration, watermark, seed):
    return {
        "model": "happyhorse-1.0-t2v",
        "input": {"prompt": _clean_prompt(prompt)},
        "parameters": _build_parameters(
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            watermark=watermark,
            seed=seed,
        ),
    }


def build_image_to_video_payload(prompt, first_frame_url, resolution, duration, watermark, seed):
    if not str(first_frame_url or "").strip():
        raise ValueError("image is required for Image To Video.")
    return {
        "model": "happyhorse-1.0-i2v",
        "input": {
            "prompt": _clean_prompt(prompt, required=False),
            "media": [{"type": "first_frame", "url": str(first_frame_url).strip()}],
        },
        "parameters": _build_parameters(
            resolution=resolution,
            duration=duration,
            watermark=watermark,
            seed=seed,
        ),
    }


def build_reference_to_video_payload(prompt, reference_urls, resolution, ratio, duration, watermark, seed):
    urls = [str(url).strip() for url in reference_urls if str(url or "").strip()]
    if not (1 <= len(urls) <= 9):
        raise ValueError("Reference To Video requires 1 to 9 reference images.")
    return {
        "model": "happyhorse-1.0-r2v",
        "input": {
            "prompt": _clean_prompt(prompt),
            "media": [{"type": "reference_image", "url": url} for url in urls],
        },
        "parameters": _build_parameters(
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            watermark=watermark,
            seed=seed,
        ),
    }


def build_video_edit_payload(prompt, video_url, reference_urls, resolution, watermark, audio_setting, seed):
    video_url = str(video_url or "").strip()
    if not video_url:
        raise ValueError("video_url is required for Video Edit.")
    urls = [str(url).strip() for url in reference_urls if str(url or "").strip()]
    if len(urls) > 5:
        raise ValueError("Video Edit supports at most 5 reference images.")
    media = [{"type": "video", "url": video_url}]
    media.extend({"type": "reference_image", "url": url} for url in urls)
    return {
        "model": "happyhorse-1.0-video-edit",
        "input": {
            "prompt": _clean_prompt(prompt),
            "media": media,
        },
        "parameters": _build_parameters(
            resolution=resolution,
            watermark=watermark,
            seed=seed,
            audio_setting=audio_setting,
        ),
    }


def _tensor_to_pil_images(image):
    if image is None:
        return []
    if hasattr(image, "detach"):
        array = image.detach().cpu().numpy()
    elif hasattr(image, "cpu"):
        array = image.cpu().numpy()
    else:
        array = image
    array = numpy.asarray(array)
    if array.ndim == 3:
        array = array[numpy.newaxis, ...]
    if array.ndim != 4:
        raise ValueError("IMAGE input must be a 3D or 4D tensor.")
    images = []
    for frame in array:
        pixels = numpy.clip(frame * 255.0, 0.0, 255.0).astype(numpy.uint8)
        images.append(Image.fromarray(pixels).convert("RGB"))
    return images


def _normalize_tmpfiles_download_url(page_url):
    normalized = str(page_url or "").strip()
    if not normalized:
        raise ValueError("Upload service did not return a file URL.")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.netloc.lower() != "tmpfiles.org":
        return normalized
    path = parsed.path.strip("/")
    if not path:
        raise ValueError("Upload service returned an invalid tmpfiles URL.")
    if path.startswith("dl/"):
        return f"https://tmpfiles.org/{path}"
    return f"https://tmpfiles.org/dl/{path}"


def _upload_file_to_tmpfiles(file_path, timeout=DEFAULT_UPLOAD_TIMEOUT):
    normalized_path = os.path.abspath(os.fspath(file_path))
    if not os.path.exists(normalized_path):
        raise ValueError(f"Upload file does not exist: {normalized_path}")
    if os.path.getsize(normalized_path) > TMPFILES_MAX_SIZE_BYTES:
        raise ValueError("Local media file exceeds tmpfiles.org's 100 MB upload limit.")

    filename = os.path.basename(normalized_path)
    last_error = None
    for attempt in range(1, TMPFILES_UPLOAD_RETRY_COUNT + 1):
        try:
            with open(normalized_path, "rb") as handle:
                response = requests.post(
                    TMPFILES_UPLOAD_API_URL,
                    files={"file": (filename, handle)},
                    timeout=float(timeout),
                )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "success":
                raise ValueError(f"Temporary media upload failed: {payload}")
            return _normalize_tmpfiles_download_url(payload.get("data", {}).get("url"))
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < TMPFILES_UPLOAD_RETRY_COUNT:
                print(f"[{NODE_PREFIX}] tmpfiles upload retry {attempt}: {exc}")
                time.sleep(TMPFILES_UPLOAD_RETRY_DELAY)
    raise ConnectionError(f"Temporary media upload failed: {last_error}") from last_error


def _upload_pil_image(image, index=0):
    config = _resolve_config()
    with tempfile.NamedTemporaryFile(prefix=f"happyhorse_{index}_", suffix=".png", delete=False) as handle:
        temp_path = handle.name
    try:
        image.save(temp_path, format="PNG")
        return _upload_file_to_tmpfiles(temp_path, timeout=config["upload_timeout"])
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _upload_image_batch(image, minimum=1, maximum=None):
    images = _tensor_to_pil_images(image)
    if len(images) < minimum:
        raise ValueError(f"At least {minimum} image(s) are required.")
    if maximum is not None and len(images) > maximum:
        raise ValueError(f"At most {maximum} image(s) are supported.")
    return [_upload_pil_image(frame, index=index) for index, frame in enumerate(images)]


def _fetch_binary(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    config = _resolve_config()
    endpoint = str(config.get("endpoint") or "").rstrip("/")
    if endpoint and str(url).startswith(endpoint + "/videos/"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    response = requests.get(url, timeout=60, stream=True, headers=headers)
    response.raise_for_status()
    return response.content


def _saved_result(filename, subfolder, folder_type):
    return {"filename": filename, "subfolder": subfolder, "type": folder_type}


def _register_output_asset(file_path):
    try:
        import app.assets.services.ingest as asset_ingest
    except Exception:
        return
    try:
        asset_ingest.ingest_existing_file(file_path)
    except Exception as exc:
        print(f"[{NODE_PREFIX}] Failed to register output asset: {exc}")


def _build_local_media_view_url(filename, subfolder, folder_type):
    query = [
        f"type={urllib.parse.quote(str(folder_type), safe='')}",
        f"filename={urllib.parse.quote(str(filename), safe='')}",
    ]
    if subfolder:
        query.append(f"subfolder={urllib.parse.quote(str(subfolder), safe='')}")
    return "/api/view?" + "&".join(query)


class HappyHorseTextToVideoNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "resolution": (RESOLUTIONS, {"default": "1080P"}),
                "ratio": (RATIOS, {"default": "16:9"}),
                "duration": (DURATIONS, {"default": "5"}),
                "watermark": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": -1, "min": -1, "max": SEED_MAX}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION = "generate"
    CATEGORY = NODE_CATEGORY

    def generate(self, prompt, resolution, ratio, duration, watermark, seed):
        return _submit_and_wait(build_text_to_video_payload(prompt, resolution, ratio, duration, watermark, seed))


class HappyHorseImageToVideoNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "resolution": (RESOLUTIONS, {"default": "1080P"}),
                "duration": (DURATIONS, {"default": "5"}),
                "watermark": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": -1, "min": -1, "max": SEED_MAX}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION = "generate"
    CATEGORY = NODE_CATEGORY

    def generate(self, image, prompt, resolution, duration, watermark, seed):
        first_frame_url = _upload_image_batch(image, minimum=1, maximum=1)[0]
        payload = build_image_to_video_payload(prompt, first_frame_url, resolution, duration, watermark, seed)
        return _submit_and_wait(payload)


class HappyHorseReferenceToVideoNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_images": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "resolution": (RESOLUTIONS, {"default": "1080P"}),
                "ratio": (RATIOS, {"default": "16:9"}),
                "duration": (DURATIONS, {"default": "5"}),
                "watermark": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": -1, "min": -1, "max": SEED_MAX}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION = "generate"
    CATEGORY = NODE_CATEGORY

    def generate(self, reference_images, prompt, resolution, ratio, duration, watermark, seed):
        urls = _upload_image_batch(reference_images, minimum=1, maximum=9)
        payload = build_reference_to_video_payload(prompt, urls, resolution, ratio, duration, watermark, seed)
        return _submit_and_wait(payload)


class HappyHorseVideoEditNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {"multiline": False, "default": ""}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "resolution": (RESOLUTIONS, {"default": "1080P"}),
                "watermark": ("BOOLEAN", {"default": True}),
                "audio_setting": (AUDIO_SETTINGS, {"default": "auto"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": SEED_MAX}),
            },
            "optional": {
                "reference_images": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id")
    FUNCTION = "generate"
    CATEGORY = NODE_CATEGORY

    def generate(self, video_url, prompt, resolution, watermark, audio_setting, seed, reference_images=None):
        urls = _upload_image_batch(reference_images, minimum=0, maximum=5) if reference_images is not None else []
        payload = build_video_edit_payload(prompt, video_url, urls, resolution, watermark, audio_setting, seed)
        return _submit_and_wait(payload)


class HappyHorsePreviewVideoNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": DEFAULT_FILENAME_PREFIX}),
                "save_output": ("BOOLEAN", {"default": True}),
            }
        }

    OUTPUT_NODE = True
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    FUNCTION = "run"
    CATEGORY = NODE_CATEGORY

    def run(self, video_url, filename_prefix, save_output):
        if isinstance(video_url, list):
            video_url = video_url[0]
        video_url = str(video_url or "").strip()
        if not video_url:
            raise ValueError("Preview Video received an empty video_url.")

        if not save_output:
            return {"ui": {"video_url": [video_url]}, "result": ("",)}

        output_dir = folder_paths.get_output_directory()
        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix,
            output_dir,
        )
        file = f"{filename}_{counter:05}_.mp4"
        file_path = os.path.join(full_output_folder, file)
        os.makedirs(full_output_folder, exist_ok=True)
        with open(file_path, "wb") as handle:
            handle.write(_fetch_binary(video_url))

        _register_output_asset(file_path)
        preview_url = _build_local_media_view_url(file, subfolder, "output")
        return {
            "ui": {
                "images": [_saved_result(file, subfolder, "output")],
                "video_url": [preview_url],
                "animated": (True,),
            },
            "result": (file_path,),
        }
