from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time

logger = logging.getLogger(__name__)

_ACTION_VERB_RE = re.compile(r"^(say|speak|announce|play|alert|notify)\s+", re.IGNORECASE)
_last_spoke: float = 0.0


async def speak(text: str) -> None:
    """Speak text using espeak-ng TTS played through built-in audio."""
    text = text.strip().strip('"').strip("'")
    # Strip action verb prefix
    text = _ACTION_VERB_RE.sub("", text).strip()
    if not text:
        return

    # Debounce: don't speak more than once per 3 seconds
    global _last_spoke
    now = time.time()
    if now - _last_spoke < 3.0:
        return
    _last_spoke = now

    try:
        # Generate WAV via espeak-ng
        wav_bytes = subprocess.run(  # noqa: ASYNC221
            ["espeak-ng", text, "--stdout"],
            capture_output=True,
            timeout=10,
        ).stdout

        if not wav_bytes:
            logger.warning("espeak-ng produced no output for: %s", text)
            return

        # Set low volume and play via bluealsa on BT speaker
        subprocess.run(  # noqa: ASYNC221
            ["amixer", "-D", "bluealsa", "sset", "TWS Mini Speaker A2DP", "20%"],
            capture_output=True, timeout=3,
        )
        proc = await asyncio.create_subprocess_exec(
            "aplay", "-D", "bluealsa",
            "-f", "S16_LE", "-r", "22050", "-c", "1",
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await proc.communicate(input=wav_bytes)
        logger.info("Spoke: %s", text)

    except FileNotFoundError:
        logger.error("espeak-ng not installed")
    except subprocess.TimeoutExpired:
        logger.warning("espeak-ng timed out for: %s", text)
    except Exception:
        logger.exception("Failed to speak: %s", text)
