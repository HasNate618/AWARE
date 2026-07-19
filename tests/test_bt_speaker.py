from unittest.mock import patch

from aware.app.action.bt_speaker import ensure_bt_speaker_connected, is_bt_speaker_connected


def test_is_bt_speaker_connected_true() -> None:
    with patch(
        "aware.app.action.bt_speaker.subprocess.run",
        return_value=type("R", (), {"stdout": "Connected: yes"})(),
    ):
        assert is_bt_speaker_connected("15:D2:D2:C5:6B:0C") is True


def test_ensure_bt_speaker_connected_skips_when_connected() -> None:
    with patch("aware.app.action.bt_speaker.is_bt_speaker_connected", return_value=True):
        assert ensure_bt_speaker_connected("15:D2:D2:C5:6B:0C") is True
