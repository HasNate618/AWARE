from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from aware.app.action.bt_speaker import ensure_bt_speaker_connected
from aware.app.config import get_settings

logger = logging.getLogger(__name__)

_ACTION_VERB_RE = re.compile(r"^(say|speak|announce|play|alert|notify)\s+", re.IGNORECASE)
_last_spoke: float = 0.0


def _synthesize_espeak(text: str, wav_path: Path) -> None:
    proc = subprocess.run(
        ["espeak-ng", text, "-w", str(wav_path)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0 or not wav_path.is_file():
        stderr = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(stderr or "espeak-ng failed")


def _synthesize_piper(text: str, model_path: Path, wav_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "piper",
            "--model",
            str(model_path),
            "--output_file",
            str(wav_path),
        ],
        input=text,
        capture_output=True,
        timeout=30,
        check=False,
        text=True,
    )
    if proc.returncode != 0 or not wav_path.is_file():
        stderr = proc.stderr.strip()
        raise RuntimeError(stderr or f"piper exited {proc.returncode}")


def _synthesize_to_file(text: str, wav_path: Path) -> None:
    settings = get_settings()
    if settings.tts_engine.lower() == "piper":
        model = Path(settings.piper_model_path)
        if not model.is_file():
            raise FileNotFoundError(f"Piper model not found: {model}")
        _synthesize_piper(text, model, wav_path)
        return
    _synthesize_espeak(text, wav_path)


async def speak(text: str) -> None:
    """Speak text through the Bluetooth speaker (espeak-ng or Piper TTS)."""
    text = text.strip().strip('"').strip("'")
    text = _ACTION_VERB_RE.sub("", text).strip()
    if not text:
        return

    global _last_spoke
    now = time.time()
    if now - _last_spoke < 3.0:
        return
    _last_spoke = now

    settings = get_settings()
    await asyncio.to_thread(ensure_bt_speaker_connected, settings.bt_speaker_mac)

    fd, wav_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_name)
    try:
        await asyncio.to_thread(_synthesize_to_file, text, wav_path)

        subprocess.run(  # noqa: ASYNC221
            [
                "amixer",
                "-D",
                "bluealsa",
                "sset",
                "TWS Mini Speaker A2DP",
                settings.bt_speaker_volume,
            ],
            capture_output=True,
            timeout=3,
        )
        proc = await asyncio.create_subprocess_exec(
            "aplay",
            "-D",
            "bluealsa",
            str(wav_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await proc.wait()
        logger.info("Spoke (%s): %s", settings.tts_engine, text)

    except FileNotFoundError as exc:
        logger.error("TTS dependency missing: %s", exc)
    except subprocess.TimeoutExpired:
        logger.warning("TTS timed out for: %s", text)
    except Exception:
        logger.exception("Failed to speak: %s", text)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wav_name)
