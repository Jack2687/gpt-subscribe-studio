"""Ensure release scanning covers new files without ingesting ignored private data."""
import importlib.util
import subprocess
from pathlib import Path

SCANNER_PATH = Path(__file__).parents[2] / "scripts/release_check.py"


def scanner():
    spec = importlib.util.spec_from_file_location("release_check_test", SCANNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_scan_includes_untracked_and_respects_ignored_private_directories(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("private/\nruntime/\n*.har\n")
    (tmp_path / "tracked.py").write_text("value = 'fixture'\n")
    git(tmp_path, "add", ".gitignore", "tracked.py")
    # Assemble a synthetic scanner fixture in memory, not an actual credential.
    token = "sk-" + "Z" * 24
    (tmp_path / "new file.py").write_text(f"VALUE = '{token}'\n")
    (tmp_path / "new script.mjs").write_text(f"const VALUE = '{token}';\n")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "ignored.py").write_text(f"VALUE = '{token}'\n")
    module = scanner()
    paths = {p.relative_to(tmp_path).as_posix() for p in module._tracked_files(tmp_path)}
    assert "new file.py" in paths
    assert "tracked.py" in paths
    assert "private/ignored.py" not in paths
    hits = list(module._iter_findings(tmp_path))
    assert any(p.name == "new file.py" and kind == "openai_api_key" for p, _, kind, _ in hits)
    assert any(p.name == "new script.mjs" and kind == "openai_api_key" for p, _, kind, _ in hits)


def test_empty_git_repository_does_not_fallback_into_ignored_files(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text("private/\n")
    git(tmp_path, "add", ".gitignore")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "hidden.py").write_text("VALUE = 'sk-" + "Z" * 24 + "'\n")
    assert not list(scanner()._iter_findings(tmp_path))
