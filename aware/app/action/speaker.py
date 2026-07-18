from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)


async def speak(text: str) -> None:
    """Speak text using espeak-ng TTS played through built-in audio."""
    text = text.strip().strip('"').strip("'")
    if not text:
        return

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

        # Play via aplay on board's audio hardware
        proc = await asyncio.create_subprocess_exec(
            "aplay", "-f", "S16_LE", "-r", "22050", "-c", "1",
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
