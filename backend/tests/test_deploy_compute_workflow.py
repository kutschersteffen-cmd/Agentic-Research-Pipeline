import subprocess
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-compute.yml"
PATHS = [
    "backend/arp/ingestion/**",
    "backend/arp/compute/**",
    "backend/arp/retrieval/rerank.py",
    "backend/arp/retrieval/embeddings.py",
    "backend/arp/schemas/common.py",
    "backend/pyproject.toml",
    "backend/Dockerfile.compute",
    "scripts/gcp/**",
]
VARS = ["GCP_PROJECT", "GCP_REGION", "GCP_WIF_PROVIDER", "GCP_DEPLOY_SA"]
GATE = "steps.vars.outputs.configured == 'true'"


def _doc():
    return yaml.safe_load(WORKFLOW.read_text())


def _steps():
    return [step for job in _doc()["jobs"].values() for step in job["steps"]]


def test_triggers():  # AC-49
    doc = _doc()
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
    assert on["push"]["branches"] == ["main"]
    assert sorted(on["push"]["paths"]) == sorted(PATHS)
    assert "workflow_dispatch" in on


def test_every_gcp_step_is_gated():  # AC-38
    gcp = [s for s in _steps() if "google-github-actions" in s.get("uses", "") or "deploy_compute.sh" in s.get("run", "")]
    assert gcp and all(s.get("if") == GATE for s in gcp)


def _run_vars_step(tmp_path, values):
    step = next(s for s in _steps() if s.get("id") == "vars")
    assert {name: step["env"][name] for name in VARS} == {name: f"${{{{ vars.{name} }}}}" for name in VARS}
    out = tmp_path / "out"
    out.write_text("")
    res = subprocess.run(
        ["bash", "-e", "-c", step["run"]], env={"GITHUB_OUTPUT": str(out), "PATH": "/usr/bin:/bin", **values},
        capture_output=True, text=True,
    )
    return res, out.read_text()


def test_missing_variable_warns_and_passes(tmp_path):  # AC-38
    res, out = _run_vars_step(tmp_path, {"GCP_PROJECT": "p", "GCP_REGION": "r", "GCP_WIF_PROVIDER": "w", "GCP_DEPLOY_SA": ""})
    assert res.returncode == 0
    assert "::warning::" in res.stdout
    assert "configured=false" in out


def test_all_variables_enable_the_deploy(tmp_path):
    res, out = _run_vars_step(tmp_path, {"GCP_PROJECT": "p", "GCP_REGION": "r", "GCP_WIF_PROVIDER": "w", "GCP_DEPLOY_SA": "s"})
    assert res.returncode == 0 and "::warning::" not in res.stdout
    assert "configured=true" in out
