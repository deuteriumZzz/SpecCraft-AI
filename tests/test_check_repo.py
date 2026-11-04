"""scripts/check_repo.sh: охранный скрипт не должен пропускать локальные файлы и секреты."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_repo.sh"


def _run(tmp_path: Path, files: dict[str, str]) -> subprocess.CompletedProcess:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "check_repo.sh")
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A", "-f"], cwd=tmp_path, check=True)
    return subprocess.run(
        ["bash", "scripts/check_repo.sh"], cwd=tmp_path, capture_output=True, text=True
    )


def test_clean_repo_passes(tmp_path):
    assert _run(tmp_path, {"a.py": "x = 1\n", ".env.example": "GEMINI_API_KEY=\n"}).returncode == 0


@pytest.mark.parametrize(
    "name",
    ["Схема.pdf", "Описание проекта.docx", ".env", ".env.local", "my.env", "k.pem",
     "SPEC.PDF", "KEY.PEM"],  # не-ASCII имена и регистр расширений не должны обходить охрану
)
def test_forbidden_file_names_are_blocked(tmp_path, name):
    result = _run(tmp_path, {name: "x"})
    assert result.returncode != 0 and name in result.stdout  # в т.ч. не-ASCII имена


def test_key_like_content_is_blocked(tmp_path):
    fake_key = "AIza" + "x" * 35  # собираем на лету, чтобы этот файл сам не выглядел секретом
    result = _run(tmp_path, {"cfg.py": f'KEY = "{fake_key}"\n'})
    assert result.returncode != 0
