import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mutation_check.py"
spec = importlib.util.spec_from_file_location("mutation_check", SCRIPT)
mutation_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutation_check)


@pytest.fixture
def backend_dir(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_dotted.py").write_text("import arp.net_safety\n")
    (tmp_path / "tests" / "test_from.py").write_text("from arp import net_safety, other\n")
    (tmp_path / "tests" / "test_prefix.py").write_text("import arp.net_safety_extra\n")
    (tmp_path / "tests" / "test_unrelated.py").write_text("from arp import config\n")
    monkeypatch.chdir(tmp_path)


def test_tests_for_finds_dotted_and_from_imports_only(backend_dir):
    assert mutation_check.tests_for("arp/net_safety.py") == ["tests/test_dotted.py", "tests/test_from.py"]


def test_tests_for_a_package_init_uses_the_package_name(backend_dir):
    (Path("tests") / "test_pkg.py").write_text("from arp.portfolio import news\n")
    assert mutation_check.tests_for("arp/portfolio/__init__.py") == ["tests/test_pkg.py"]


class _Run:
    def __init__(self, returncode, stdout=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, ""


def _mutmut(monkeypatch, run_returncode, run_stdout="", seen=None):
    def run(cmd, **kwargs):
        if cmd[:2] == ["mutmut", "run"]:
            if seen is not None:
                seen["cfg"] = Path("setup.cfg").read_text()
                seen["env"] = kwargs.get("env") or {}
            return _Run(run_returncode, run_stdout)
        return _Run(0)

    monkeypatch.setattr(mutation_check.subprocess, "run", run)


def test_nothing_covered_is_reported_not_an_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _mutmut(monkeypatch, 1, "Stopping early, because we could not find any test case for any mutant.")
    assert mutation_check.mutate("arp/pkg/__init__.py", ["tests/test_x.py"]) == {"uncovered": []}


def test_a_real_mutmut_failure_is_still_an_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _mutmut(monkeypatch, 1, "failed to collect stats. runner returned 1")
    assert "error" in mutation_check.mutate("arp/x.py", ["tests/test_x.py"])


def test_mutants_copy_includes_scripts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seen = {}
    _mutmut(monkeypatch, 0, seen=seen)
    mutation_check.mutate("arp/x.py", ["tests/test_x.py"])
    assert "also_copy =\n    scripts/\n" in seen["cfg"]


def _main(monkeypatch, files, mutate):
    monkeypatch.setattr(mutation_check, "changed_files", lambda base, since: files)
    monkeypatch.setattr(mutation_check, "tests_for", lambda path: ["tests/test_x.py"])
    monkeypatch.setattr(mutation_check, "mutate", mutate)
    monkeypatch.setattr(sys, "argv", ["mutation_check.py", "--base", "origin/main"])
    return mutation_check.main()


def test_uncovered_file_does_not_fail_the_job(monkeypatch, capsys):
    assert _main(monkeypatch, ["arp/pkg/__init__.py"], lambda path, tests: {"uncovered": []}) == 0
    assert "no mutant is covered by these tests" in capsys.readouterr().out


def test_config_is_skipped_not_mutated(monkeypatch, capsys):
    assert _main(monkeypatch, ["arp/config.py"], lambda path, tests: pytest.fail("mutmut ran on arp/config.py")) == 0
    assert "skipped" in capsys.readouterr().out


def test_mutants_copy_finds_the_rule_book(monkeypatch, tmp_path):
    """Tests that start the API check the rule book; mutmut's copy must get its real path, not REPO_ROOT's."""
    monkeypatch.chdir(tmp_path)
    seen = {}
    _mutmut(monkeypatch, 0, seen=seen)
    mutation_check.mutate("arp/x.py", ["tests/test_x.py"])
    assert seen["env"]["ARP_TRANSITION_BARRIER_DATA_DIR"] == str(tmp_path / "arp/transition_barrier/data")
    assert seen["env"]["ARP_TRANSITION_ALIGNMENT_DATA_DIR"] == str(tmp_path / "arp/transition_alignment/data")


def test_link_repo_root_links_missing_top_level_entries(tmp_path, monkeypatch):
    for name in ("backend/tests", "backend/scripts/check.py", "docs", "scripts/report.js", ".git"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("") if "." in path.name else path.mkdir()
    monkeypatch.chdir(tmp_path / "backend")
    made = mutation_check.link_repo_root()
    assert sorted(str(p) for p in made) == ["backend", "docs", "scripts/report.js"]
    assert Path("backend/tests").is_dir() and Path("docs").resolve() == tmp_path / "docs"
    assert Path("scripts/report.js").resolve() == tmp_path / "scripts" / "report.js"
    assert not Path(".git").exists()


def test_a_mutmut_timeout_is_reported_not_raised(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def run(cmd, **kwargs):
        if cmd[:2] == ["mutmut", "run"]:
            raise mutation_check.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return _Run(0)

    monkeypatch.setattr(mutation_check.subprocess, "run", run)
    assert mutation_check.mutate("arp/x.py", ["tests/test_x.py"]) == {"timeout": []}


def test_a_timed_out_file_is_listed_and_the_next_file_still_runs(monkeypatch, capsys):
    ran = []

    def mutate(path, tests):
        ran.append(path)
        return {"timeout": []} if path == "arp/api/main.py" else {"killed": ["m1"]}

    assert _main(monkeypatch, ["arp/api/main.py", "arp/y.py"], mutate) == 0
    out = capsys.readouterr().out
    assert ran == ["arp/api/main.py", "arp/y.py"]
    assert "| `arp/api/main.py` | 1 | – | – | **timed out** after 30 min: too many tests import it to mutate in CI |" in out
