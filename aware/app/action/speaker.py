from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from aware.app.action.bt_speaker import ensure_bt_speaker_connected, is_bt_speaker_connected
from aware.app.config import get_settings

logger = logging.getLogger(__name__)

_ACTION_VERB_RE = re.compile(r"^(say|speak|announce|play|alert|notify)\s+", re.IGNORECASE)
_last_spoke: float = 0.0
_piper_voice: Any = None
_piper_model_path: str = ""
_phrase_cache: dict[str, bytes] = {}
_MAX_PHRASE_CACHE = 24
_volume_set: bool = False


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


def _load_piper_voice(model_path: Path) -> Any:
    global _piper_voice, _piper_model_path
    resolved = str(model_path.resolve())
    if _piper_voice is not None and _piper_model_path == resolved:
        return _piper_voice
    from piper import PiperVoice

    logger.info("Loading Piper voice model: %s", resolved)
    _piper_voice = PiperVoice.load(resolved)
    _piper_model_path = resolved
    return _piper_voice


def _synthesize_piper(text: str, model_path: Path, wav_path: Path) -> None:
    voice = _load_piper_voice(model_path)
    with wav_path.open("wb") as wav_file:
        voice.synthesize(text, wav_file)


def _synthesize_to_file(text: str, wav_path: Path) -> None:
    cache_key = text.lower().strip()
    cached = _phrase_cache.get(cache_key)
    if cached:
        wav_path.write_bytes(cached)
        return

    settings = get_settings()
    if settings.tts_engine.lower() == "piper":
        model = Path(settings.piper_model_path)
        if not model.is_file():
            raise FileNotFoundError(f"Piper model not found: {model}")
        _synthesize_piper(text, model, wav_path)
    else:
        _synthesize_espeak(text, wav_path)

    if wav_path.is_file():
        _phrase_cache[cache_key] = wav_path.read_bytes()
        if len(_phrase_cache) > _MAX_PHRASE_CACHE:
            _phrase_cache.pop(next(iter(_phrase_cache)))


def _set_bt_volume(volume: str) -> None:
    global _volume_set
    if _volume_set:
        return
    subprocess.run(
        ["amixer", "-D", "bluealsa", "sset", "TWS Mini Speaker A2DP", volume],
        capture_output=True,
        timeout=3,
        check=False,
    )
    _volume_set = True


async def warmup_tts() -> None:
    """Pre-load Piper so the first rule-triggered speak is not delayed ~15s."""
    settings = get_settings()
    if settings.tts_engine.lower() != "piper":
        return
    model = Path(settings.piper_model_path)

    def _warm() -> None:
        if not model.is_file():
            logger.warning("Piper warmup skipped — model not found: %s", model)
            return
        fd, wav_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            _synthesize_to_file("ready", Path(wav_name))
            logger.info("Piper TTS warmed up")
        finally:
            with contextlib.suppress(OSError):
                os.unlink(wav_name)

    await asyncio.to_thread(_warm)


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
    if not is_bt_speaker_connected(settings.bt_speaker_mac):
        await asyncio.to_thread(ensure_bt_speaker_connected, settings.bt_speaker_mac)

    fd, wav_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_name)
    try:
        await asyncio.to_thread(_synthesize_to_file, text, wav_path)

        await asyncio.to_thread(_set_bt_volume, settings.bt_speaker_volume)
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
