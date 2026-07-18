from __future__ import annotations

import asyncio
import csv
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from aware.app.perception.interface import Detection, PerceptionSnapshot

logger = logging.getLogger(__name__)

# YAMNet class indices → AWARE vocabulary labels
_YAMNET_MAP: dict[int, str] = {
    0: "speech",
    6: "speech",     # Shout
    19: "crying",
    20: "baby_cry",
    69: "dog",
    70: "dog_bark",
    195: "doorbell",
    196: "doorbell",  # Church bell
    198: "doorbell",  # Bicycle bell
    292: "fire",
    304: "alarm",     # Car alarm
    317: "siren",     # Police siren
    318: "siren",     # Ambulance
    319: "siren",     # Fire truck
    344: "knock",     # Engine knocking
    349: "doorbell",
    353: "knock",
    382: "alarm",
    384: "doorbell",  # Telephone bell
    389: "alarm",     # Alarm clock
    390: "siren",
    392: "alarm",     # Buzzer
    393: "alarm",     # Smoke detector
    394: "alarm",     # Fire alarm
    420: "alarm",     # Explosion
    421: "alarm",     # Gunshot
    435: "glass_break",
}


def _load_yamnet(model_path: str, class_map_path: str) -> Any:
    """Load YAMNet ONNX model. Returns session or None on failure."""
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        # Load class map for display names
        class_names: dict[int, str] = {}
        p = Path(class_map_path)
        if p.exists():
            with open(p) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    class_names[int(row["index"])] = row["display_name"]
        logger.info("YAMNet loaded: %s (%d classes)", model_path, len(class_names))
        return sess, class_names
    except Exception:
        logger.exception("Failed to load YAMNet from %s", model_path)
        return None


def _classify_yamnet(
    audio: np.ndarray, session: Any, class_names: dict[int, str]
) -> tuple[str, float]:
    """Run YAMNet inference and return (label, confidence)."""
    try:
        inp = session.get_inputs()[0]
        scores = session.run(None, {inp.name: audio})[0][0]
        top_idx = int(scores.argmax())
        top_score = float(scores[top_idx])

        # Map to AWARE vocabulary, fall back to YAMNet display name
        label = _YAMNET_MAP.get(top_idx, class_names.get(top_idx, "sound"))
        return (label, round(top_score, 3))
    except Exception:
        logger.debug("YAMNet inference failed", exc_info=True)
        return ("sound", 0.5)


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def _classify_fft(audio: np.ndarray, sr: int) -> tuple[str, float]:
    """Fallback: FFT-based sound classification."""
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)

    mask = freqs > 100
    fft_f = fft[mask]
    freqs_f = freqs[mask]

    total_energy = np.sum(fft_f**2)
    if total_energy < 1e-10:
        return ("sound", 0.5)

    peak_idx = fft_f.argmax()
    peak_freq = freqs_f[peak_idx]
    peak_energy = fft_f[peak_idx] ** 2
    peak_ratio = peak_energy / total_energy if total_energy > 0 else 0

    def band_ratio(fmin: float, fmax: float) -> float:
        band = (freqs_f >= fmin) & (freqs_f <= fmax)
        return float(np.sum(fft_f[band] ** 2) / total_energy) if total_energy > 0 else 0.0

    low_energy = band_ratio(100, 400)
    mid_energy = band_ratio(400, 2000)
    broad_energy = band_ratio(100, 8000)

    if peak_freq > 2000 and peak_ratio > 0.3:
        return ("glass_break", round(min(0.5 + peak_ratio * 0.5, 0.95), 3))
    if peak_freq < 400 and low_energy > 0.4 and peak_ratio > 0.15:
        return ("knock", round(min(0.5 + peak_ratio, 0.9), 3))
    if 600 < peak_freq < 2500 and mid_energy > 0.5 and peak_ratio > 0.2:
        return ("doorbell", round(min(0.5 + peak_ratio * 0.8, 0.9), 3))
    if 500 < peak_freq < 3000 and peak_ratio > 0.25:
        return ("alarm", round(min(0.5 + peak_ratio * 0.5, 0.9), 3))
    if 200 < peak_freq < 3000:
        harmonics = 0
        for h in range(2, 6):
            h_idx = np.argmin(np.abs(freqs_f - peak_freq * h))
            if h_idx < len(fft_f) and fft_f[h_idx] > np.median(fft_f) * 3:
                harmonics += 1
        if harmonics >= 2 and mid_energy > 0.3:
            return ("speech", round(min(0.4 + harmonics * 0.15, 0.9), 3))

    conf = min(0.3 + broad_energy * 0.5, 0.8)
    return ("sound", round(conf, 3))


class YAMNetMic:
    """Microphone capture + audio event detection. Implements PerceptionSource."""

    def __init__(
        self,
        device: int | str | None = None,
        sample_rate: int = 0,
        chunk_duration: float = 0.975,
        energy_threshold: float = 0.001,
        detection_interval: float = 0.25,
        model_path: str = "models/yamnet.onnx",
        class_map_path: str = "models/yamnet_class_map.csv",
    ) -> None:
        self.device = device
        self.target_rate = 16000
        self.device_rate = 0
        self.chunk_duration = chunk_duration
        self.energy_threshold = energy_threshold
        self.detection_interval = detection_interval
        self.model_path = model_path
        self.class_map_path = class_map_path
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
        self._yamnet: Any = None
        self._class_names: dict[int, str] = {}

    def _resolve_model_path(self, relative: str) -> str:
        p = Path(relative)
        if p.exists():
            return str(p)
        project_root = Path(__file__).parent.parent.parent.parent
        return str(project_root / relative)

    async def start(self) -> None:
        self._running = True

        # Load YAMNet model (non-fatal if missing/corrupt)
        model_file = self._resolve_model_path(self.model_path)
        class_map_file = self._resolve_model_path(self.class_map_path)
        result = _load_yamnet(model_file, class_map_file)
        if result is not None:
            self._yamnet, self._class_names = result
            logger.info("YAMNet enabled — %d mapped classes", len(_YAMNET_MAP))
        else:
            logger.warning("YAMNet unavailable — falling back to FFT classifier")

        try:
            import sounddevice as sd

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
            # YAMNet if available, else FFT
            if self._yamnet is not None:
                label, conf = _classify_yamnet(audio, self._yamnet, self._class_names)
            else:
                label, conf = _classify_fft(audio, self.target_rate)
            sound = Detection(label=label, confidence=conf)
            self._sound_log.append({
                "label": label,
                "confidence": conf,
                "timestamp": now,
            })
            logger.info(
                "[sound] %s (%.0f%%) rms=%.5f ratio=%.1f",
                label, conf * 100, rms_val, ratio,
            )
            return PerceptionSnapshot(
                detections=[], sounds=[sound], source="mic", timestamp=now,
            )

        return PerceptionSnapshot(
            detections=[], sounds=[], source="mic", timestamp=time.time(),
        )
