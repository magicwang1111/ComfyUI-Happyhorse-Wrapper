from .nodes import (
    HappyHorseImageToVideoNode,
    HappyHorsePreviewVideoNode,
    HappyHorseReferenceToVideoNode,
    HappyHorseTextToVideoNode,
    HappyHorseVideoEditNode,
)

# The ComfyUI convention of naming this package `py` can shadow pytest's
# legacy `py` dependency when tests are run from the repository root.
try:
    from _pytest._py import path as path  # type: ignore
except Exception:
    path = None

NODE_PREFIX = "ComfyUI-Happyhorse-Wrapper"


def _node_name(label):
    return f"{NODE_PREFIX} {label}"


NODE_CLASS_MAPPINGS = {
    _node_name("Text To Video"): HappyHorseTextToVideoNode,
    _node_name("Image To Video"): HappyHorseImageToVideoNode,
    _node_name("Reference To Video"): HappyHorseReferenceToVideoNode,
    _node_name("Video Edit"): HappyHorseVideoEditNode,
    _node_name("Preview Video"): HappyHorsePreviewVideoNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {key: key for key in NODE_CLASS_MAPPINGS}
