# ComfyUI-Happyhorse-Wrapper

ComfyUI custom nodes for HappyHorse 1.0 video generation. The nodes create a task, poll for completion, then return the temporary result URL and task ID.

Two endpoint styles are supported:

- DashScope official endpoints such as `https://dashscope.aliyuncs.com`, using `/api/v1/services/aigc/video-generation/video-synthesis`.
- AiHubMix OpenAI-compatible endpoints such as `https://aihubmix.com/v1`, using `/v1/videos`.

## Nodes

- `ComfyUI-Happyhorse-Wrapper Text To Video`
- `ComfyUI-Happyhorse-Wrapper Image To Video`
- `ComfyUI-Happyhorse-Wrapper Reference To Video`
- `ComfyUI-Happyhorse-Wrapper Video Edit`
- `ComfyUI-Happyhorse-Wrapper Preview Video`

## Setup

Install dependencies in the same Python environment used by ComfyUI:

```bash
python -m pip install -r ComfyUI/custom_nodes/ComfyUI-Happyhorse-Wrapper/requirements.txt
```

Create `config.local.json` in this folder:

```json
{
  "api_key": "sk-...",
  "endpoint": "https://dashscope.aliyuncs.com",
  "poll_interval": 15,
  "request_timeout": 60,
  "upload_timeout": 120
}
```

The plugin also reads `DASHSCOPE_API_KEY` or `AIHUBMIX_API_KEY` from the environment. Use `https://dashscope-intl.aliyuncs.com` for Singapore-region keys.

With the local AiHubMix endpoint tested during development, `happyhorse-1.0-t2v` and authenticated content download worked through `/v1/videos`. Official DashScope endpoints keep the documented media URL payload for I2V/R2V/video-edit.

## Media Uploads

HappyHorse media inputs require HTTP/HTTPS URLs. The image nodes accept ComfyUI `IMAGE` tensors, save them as PNG files, then upload them before calling the API.

For reliable DashScope access, configure Alibaba Cloud OSS. The wrapper uploads media to OSS and sends a signed HTTPS URL to DashScope:

Create `.env` in this plugin folder:

```env
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_BUCKET=your-bucket
OSS_PREFIX=Happyhorse/
```

Or set the same values in your shell before starting ComfyUI:

```powershell
$env:OSS_ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"
$env:OSS_ACCESS_KEY_ID = "your-access-key-id"
$env:OSS_ACCESS_KEY_SECRET = "your-access-key-secret"
$env:OSS_BUCKET = "your-bucket"
$env:OSS_PREFIX = "Happyhorse/"
```

You can also set `oss_uri` such as `oss://your-bucket/Happyhorse/` and `oss_endpoint` in `config.local.json`. Config values override environment variables and `.env`. If OSS is not configured, the wrapper falls back to `tmpfiles.org`, which may be unreachable from the model service even when it works from your browser.

Generated video URLs expire, so connect generation nodes to `Preview Video` to save the MP4 under the ComfyUI output directory.

## Model Notes

- Text To Video uses `happyhorse-1.0-t2v` and supports `ratio`.
- Image To Video uses `happyhorse-1.0-i2v`; the output aspect ratio follows the first frame, so there is no `ratio` input.
- Reference To Video uses `happyhorse-1.0-r2v`; image batch order maps to `character1`, `character2`, and so on in the prompt.
- Video Edit uses `happyhorse-1.0-video-edit`; provide one public MP4/MOV URL and optional reference images.
