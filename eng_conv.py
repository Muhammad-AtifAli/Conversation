import hashlib
import io
import json
import os
import re

import streamlit as st
from openai import OpenAI


# --------------------------------------------------
# PAGE SETTINGS
# --------------------------------------------------
st.set_page_config(
    page_title="English Conversation Partner",
    page_icon="🗣️",
    layout="wide",
)

st.title("🗣️ English Conversation Partner")
st.caption(
    "Practise English through text or voice. The app replies, speaks, "
    "corrects mistakes, and suggests useful vocabulary."
)


# --------------------------------------------------
# CONSTANTS
# --------------------------------------------------
LEVELS = {
    "A1 - Beginner": "Use very short sentences and very common words.",
    "A2 - Elementary": "Use simple everyday English.",
    "B1 - Intermediate": "Use natural everyday English at an intermediate level.",
    "B2 - Upper-intermediate": (
        "Use fluent English and introduce some advanced phrases."
    ),
    "C1 - Advanced": "Use sophisticated but clear and natural English.",
}

TOPICS = [
    "Free conversation",
    "Daily routine",
    "Job interview",
    "Travel and airport",
    "Shopping",
    "Restaurant",
    "School and teaching",
    "Academic discussion",
    "Public speaking",
    "Custom topic",
]

CORRECTION_MODES = {
    "Correct major mistakes": (
        "Correct only errors that affect grammar, meaning, or naturalness."
    ),
    "Correct every important mistake": (
        "Correct grammar, vocabulary, and unnatural sentence structure "
        "after every turn."
    ),
    "Conversation only": (
        "Do not correct the learner unless the learner directly asks "
        "for correction."
    ),
}


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------
def initialise_session():
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Hello! I am your English conversation partner. "
                    "Tell me something about yourself."
                ),
                "correction": "",
                "explanation": "",
                "vocabulary": [],
                "audio": None,
            }
        ]

    if "turns" not in st.session_state:
        st.session_state.turns = 0

    if "words" not in st.session_state:
        st.session_state.words = 0

    if "corrections" not in st.session_state:
        st.session_state.corrections = 0

    if "last_audio_hash" not in st.session_state:
        st.session_state.last_audio_hash = ""


initialise_session()


# --------------------------------------------------
# API HELPERS
# --------------------------------------------------
def get_saved_api_key():
    try:
        secret_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        secret_key = ""

    environment_key = os.getenv("OPENAI_API_KEY", "")

    return str(secret_key or environment_key).strip()


def remove_code_fences(text):
    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return text.strip()


def parse_ai_json(text):
    fallback = {
        "reply": text.strip(),
        "correction": "",
        "explanation": "",
        "vocabulary": [],
    }

    try:
        cleaned = remove_code_fences(text)

        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

        data = json.loads(cleaned)

        vocabulary = data.get("vocabulary", [])

        if not isinstance(vocabulary, list):
            vocabulary = []

        return {
            "reply": (
                str(data.get("reply", "")).strip()
                or fallback["reply"]
            ),
            "correction": str(
                data.get("correction", "")
            ).strip(),
            "explanation": str(
                data.get("explanation", "")
            ).strip(),
            "vocabulary": vocabulary[:3],
        }

    except (json.JSONDecodeError, TypeError, ValueError):
        return fallback


def create_conversation_reply(
    client,
    model,
    learner_name,
    level,
    topic,
    custom_topic,
    correction_mode,
):
    if topic == "Custom topic":
        selected_topic = custom_topic.strip()
    else:
        selected_topic = topic

    selected_topic = selected_topic or "Free conversation"

    instructions = f"""
You are a friendly one-to-one English conversation partner and tutor.

Learner name: {learner_name or "Learner"}
Learner level: {level}
Level instruction: {LEVELS[level]}
Conversation topic: {selected_topic}
Correction instruction: {CORRECTION_MODES[correction_mode]}

Rules:

1. Speak only in English.
2. Continue the conversation naturally.
3. Keep your reply between 2 and 5 short sentences.
4. Ask exactly one relevant question at the end.
5. Let the learner speak more than you.
6. Do not give a long lecture.
7. For role-play topics, stay in character.
8. Never claim that you can judge pronunciation from written transcription.
9. If correction is needed, provide a natural corrected version of the learner's sentence.
10. Give zero to two useful vocabulary items.

Return valid JSON only in this exact structure:

{{
    "reply": "Your conversational reply",
    "correction": "Corrected learner sentence, or an empty string",
    "explanation": "A short explanation, or an empty string",
    "vocabulary": [
        {{
            "word": "useful word or phrase",
            "meaning": "simple meaning",
            "example": "short example sentence"
        }}
    ]
}}
""".strip()

    history = []

    for message in st.session_state.messages[-16:]:
        history.append(
            {
                "role": message["role"],
                "content": message["content"],
            }
        )

    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=history,
        max_output_tokens=500,
    )

    return parse_ai_json(response.output_text)


