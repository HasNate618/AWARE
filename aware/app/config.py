from __future__ import annotations

import glob
import logging
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def detect_camera() -> str:
    """Find the first UVC camera device. Falls back to /dev/video0."""
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.splitlines():
            if "CAMERA" in line.upper() or "UVC" in line.upper():
                # Next non-empty indented line is the device
                idx = result.stdout.splitlines().index(line)
                for subline in result.stdout.splitlines()[idx + 1:]:
                    stripped = subline.strip()
                    if stripped.startswith("/dev/video"):
                        return stripped
    except Exception:
        pass
    # Fallback: try /dev/video0 first, then any video device
    for dev in sorted(glob.glob("/dev/video*")):
        return dev
    return "/dev/video0"


class Settings(BaseSettings):
    camera_device: str = ""  # empty = auto-detect UVC camera
    mic_device: str = ""  # empty = auto-detect USB mic (alsa card)
    model_path: str = "models/yolov8n.onnx"
    mcu_serial_port: str = "/dev/ttyACM0"
    mcu_baud_rate: int = 115200
    db_path: str = "aware.db"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    llm_model_path: str = "models/minicpm5-1b-q8.gguf"
    llm_server_url: str = ""  # e.g. "http://127.0.0.1:8080" for llama.cpp server
    llm_ctx_size: int = 2048
    llm_timeout: float = 90.0
    rules_tick_ms: int = 500
    dashboard_dir: str = "dashboard"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {"env_prefix": "AWARE_", "env_file": ".env"}


def get_settings() -> Settings:
    s = Settings()
    if not s.camera_device:
        s.camera_device = detect_camera()
    return s


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_db_path(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return Path(s.db_path)
