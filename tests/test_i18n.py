from __future__ import annotations

import ast
from pathlib import Path

from eyelens.config import Settings
from eyelens.i18n import _RU, resolve_language, set_language, system_language, tr

PACKAGE = Path(__file__).resolve().parent.parent / "eyelens"


def test_system_language_is_concrete() -> None:
    assert system_language() in ("ru", "en")
    assert resolve_language("auto") == system_language()
    assert resolve_language("banana") == "en"


def test_russian_translation_and_fallback() -> None:
    try:
        set_language("ru")
        assert tr("Not calibrated") == "Не откалибровано"
        assert tr("Unused text") == "Unused text"
    finally:
        set_language("en")
    assert tr("Not calibrated") == "Not calibrated"


def test_language_setting_roundtrip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    original = Settings(language="ru")
    original.save(path)
    assert Settings.load(path).language == "ru"
    assert Settings(language="banana").normalized().language == "auto"


def test_every_literal_ui_string_is_translated() -> None:
    missing: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "tr"):
                continue
            if not node.args:
                continue

            def texts(argument: ast.expr) -> list[str]:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    return [argument.value]
                if isinstance(argument, ast.IfExp):
                    return texts(argument.body) + texts(argument.orelse)
                return []

            for text in texts(node.args[0]):
                if any(char.isalpha() for char in text) and text not in _RU:
                    missing.append(f"{path.name}:{node.lineno}: {text}")
    assert not missing, "\n".join(missing)
