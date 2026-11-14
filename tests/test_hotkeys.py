from __future__ import annotations

from eyelens.hotkeys import HotkeyManager


class _VkKey:
    def __init__(self, vk: int) -> None:
        self.vk = vk


def test_virtual_key_hotkey_ignores_auto_repeat(monkeypatch) -> None:
    manager = HotkeyManager()
    fired: list[str] = []
    manager.toggle_lens.connect(lambda: fired.append("toggled"))
    monkeypatch.setattr(manager, "_ctrl_alt_down", lambda: True)

    manager._on_key_press(_VkKey(0x4C))  # L
    manager._on_key_press(_VkKey(0x4C))  # auto-repeat while held
    manager._on_key_release(_VkKey(0x4C))
    manager._on_key_press(_VkKey(0x4C))

    assert fired == ["toggled", "toggled"]


def test_hotkey_requires_ctrl_and_alt(monkeypatch) -> None:
    manager = HotkeyManager()
    fired: list[str] = []
    manager.toggle_lens.connect(lambda: fired.append("toggled"))
    monkeypatch.setattr(manager, "_ctrl_alt_down", lambda: False)

    manager._on_key_press(_VkKey(0x4C))

    assert fired == []
