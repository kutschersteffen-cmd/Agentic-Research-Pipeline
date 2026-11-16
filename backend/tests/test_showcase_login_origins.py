"""The showcase runs with real sign-in (spec showcase-login-origins)."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app as real_app
from arp.config import Settings
from arp.storage.run_store import RunStore

REPO = Path(__file__).resolve().parents[2]
SPECS = REPO / "docs" / "superpowers" / "specs"
OLD_LINES = {"dev_trusted_networks": ["0.0.0.0/0"], "allowed_origins": ["*"]}
EVIL = {"Origin": "https://evil.example"}


@pytest.fixture
def showcase_local(tmp_path, pg):
    """The real app under the Showcase-local settings plus `extra`, called from `host`."""
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [
        {"token": "tok_presenter", "user_id": "u_presenter", "name": "Presenter", "role": "approver"}]}))

    def make(host, **extra):
        real_app.dependency_overrides.clear()
        real_app.dependency_overrides[settings_dep] = lambda: Settings(
            auth_mode="local", users_file=users, trusted_hosts=["*"], runs_dir=tmp_path / "runs", **extra
        )
        real_app.dependency_overrides[get_run_store] = lambda: RunStore(pg, tmp_path / "runs")
        return TestClient(real_app, client=(host, 5000))

    yield make
    real_app.dependency_overrides.clear()


def test_foreign_origin_cannot_cast(showcase_local):  # AC-1
    r = showcase_local("10.1.2.3", **OLD_LINES).post("/api/voting/runs/ac1_none/cast", headers=EVIL)
    assert (r.status_code, r.headers["WWW-Authenticate"]) == (401, "Bearer")


def test_foreign_origin_cannot_read(showcase_local):  # AC-2
    r = showcase_local("10.1.2.3", **OLD_LINES).get("/api/voting/runs/ac2_none/review-queue", headers=EVIL)
    assert r.status_code == 401


@pytest.mark.parametrize(("host", "run"), [("127.0.0.1", "ac3_none"), ("10.1.2.3", "ac11_none")])  # AC-3, AC-11
def test_no_token_no_origin_cannot_cast(showcase_local, host, run):
    assert showcase_local(host, **OLD_LINES).post(f"/api/voting/runs/{run}/cast").status_code == 401


def test_presenter_token_casts_from_the_hub(showcase_local):  # AC-4
    r = showcase_local("10.1.2.3").post(
        "/api/voting/runs/ac4_none/cast",
        headers={"Origin": "https://hub.example", "Authorization": "Bearer tok_presenter"},
    )
    assert (r.status_code, r.json()) == (200, {"cast_count": 0, "votes": []})


def section(text, heading):
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def bank_section():
    return section((REPO / "docs" / "INSTALLATION.md").read_text(), "## Bank Jupyter (Vertex)")


def test_guide_uses_local_sign_in():  # AC-8
    text = bank_section()
    ini = text.split("```ini\n", 1)[1].split("```", 1)[0]
    assert "ARP_AUTH_MODE=local" in ini and "ARP_USERS_FILE" in ini
    for gone in ("ARP_AUTH_MODE=dev", "ARP_DEV_TRUSTED_NETWORKS", "ARP_ALLOWED_ORIGINS"):
        assert gone not in ini, gone
    assert "scripts/launch_jupyter.sh users" in text


def plain(text):
    return re.sub(r"\s+", " ", text.replace("*", "").replace("_", ""))


def test_guide_and_readme_warn_against_dev_with_any_origin():  # AC-12
    warning = plain('Never combine `ARP_AUTH_MODE=dev` with `ARP_ALLOWED_ORIGINS=["*"]`: `"*"` lets any website '
                    "open in the same browser act as the dev approver.")
    readme = (REPO / "README.md").read_text()
    assert warning in plain(bank_section())
    assert warning in plain(readme)
    assert "another website cannot" not in readme


def assert_run_book(text):
    assert text.index("scripts/launch_jupyter.sh users") < text.index("scripts/launch_jupyter.sh up")
    loader = [line for line in text.splitlines() if "load_showcase_pack.py" in line]
    assert loader and all("ARP_SHOWCASE_TOKEN=" in line for line in loader), loader


def test_run_sheet_signs_in_before_up():  # AC-9
    assert_run_book(section((REPO / "demo" / "showcase" / "RUN_SHEET.md").read_text(), "## Day before"))


def test_showcase_readme_signs_in_before_up():  # AC-13
    assert_run_book((REPO / "demo" / "showcase" / "README.md").read_text())


def row(text, row_id):
    line = next(line for line in text.splitlines() if line.startswith(f"| {row_id} |"))
    return [cell.strip() for cell in line.strip("|").split(" | ")]


def test_voting_spec_retires_showcase_wording():  # AC-10
    text = (SPECS / "2026-11-15-voting-api-login.md").read_text()
    given = row(text, "AC-10")[1]
    assert "showcase-login-origins" in given and "the bank JupyterLab settings" not in given
    must_not_change = next(line for line in text.splitlines() if line.startswith("Must not change"))
    assert "AC-10" not in must_not_change


def test_launch_spec_rows_need_local_env():  # AC-14
    text = (SPECS / "2026-11-11-bank-jupyter-launch-design.md").read_text()
    given = row(text, "AC-11a")[1]
    assert "ARP_AUTH_MODE=local" in given and "showcase-login-origins" in given
    assert "AC-11a" in row(text, "AC-18")[1] and "AC-11a" in row(text, "AC-31")[1]


def test_users_prints_local_env_lines(tmp_path):  # AC-15
    copy = tmp_path / "repo"
    (copy / "scripts").mkdir(parents=True)
    (copy / "config").mkdir()
    shutil.copy(REPO / "scripts" / "launch_jupyter.sh", copy / "scripts")
    r = subprocess.run(["bash", str(copy / "scripts" / "launch_jupyter.sh"), "users"], capture_output=True,
                       text=True, env={**os.environ, "TMPDIR": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "  ARP_AUTH_MODE=local" in lines
    assert f"  ARP_USERS_FILE={copy}/config/users.json" in lines


STUB = """import http.server, pathlib, sys
port, me = int(sys.argv[sys.argv.index("--port") + 1]), pathlib.Path(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/health" else int(me.read_text()))
        self.end_headers()
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


@pytest.fixture
def launcher(tmp_path):
    """A repo copy whose `up` runs a stub server instead of uvicorn; `me` holds its /api/me status."""
    copy = tmp_path / "repo"
    for d in ("scripts", "backend", "frontend/dist", "bin"):
        (copy / d).mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "launch_jupyter.sh", copy / "scripts")
    (copy / "frontend" / "dist" / "index.html").write_text('<script src="./assets/x.js"></script>')
    me = tmp_path / "me_status"
    me.write_text("401")
    (tmp_path / "stub.py").write_text(STUB)
    shim = copy / "bin" / "python3"  # stands in for the database init and uvicorn
    shim.write_text(f'#!/bin/bash\ncase "$*" in\n  "-m arp db init-postgres") exit 0 ;;\n'
                    f'  "-m uvicorn "*) exec {sys.executable} {tmp_path / "stub.py"} {me} "$@" ;;\nesac\n'
                    f'exec {sys.executable} "$@"\n')
    shim.chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ARP_")}
    env.update(PATH=f"{copy / 'bin'}:{env['PATH']}", TMPDIR=str(tmp_path), ARP_LAUNCH_PORT=str(port),
               ARP_POSTGRES_DSN="x", ARP_LLM_MODEL="m", ARP_LLM_VERIFIER_MODEL="m")

    def launch(cmd, **extra):
        return subprocess.run(["bash", str(copy / "scripts" / "launch_jupyter.sh"), cmd], capture_output=True,
                              text=True, env={**env, **extra}, timeout=60)

    def serving():
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    yield SimpleNamespace(launch=launch, serving=serving, me=me, env_file=copy / "backend" / ".env", port=port)
    launch("down")


