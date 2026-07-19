from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def is_bt_speaker_connected(mac: str) -> bool:
    try:
        proc = subprocess.run(
            ["bluetoothctl", "info", mac],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return "Connected: yes" in proc.stdout


def ensure_bt_speaker_connected(mac: str) -> bool:
    """Connect paired BT speaker if it is not already connected."""
    if not mac:
        return False
    if is_bt_speaker_connected(mac):
        return True
    try:
        proc = subprocess.run(
            ["bluetoothctl", "connect", mac],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.debug("Bluetooth connect timed out for %s", mac)
        return False
    if is_bt_speaker_connected(mac):
        logger.info("Bluetooth speaker connected (%s)", mac)
        return True
    stderr = proc.stderr.strip()
    if stderr:
        logger.debug("Bluetooth connect failed for %s: %s", mac, stderr)
    return False