def convert_speech_to_text(
    client,
    audio_bytes,
    transcription_model,
):
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "recording.wav"

    transcription = client.audio.transcriptions.create(
        model=transcription_model,
        file=audio_file,
        language="en",
        prompt=(
            "This is English conversation practice. "
            "Transcribe the learner's English accurately "
            "and do not translate it."
        ),
    )

    return transcription.text.strip()


def convert_text_to_speech(
    client,
    text,
    voice,
    speed,
):
    speech = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text[:4000],
        instructions=(
            "Speak clearly, warmly, and naturally for an "
            "English learner. Use a neutral international "
            "English accent."
        ),
        response_format="mp3",
        speed=speed,
    )

    if hasattr(speech, "read"):
        return speech.read()

    if hasattr(speech, "content"):
        return speech.content

    return bytes(speech)


def process_learner_message(
    learner_text,
    client,
    conversation_model,
    learner_name,
    level,
    topic,
    custom_topic,
    correction_mode,
    spoken_reply,
    voice,
    speech_speed,
):
    learner_text = learner_text.strip()

    if not learner_text:
        st.warning("Please write or record a message first.")
        return

    st.session_state.messages.append(
        {
            "role": "user",
            "content": learner_text,
        }
    )

    st.session_state.turns += 1
    st.session_state.words += len(learner_text.split())

    result = create_conversation_reply(
        client=client,
        model=conversation_model,
        learner_name=learner_name,
        level=level,
        topic=topic,
        custom_topic=custom_topic,
        correction_mode=correction_mode,
    )

    reply_audio = None

    if spoken_reply and result["reply"]:
        reply_audio = convert_text_to_speech(
            client=client,
            text=result["reply"],
            voice=voice,
            speed=speech_speed,
        )

    if result["correction"]:
        st.session_state.corrections += 1

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["reply"],
            "correction": result["correction"],
            "explanation": result["explanation"],
            "vocabulary": result["vocabulary"],
            "audio": reply_audio,
        }
    )


def make_transcript():
    lines = [
        "English Conversation Practice Transcript",
        "",
    ]

    for message in st.session_state.messages:
        if message["role"] == "user":
            speaker = "Learner"
        else:
            speaker = "Tutor"

        lines.append(
            f"{speaker}: {message['content']}"
        )

        if message["role"] == "assistant":
            if message.get("correction"):
                lines.append(
                    f"Correction: {message['correction']}"
                )

            if message.get("explanation"):
                lines.append(
                    f"Explanation: {message['explanation']}"
                )

        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------
# SIDEBAR SETTINGS
# --------------------------------------------------
with st.sidebar:
    st.header("Settings")

    saved_key = get_saved_api_key()

    typed_key = st.text_input(
        "OpenAI API key",
        type="password",
        help=(
            "Leave it blank when OPENAI_API_KEY is "
            "already stored in .streamlit/secrets.toml."
        ),
    )

    api_key = typed_key.strip() or saved_key

    learner_name = st.text_input(
        "Your name",
        value="Muhammad Atif",
    )

    level = st.selectbox(
        "English level",
        list(LEVELS.keys()),
        index=2,
    )

    topic = st.selectbox(
        "Conversation topic",
        TOPICS,
    )

    custom_topic = ""

    if topic == "Custom topic":
        custom_topic = st.text_input(
            "Write your topic",
            placeholder=(
                "For example: discussing my research"
            ),
        )

    correction_mode = st.selectbox(
        "Correction style",
        list(CORRECTION_MODES.keys()),
    )

    input_mode = st.radio(
        "How will you communicate?",
        ["Voice", "Text"],
        horizontal=True,
    )

    spoken_reply = st.toggle(
        "Play spoken tutor replies",
        value=True,
    )

    if spoken_reply:
        voice = st.selectbox(
            "Tutor voice",
            [
                "marin",
                "cedar",
                "coral",
                "nova",
                "alloy",
                "onyx",
                "sage",
            ],
        )

        speech_speed = st.slider(
            "Tutor speaking speed",
            min_value=0.70,
            max_value=1.20,
            value=0.90,
            step=0.05,
        )

    else:
        voice = "marin"
        speech_speed = 1.0

    with st.expander("Model settings"):
        conversation_model = st.text_input(
            "Conversation model",
            value="gpt-4o-mini",
        )

        transcription_model = st.text_input(
            "Speech transcription model",
            value="gpt-4o-mini-transcribe",
        )

    if st.button(
        "Start a new conversation",
        use_container_width=True,
    ):
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    f"Hello, {learner_name or 'there'}! "
                    "Let us practise English. "
                    "What would you like to talk about first?"
                ),
                "correction": "",
                "explanation": "",
                "vocabulary": [],
                "audio": None,
            }
        ]

        st.session_state.turns = 0
        st.session_state.words = 0
        st.session_state.corrections = 0
        st.session_state.last_audio_hash = ""

        st.rerun()


