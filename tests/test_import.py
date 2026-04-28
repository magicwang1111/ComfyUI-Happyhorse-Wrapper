import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMFY_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(COMFY_ROOT))


def test_node_mappings_import():
    import importlib.util

    spec = importlib.util.spec_from_file_location("happyhorse_wrapper", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["happyhorse_wrapper"] = module
    spec.loader.exec_module(module)

    assert "ComfyUI-Happyhorse-Wrapper Image To Video" in module.NODE_CLASS_MAPPINGS
    assert "ComfyUI-Happyhorse-Wrapper Preview Video" in module.NODE_DISPLAY_NAME_MAPPINGS

