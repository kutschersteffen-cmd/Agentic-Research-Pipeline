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
