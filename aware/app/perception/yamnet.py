from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import numpy as np

from aware.app.perception.interface import Detection, PerceptionSnapshot

logger = logging.getLogger(__name__)

# Sound event labels we detect
SOUND_LABELS = [
    "glass_break",
    "doorbell",
    "knock",
    "speech",
    "alarm",
    "siren",
    "dog_bark",
    "cat_meow",
    "silence",
    "ambient",
]

# Frequency ranges (Hz) for different sound types
_FREQ_RANGES: dict[str, tuple[int, int]] = {
    "glass_break": (2000, 8000),
    "doorbell": (800, 2000),
    "knock": (200, 800),
    "speech": (300, 3400),
    "alarm": (1000, 4000),
    "siren": (500, 3000),
    "dog_bark": (300, 1500),
    "cat_meow": (600, 2000),
}


def _rms(audio: np.ndarray) -> float:
    """Root mean square energy."""
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def _spectral_centroid(audio: np.ndarray, sr: int) -> float:
    """Dominant frequency centroid."""
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
    total = fft.sum()
    if total < 1e-10:
        return 0.0
    return float(np.sum(freqs * fft) / total)


def _dominant_freq(audio: np.ndarray, sr: int) -> tuple[float, float]:
    """Return (dominant_freq_hz, strength) where strength is 0-1."""
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
    # Ignore DC and very low frequencies
    mask = freqs > 100
    if not mask.any():
        return (0.0, 0.0)
    fft_masked = fft[mask]
    freqs_masked = freqs[mask]
    peak_idx = fft_masked.argmax()
    peak_freq = freqs_masked[peak_idx]
    peak_val = fft_masked[peak_idx]
    # Strength = how much the peak stands out above the noise floor
    median_val = np.median(fft_masked)
    if median_val < 1e-10:
        return (float(peak_freq), 0.0)
    snr = peak_val / median_val  # signal-to-noise ratio
    # Map SNR to 0-1: SNR of 3 = weak (0.3), SNR of 10 = strong (0.8), SNR of 20+ = very strong (1.0)
    strength = min(max((snr - 2) / 15, 0.0), 1.0)
    return (float(peak_freq), float(strength))


def _band_energy(audio: np.ndarray, sr: int, fmin: int, fmax: int) -> float:
    """Fraction of total energy in a frequency band (0-1)."""
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
    total_energy = np.sum(fft ** 2)
    if total_energy < 1e-10:
        return 0.0
    band_mask = (freqs >= fmin) & (freqs <= fmax)
    band_energy = np.sum(fft[band_mask] ** 2)
    return float(band_energy / total_energy)


def _classify_sound(
    audio: np.ndarray, sr: int, rms: float, energy_threshold: float
) -> list[tuple[str, float]]:
    """Classify audio chunk into sound events with confidence scores."""
    if rms < energy_threshold:
        return [("silence", 0.9)]

    dom_freq, dom_strength = _dominant_freq(audio, sr)
    norm_energy = min(rms / (energy_threshold * 5), 1.0)

    # Only classify if we have a clear spectral peak
    if dom_strength < 0.2:
        return [("ambient", round(norm_energy * 0.5, 3))]

    detections: list[tuple[str, float]] = []

    for label, (fmin, fmax) in _FREQ_RANGES.items():
        # Peak must be within the frequency range
        if fmin <= dom_freq <= fmax:
            # Also check that significant energy is in this band
            band_frac = _band_energy(audio, sr, fmin, fmax)
            if band_frac < 0.15:
                continue  # Not enough energy in this band
            # Confidence: strong peak + high energy + good band match
            conf = dom_strength * 0.5 + norm_energy * 0.2 + band_frac * 0.3
            if conf > 0.35:
                detections.append((label, round(conf, 3)))

    # Speech: check for harmonic structure (voice has harmonics at ~100-300Hz spacing)
    if 200 < dom_freq < 4000 and norm_energy > 0.15:
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)
        # Look for harmonics: peaks at f0, 2*f0, 3*f0 where f0 ~ 80-300Hz
        speech_score = 0
        for f0 in [100, 150, 200, 250]:
            harmonic_strength = 0
            for h in range(1, 5):
                h_freq = f0 * h
                h_idx = np.argmin(np.abs(freqs - h_freq))
                if h_idx < len(fft):
                    harmonic_strength += fft[h_idx]
            if harmonic_strength > 0:
                speech_score = max(speech_score, harmonic_strength / (fft.sum() + 1e-10))
        if speech_score > 0.01:
            detections.append(("speech", round(min(speech_score * 20, 0.9), 3)))

    if not detections:
        return [("ambient", round(norm_energy * 0.3, 3))]

    # Return top detection only
    detections.sort(key=lambda x: x[1], reverse=True)
    return [detections[0]]

    # Sort by confidence, return top 3
    detections.sort(key=lambda x: x[1], reverse=True)
    return detections[:3]


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
        """Accumulate audio chunks and classify."""
        # Drain queue into persistent buffer
        while self._audio_queue:
            try:
                self._audio_buffer.append(self._audio_queue.popleft())
            except IndexError:
                break

        if not self._audio_buffer:
            return PerceptionSnapshot(detections=[], sounds=[], source="mic", timestamp=time.time())

        audio = np.concatenate(self._audio_buffer)

        # Resample to 16kHz if needed
        if self.device_rate != self.target_rate:
            ratio = self.target_rate / self.device_rate
            new_len = int(len(audio) * ratio)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, new_len),
                np.arange(len(audio)),
                audio.astype(np.float64),
            ).astype(np.float32)

        chunk_samples = int(self.target_rate * self.chunk_duration)

        # Need at least chunk_samples for analysis
        if len(audio) < chunk_samples:
            return PerceptionSnapshot(detections=[], sounds=[], source="mic", timestamp=time.time())

        # Use the latest chunk_samples, keep the rest in buffer
        audio = audio[-chunk_samples:]
        # Trim buffer: keep what wasn't used (approximately)
        used_device_samples = int(self.device_rate * self.chunk_duration)
        total_device_samples = sum(c.shape[0] for c in self._audio_buffer)
        if total_device_samples > used_device_samples * 2:
            self._audio_buffer = self._audio_buffer[-10:]

        rms_val = _rms(audio)
        sounds_raw = _classify_sound(audio, self.target_rate, rms_val, self.energy_threshold)

        # Always log audio level for debugging
        classified = [(label, conf) for label, conf in sounds_raw if label != "silence"]
        if classified:
            logger.info("[sound] rms=%.6f detected=%s", rms_val, classified)
        else:
            logger.info("[sound] rms=%.6f threshold=%.5f silence", rms_val, self.energy_threshold)

        sounds = [
            Detection(label=label, confidence=conf)
            for label, conf in sounds_raw
            if label != "silence"
        ]

        return PerceptionSnapshot(
            detections=[],
            sounds=sounds,
            source="mic",
            timestamp=time.time(),
        )
