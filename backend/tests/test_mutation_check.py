import importlib.util
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