# --------------------------------------------------
# MAIN DASHBOARD
# --------------------------------------------------
metric_1, metric_2, metric_3 = st.columns(3)

metric_1.metric(
    "Speaking turns",
    st.session_state.turns,
)

metric_2.metric(
    "Words practised",
    st.session_state.words,
)

metric_3.metric(
    "Corrections",
    st.session_state.corrections,
)

if not api_key:
    st.warning(
        "Enter your OpenAI API key in the sidebar. "
        "You may also store it in "
        ".streamlit/secrets.toml."
    )


# --------------------------------------------------
# DISPLAY CHAT
# --------------------------------------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        if message["role"] == "assistant":
            if message.get("audio"):
                st.audio(
                    message["audio"],
                    format="audio/mp3",
                )

            correction = message.get(
                "correction",
                "",
            )

            explanation = message.get(
                "explanation",
                "",
            )

            vocabulary = message.get(
                "vocabulary",
                [],
            )

            if correction or explanation or vocabulary:
                with st.expander(
                    "Learning feedback"
                ):
                    if correction:
                        st.markdown(
                            f"**Better sentence:** "
                            f"{correction}"
                        )

                    if explanation:
                        st.markdown(
                            f"**Explanation:** "
                            f"{explanation}"
                        )

                    if vocabulary:
                        st.markdown(
                            "**Useful vocabulary:**"
                        )

                        for item in vocabulary:
                            if isinstance(item, dict):
                                word = item.get(
                                    "word",
                                    "",
                                )

                                meaning = item.get(
                                    "meaning",
                                    "",
                                )

                                example = item.get(
                                    "example",
                                    "",
                                )

                                if word:
                                    st.markdown(
                                        f"- **{word}**: "
                                        f"{meaning}  \n"
                                        f"  *Example:* "
                                        f"{example}"
                                    )


# --------------------------------------------------
# USER INPUT
# --------------------------------------------------
st.divider()

if input_mode == "Voice":
    st.subheader("Record your English")

    recorded_audio = st.audio_input(
        "Press the microphone, speak in English, "
        "and stop when finished.",
        sample_rate=16000,
    )

    send_voice = st.button(
        "Send voice message",
        type="primary",
        use_container_width=True,
        disabled=(
            recorded_audio is None
            or not api_key
        ),
    )

    if send_voice and recorded_audio is not None:
        try:
            audio_bytes = recorded_audio.getvalue()

            current_hash = hashlib.sha256(
                audio_bytes
            ).hexdigest()

            if (
                current_hash
                == st.session_state.last_audio_hash
            ):
                st.info(
                    "This recording has already been sent. "
                    "Record another message."
                )

            else:
                client = OpenAI(
                    api_key=api_key
                )

                with st.status(
                    "Listening and preparing the reply..."
                ):
                    learner_text = (
                        convert_speech_to_text(
                            client=client,
                            audio_bytes=audio_bytes,
                            transcription_model=(
                                transcription_model.strip()
                            ),
                        )
                    )

                    if not learner_text:
                        raise ValueError(
                            "No English speech was detected."
                        )

                    st.session_state.last_audio_hash = (
                        current_hash
                    )

                    process_learner_message(
                        learner_text=learner_text,
                        client=client,
                        conversation_model=(
                            conversation_model.strip()
                        ),
                        learner_name=learner_name,
                        level=level,
                        topic=topic,
                        custom_topic=custom_topic,
                        correction_mode=correction_mode,
                        spoken_reply=spoken_reply,
                        voice=voice,
                        speech_speed=speech_speed,
                    )

                st.rerun()

        except Exception as error:
            st.error(
                "The voice message could not be "
                f"processed: {error}"
            )

else:
    typed_message = st.chat_input(
        "Write your English message here...",
        disabled=not api_key,
    )

    if typed_message:
        try:
            client = OpenAI(
                api_key=api_key
            )

            with st.status(
                "Preparing the reply..."
            ):
                process_learner_message(
                    learner_text=typed_message,
                    client=client,
                    conversation_model=(
                        conversation_model.strip()
                    ),
                    learner_name=learner_name,
                    level=level,
                    topic=topic,
                    custom_topic=custom_topic,
                    correction_mode=correction_mode,
                    spoken_reply=spoken_reply,
                    voice=voice,
                    speech_speed=speech_speed,
                )

            st.rerun()

        except Exception as error:
            st.error(
                "The message could not be "
                f"processed: {error}"
            )


# --------------------------------------------------
# DOWNLOAD TRANSCRIPT
# --------------------------------------------------
st.divider()

st.download_button(
    "Download conversation transcript",
    data=make_transcript(),
    file_name=(
        "english_conversation_transcript.txt"
    ),
    mime="text/plain",
    use_container_width=True,
)

st.info(
    "This version can correct grammar, vocabulary, "
    "and sentence naturalness. It does not give a "
    "reliable pronunciation score because the AI "
    "receives a speech transcript rather than "
    "detailed phonetic measurements."
)