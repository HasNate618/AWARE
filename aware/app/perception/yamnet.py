from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import numpy as np

from aware.app.perception.interface import Detection, PerceptionSnapshot

logger = logging.getLogger(__name__)

_SOUND_LABELS = ["sound", "silence"]


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


class YAMNetMic:
    """Microphone capture + audio event detection. Implements PerceptionSource."""

    def __init__(
        self,
        device: int | str | None = None,
        sample_rate: int = 0,  # 0 = auto-detect native rate
        chunk_duration: float = 0.975,
        energy_threshold: float = 0.001,
        detection_interval: float = 0.25,
    ) -> None:
        self.device = device
        self.target_rate = 16000
        self.device_rate = 0  # set during start()
        self.chunk_duration = chunk_duration
        self.energy_threshold = energy_threshold
        self.detection_interval = detection_interval
        self._running = False
        self._last_snapshot: PerceptionSnapshot = PerceptionSnapshot(
            detections=[], sounds=[], source="mic_unavailable", timestamp=time.time()
        )
        self._sound_log: deque[dict[str, object]] = deque(maxlen=200)
        self._stream: Any = None
        self._audio_queue: deque[np.ndarray] = deque(maxlen=50)
        self._audio_buffer: list[np.ndarray] = []
        self._baseline_rms: float = 0.0
        self._last_event_time: float = 0.0
        self._event_cooldown: float = 2.0

    async def start(self) -> None:
        self._running = True
        try:
            import sounddevice as sd

            # Find USB mic
            if self.device is None:
                devices = sd.query_devices()
                for i, d in enumerate(devices):
                    if d["max_input_channels"] > 0 and "CAMERA" in d.get("name", "").upper():
                        self.device = i
                        self.device_rate = int(d["default_samplerate"])
                        logger.info(
                            "Found USB mic: %s (device %d, %dHz)", d["name"], i, self.device_rate
                        )
                        break
                if self.device is None:
                    for i, d in enumerate(devices):
                        if d["max_input_channels"] > 0 and "USB" in d.get("name", "").upper():
                            self.device = i
                            self.device_rate = int(d["default_samplerate"])
                            logger.info(
                                "Found USB mic: %s (device %d, %dHz)",
                                d["name"],
                                i,
                                self.device_rate,
                            )
                            break
                if self.device is None:
                    self.device = 0
                    dev_info = sd.query_devices(self.device, "input")
                    self.device_rate = int(dev_info["default_samplerate"])
                    logger.warning(
                        "No USB mic found, using default device %d (%dHz)",
                        self.device,
                        self.device_rate,
                    )

            if self.device_rate <= 0:
                self.device_rate = 48000

            # PortAudio requires exact native rate — always use device_rate

            # Start audio stream in a thread
            def audio_callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
                if status:
                    logger.warning("Audio status: %s", status)
                self._audio_queue.append(indata[:, 0].copy())

            self._stream = sd.InputStream(
                device=self.device,
                channels=1,
                samplerate=self.device_rate,
                blocksize=int(self.device_rate * 0.05),
                dtype="float32",
                callback=audio_callback,
            )
            self._stream.start()
            logger.info("Mic started (device=%s, rate=%dHz)", self.device, self.device_rate)
        except ImportError as e:
            logger.error("Missing dependency: %s", e)
        except Exception:
            logger.exception("Failed to start mic")

    async def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        logger.info("Mic stopped")

    async def snapshot(self) -> PerceptionSnapshot:
        return self._last_snapshot

    def get_sound_log(self, limit: int = 50) -> list[dict[str, object]]:
        """Return recent sound detections with timestamps."""
        items = list(self._sound_log)
        return items[-limit:]

    async def run_detection_loop(self) -> None:
        """Background loop: capture audio, classify sounds, store snapshot."""
        cycle = 0
        while self._running:
            queue_len = len(self._audio_queue)
            if queue_len == 0:
                await asyncio.sleep(0.05)
                continue
            cycle += 1
            try:
                snapshot = await asyncio.to_thread(self._detect)
                self._last_snapshot = snapshot
                if snapshot.sounds:
                    for snd in snapshot.sounds:
                        self._sound_log.append(
                            {
                                "label": snd.label,
                                "confidence": snd.confidence,
                                "timestamp": snapshot.timestamp,
                            }
                        )
                        logger.info("[sound] %s (%.0f%%)", snd.label, snd.confidence * 100)
                elif cycle % 20 == 0:
                    logger.info("[sound] queue=%d no detections", queue_len)
            except Exception:
                logger.exception("Sound detection error")
            await asyncio.sleep(self.detection_interval)

    def _detect(self) -> PerceptionSnapshot:
        """Accumulate audio chunks and detect sound events."""
        while self._audio_queue:
            try:
                self._audio_buffer.append(self._audio_queue.popleft())
            except IndexError:
                break

        if not self._audio_buffer:
            return PerceptionSnapshot(detections=[], sounds=[], source="mic", timestamp=time.time())

        audio = np.concatenate(self._audio_buffer)
        if self.device_rate != self.target_rate:
            ratio = self.target_rate / self.device_rate
            new_len = int(len(audio) * ratio)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, new_len),
                np.arange(len(audio)),
                audio.astype(np.float64),
            ).astype(np.float32)

        chunk_samples = int(self.target_rate * self.chunk_duration)
        if len(audio) < chunk_samples:
            return PerceptionSnapshot(detections=[], sounds=[], source="mic", timestamp=time.time())

        audio = audio[-chunk_samples:]
        used_device_samples = int(self.device_rate * self.chunk_duration)
        total_device_samples = sum(c.shape[0] for c in self._audio_buffer)
        if total_device_samples > used_device_samples * 2:
            self._audio_buffer = self._audio_buffer[-10:]

        rms_val = _rms(audio)

        # Track baseline with exponential moving average
        if self._baseline_rms == 0.0:
            self._baseline_rms = rms_val
        else:
            self._baseline_rms = self._baseline_rms * 0.9 + rms_val * 0.1

        # Only report on energy spikes (2x baseline)
        ratio = rms_val / (self._baseline_rms + 1e-10)
        now = time.time()
        cooldown_ok = (now - self._last_event_time) > self._event_cooldown

        if ratio > 2.0 and cooldown_ok:
            self._last_event_time = now
            conf = min(ratio / 5.0, 0.95)
            sound = Detection(label="sound", confidence=round(conf, 3))
            self._sound_log.append({
                "label": "sound",
                "confidence": conf,
                "timestamp": now,
            })
            logger.info("[sound] event rms=%.5f baseline=%.5f ratio=%.1f", rms_val, self._baseline_rms, ratio)
            return PerceptionSnapshot(
                detections=[], sounds=[sound], source="mic", timestamp=now,
            )

        return PerceptionSnapshot(
            detections=[], sounds=[], source="mic", timestamp=time.time(),
        )
