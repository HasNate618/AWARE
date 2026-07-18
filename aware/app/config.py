from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class Settings(BaseSettings):
    camera_device: str = "/dev/video0"
    mcu_serial_port: str = "/dev/ttyACM0"
    mcu_baud_rate: int = 115200
    db_path: str = "aware.db"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    llm_model_path: str = "models/minicpm5-1b-q8.gguf"
    llm_ctx_size: int = 2048
    llm_timeout: float = 10.0
    rules_tick_ms: int = 500
    dashboard_dir: str = "dashboard"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {"env_prefix": "AWARE_", "env_file": ".env"}


def get_settings() -> Settings:
    return Settings()


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_db_path(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return Path(s.db_path)
