from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import streamlit as st


def _read_setting(name: str, default: str = "") -> str:
    """Read a setting from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, None)
    except Exception:
        value = None

    if value is None:
        value = os.getenv(name, default)

    return str(value).strip()


def _read_float(name: str, default: float) -> float:
    raw = _read_setting(name, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    database_url: str
    openai_api_key: str
    text_model: str
    transcription_model: str
    tts_model: str
    moderation_model: str
    admin_email: str
    admin_password: str
    payment_link: str
    free_trial_minutes: float
    free_trial_days: int
    text_input_usd_per_million: float
    text_output_usd_per_million: float
    transcription_usd_per_minute: float
    tts_usd_per_minute: float


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig(
        app_name=_read_setting("APP_NAME", "SpeakMate Business"),
        database_url=_read_setting("DATABASE_URL"),
        openai_api_key=_read_setting("OPENAI_API_KEY"),
        text_model=_read_setting("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        transcription_model=_read_setting(
            "OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"
        ),
        tts_model=_read_setting("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        moderation_model=_read_setting(
            "OPENAI_MODERATION_MODEL", "omni-moderation-latest"
        ),
        admin_email=_read_setting("ADMIN_EMAIL", "admin@example.com").lower(),
        admin_password=_read_setting("ADMIN_PASSWORD", "ChangeMe123!"),
        payment_link=_read_setting("PAYMENT_LINK", ""),
        free_trial_minutes=_read_float("FREE_TRIAL_MINUTES", 10.0),
        free_trial_days=int(_read_float("FREE_TRIAL_DAYS", 14)),
        # Internal estimates only. Update these values in Streamlit Secrets.
        text_input_usd_per_million=_read_float(
            "TEXT_INPUT_USD_PER_MILLION", 0.15
        ),
        text_output_usd_per_million=_read_float(
            "TEXT_OUTPUT_USD_PER_MILLION", 0.60
        ),
        transcription_usd_per_minute=_read_float(
            "TRANSCRIPTION_USD_PER_MINUTE", 0.003
        ),
        tts_usd_per_minute=_read_float("TTS_USD_PER_MINUTE", 0.015),
    )
