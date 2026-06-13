from __future__ import annotations

import io
import wave

from backend.config import AppConfig


def wav_duration_minutes(audio_bytes: bytes, sample_rate_fallback: int = 16_000) -> float:
    if not audio_bytes:
        return 0.0

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            if rate <= 0:
                return 0.0
            return max(0.0, frames / rate / 60.0)
    except (wave.Error, EOFError):
        # Approximate 16-bit mono PCM when a browser adds an unexpected wrapper.
        return max(0.0, len(audio_bytes) / (sample_rate_fallback * 2 * 60))


def estimated_spoken_minutes(text: str, words_per_minute: float = 130.0) -> float:
    words = len(text.split())
    if words == 0:
        return 0.0
    return words / words_per_minute


def reserve_minutes(
    learner_text: str = "",
    audio_minutes: float = 0.0,
    spoken_reply_enabled: bool = True,
) -> float:
    learner_minutes = audio_minutes or estimated_spoken_minutes(
        learner_text, words_per_minute=120.0
    )
    reply_reserve = 0.65 if spoken_reply_enabled else 0.15
    return round(max(0.25, learner_minutes + reply_reserve), 3)


def calculate_billed_minutes(
    learner_text: str,
    assistant_text: str,
    audio_minutes: float,
    spoken_reply_enabled: bool,
) -> float:
    learner_minutes = audio_minutes or estimated_spoken_minutes(
        learner_text, words_per_minute=120.0
    )
    assistant_minutes = (
        estimated_spoken_minutes(assistant_text, words_per_minute=130.0)
        if spoken_reply_enabled
        else 0.0
    )
    return round(max(0.20, learner_minutes + assistant_minutes), 3)


def text_cost(
    config: AppConfig,
    input_tokens: int,
    output_tokens: int,
) -> float:
    return (
        input_tokens / 1_000_000 * config.text_input_usd_per_million
        + output_tokens / 1_000_000 * config.text_output_usd_per_million
    )


def transcription_cost(config: AppConfig, minutes: float) -> float:
    return max(0.0, minutes) * config.transcription_usd_per_minute


def tts_cost(config: AppConfig, minutes: float) -> float:
    return max(0.0, minutes) * config.tts_usd_per_minute
