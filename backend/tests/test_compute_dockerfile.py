"""backend/Dockerfile.compute's VARIANT build arg (spec portable-docker-images). Kept apart from the compute
server's tests: mutmut runs those in a copy of backend/ that has no Dockerfile."""

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile.compute"


def test_dockerfile_variants():  # AC-25
    text = DOCKERFILE.read_text()
    assert "ARG VARIANT=cpu" in text
    cuda = text.split('if [ "$VARIANT" = "cuda" ]', 1)[1].split("elif", 1)[0]
    assert '"onnxruntime-gpu==1.31.0"' in cuda and '"torch==2.14.1"' in cuda
    cpu = text.split('elif [ "$VARIANT" = "cpu" ]', 1)[1].split("else", 1)[0]
    assert "download.pytorch.org/whl/cpu" in cpu and "onnxruntime-gpu" not in cpu