REFUSAL = "ARP_AUTH_MODE must be local for this launch"


def test_up_refuses_a_live_server_that_signs_in_without_token(launcher):  # code + security review of #569
    """`up` asks the running app: /api/me without a token must be 401, after start and when already running."""
    local = {"ARP_AUTH_MODE": "local"}
    launcher.me.write_text("200")  # a server in dev mode, whatever the settings said
    r = launcher.launch("up", **local)
    assert (r.returncode, REFUSAL in r.stderr, launcher.serving()) == (1, True, False), r
    launcher.me.write_text("401")  # local mode
    r = launcher.launch("up", **local)
    assert (r.returncode, r.stdout) == (0, f"http://localhost:{launcher.port}/\n"), r
    launcher.me.write_text("200")  # the running server signs in without a token
    r = launcher.launch("up", **local)
    assert (r.returncode, REFUSAL in r.stderr, launcher.serving()) == (1, True, False), r


@pytest.mark.parametrize(("env_file", "environ", "starts"), [
    ("ARP_AUTH_MODE=local\nexport ARP_AUTH_MODE=dev\n", {}, False),
    ("ARP_AUTH_MODE=local\nARP_AUTH_MODE = dev\n", {}, False),
    ("ARP_AUTH_MODE=local\n ARP_AUTH_MODE=dev\n", {}, False),
    ("ARP_AUTH_MODE=local\narp_auth_mode=dev\n", {}, False),
    ("ARP_AUTH_MODE=local\n", {"arp_auth_mode": "dev"}, False),
    ("ARP_AUTH_MODE=local # comment\n", {}, True),
    ("export ARP_AUTH_MODE=local\r\n", {}, True),
    ("ARP_AUTH_MODE=dev\nARP_AUTH_MODE=local\n", {}, True),
])
def test_up_reads_auth_mode_as_the_app_does(launcher, env_file, environ, starts):  # code + security review of #569
    launcher.env_file.write_text(env_file)
    r = launcher.launch("up", **environ)
    assert (r.returncode == 0, REFUSAL in r.stderr) == (starts, not starts), r
