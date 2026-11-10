from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Repository hygiene checks require a Git checkout.")


def test_no_tracked_python_bytecode():
    tracked = git("ls-files", "-z").split("\0")
    unwanted = [path for path in tracked if "__pycache__" in path.split("/")
                or path.endswith((".pyc", ".pyo"))]
    assert unwanted == [], f"Generated Python bytecode must not be tracked: {unwanted}"


def test_nested_python_caches_are_ignored():
    candidates = ["__pycache__/test.pyc", "planner/domain/__pycache__/test.pyc", "planner/test.pyo"]
    assert set(git("check-ignore", "--no-index", *candidates).splitlines()) == set(candidates)
