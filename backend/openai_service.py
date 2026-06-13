from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from backend.config import AppConfig, get_config


@dataclass
class TutorReply:
    reply: str
    correction: str
    explanation: str
    vocabulary: list[dict[str, str]]
    input_tokens: int
    output_tokens: int


class ContentBlockedError(ValueError):
    pass


def get_client() -> OpenAI:
    config = get_config()
    if not config.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing from .streamlit/secrets.toml or the server environment."
        )
    return OpenAI(api_key=config.openai_api_key)


def moderate_text(text: str, config: AppConfig | None = None) -> None:
    clean_text = text.strip()
    if not clean_text:
        return

    config = config or get_config()
    response = get_client().moderations.create(
        model=config.moderation_model,
        input=clean_text,
    )
    if response.results and response.results[0].flagged:
        raise ContentBlockedError(
            "This message cannot be processed because it was flagged by the safety filter."
        )


def transcribe_audio(audio_bytes: bytes, config: AppConfig | None = None) -> str:
    config = config or get_config()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "learner_recording.wav"

    result = get_client().audio.transcriptions.create(
        model=config.transcription_model,
        file=audio_file,
        language="en",
        prompt=(
            "This is an English conversation-practice recording. "
            "Transcribe the learner's intended English accurately. "
            "Do not translate it into another language."
        ),
    )
    return result.text.strip()


def _clean_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def generate_tutor_reply(
    messages: list[dict[str, str]],
    learner_name: str,
    level: str,
    topic: str,
    correction_mode: str,
    partner_style: str,
    config: AppConfig | None = None,
) -> TutorReply:
    config = config or get_config()

    instructions = f"""
You are SpeakMate, a patient one-to-one English conversation partner and tutor.

Learner name: {learner_name}
Learner level: {level}
Conversation topic: {topic}
Correction mode: {correction_mode}
Partner style: {partner_style}

Rules:
1. Speak only in English.
2. Continue the same conversation naturally.
3. Keep the conversational reply between 2 and 4 concise sentences, normally under 75 words.
4. End the reply with exactly one relevant question.
5. Let the learner do most of the speaking.
6. Do not give long lectures or repetitive praise.
7. For a role-play topic, remain in character.
8. Never claim to evaluate pronunciation from a written transcript.
9. If correction is appropriate, provide a natural corrected version of the learner's latest sentence.
10. Give zero to two useful vocabulary items.

Return valid JSON only:
{{
  "reply": "natural conversational reply",
  "correction": "corrected sentence or empty string",
  "explanation": "brief explanation or empty string",
  "vocabulary": [
    {{"word": "word or phrase", "meaning": "simple meaning", "example": "short example"}}
  ]
}}
""".strip()

    response = get_client().responses.create(
        model=config.text_model,
        instructions=instructions,
        input=messages[-18:],
        max_output_tokens=450,
    )

    raw_text = response.output_text.strip()
    try:
        data = _clean_json(raw_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        data = {
            "reply": raw_text,
            "correction": "",
            "explanation": "",
            "vocabulary": [],
        }

    vocabulary = data.get("vocabulary", [])
    if not isinstance(vocabulary, list):
        vocabulary = []

    cleaned_vocabulary: list[dict[str, str]] = []
    for item in vocabulary[:2]:
        if isinstance(item, dict):
            cleaned_vocabulary.append(
                {
                    "word": str(item.get("word", "")).strip(),
                    "meaning": str(item.get("meaning", "")).strip(),
                    "example": str(item.get("example", "")).strip(),
                }
            )

    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

    return TutorReply(
        reply=str(data.get("reply", raw_text)).strip() or raw_text,
        correction=str(data.get("correction", "")).strip(),
        explanation=str(data.get("explanation", "")).strip(),
        vocabulary=cleaned_vocabulary,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def synthesize_speech(
    text: str,
    voice: str,
    speed: float,
    accent: str,
    config: AppConfig | None = None,
) -> bytes:
    config = config or get_config()
    instructions = (
        f"Speak clearly in a natural {accent} English accent. "
        f"Use a patient, friendly teaching tone. Target speaking speed: {speed:.2f}x."
    )

    result = get_client().audio.speech.create(
        model=config.tts_model,
        voice=voice,
        input=text[:4000],
        instructions=instructions,
        response_format="mp3",
        speed=speed,
    )

    if hasattr(result, "read"):
        return result.read()
    if hasattr(result, "content"):
        return result.content
    return bytes(result)
