"""Which device the models the backend loads itself run on: ARP_MODEL_DEVICE = auto | cpu | cuda.

torch and onnxruntime are imported inside the functions, so importing this module never imports torch.
Every function reads the setting on each call; nothing is cached except which log lines were written.
"""
import logging

from arp.config import get_settings

log = logging.getLogger(__name__)
_logged: set[str] = set()

_E1 = "ARP_MODEL_DEVICE=cuda but torch is not installed; set ARP_MODEL_DEVICE=auto to fall back to the CPU"
_E2 = "ARP_MODEL_DEVICE=cuda but no CUDA GPU is visible to torch; set ARP_MODEL_DEVICE=auto to fall back to the CPU"
_E3 = (
    "ARP_MODEL_DEVICE=cuda but onnxruntime has no CUDAExecutionProvider; "
    "run: pip uninstall -y onnxruntime && pip install onnxruntime-gpu"
)
_PROVIDER = "CUDAExecutionProvider"


class ModelDeviceError(RuntimeError):
    pass


def _torch_gpu() -> tuple[bool, str]:
    """(GPU visible to torch, reason it is not): reason is "" when visible."""
    try:
        import torch
    except Exception:  # noqa: BLE001 - a broken torch install counts as no torch
        return False, "torch not installed"
    return (True, "") if torch.cuda.is_available() else (False, "no GPU visible")


def _provider_listed() -> bool:
    try:
        import onnxruntime
    except Exception:  # noqa: BLE001
        return False
    return _PROVIDER in onnxruntime.get_available_providers()


def torch_device() -> str:
    mode = get_settings().model_device
    if mode == "cpu":
        return "cpu"
    visible, why = _torch_gpu()
    if visible:
        return "cuda"
    if mode == "cuda":
        raise ModelDeviceError(_E1 if why == "torch not installed" else _E2)
    return "cpu"


def onnx_cuda() -> bool:
    mode = get_settings().model_device
    if mode == "cpu":
        return False
    if torch_device() != "cuda":
        return False
    if _provider_listed():
        return True
    if mode == "cuda":
        raise ModelDeviceError(_E3)
    return False


def _why_cpu() -> str:
    if get_settings().model_device == "cpu":
        return "ARP_MODEL_DEVICE=cpu"
    return _torch_gpu()[1]


def _models_phrase() -> str:
    if torch_device() == "cuda":
        return "models on cuda"
    return f"models on cpu ({_why_cpu()})"


def _embeddings_phrase() -> str:
    if onnx_cuda():
        return "embeddings on cuda"
    if torch_device() == "cuda":
        return "embeddings on cpu (onnxruntime has no CUDAExecutionProvider)"
    return f"embeddings on cpu ({_why_cpu()})"


def summary() -> str:
    return f"{_models_phrase()}; {_embeddings_phrase()}"


def log_models() -> None:
    """Once per process: which device the torch models use. Call after torch_device() succeeded."""
    if "models" not in _logged:
        _logged.add("models")
        log.info(_models_phrase())


def log_embeddings() -> None:
    if "embeddings" not in _logged:
        _logged.add("embeddings")
        log.info(_embeddings_phrase())


def reset() -> None:
    _logged.clear()
