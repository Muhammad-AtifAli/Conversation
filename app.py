from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import streamlit as st

from backend import auth, database, openai_service, usage
from backend.config import get_config


# -----------------------------------------------------------------------------
# Page and database setup
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="SpeakMate Business",
    page_icon="🗣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = get_config()

try:
    database.init_database()
except Exception as database_error:
    st.error("The cloud database could not be connected or initialized.")
    st.code(str(database_error))
    st.info(
        "Add DATABASE_URL to Streamlit Community Cloud Secrets. "
        "Use the Supabase PostgreSQL session-pooler connection string, not a local SQLite path."
    )
    st.stop()

st.markdown(
    """
    <style>
        .block-container {padding-top: 1.4rem; padding-bottom: 3rem;}
        .brand-title {font-size: 2.35rem; font-weight: 800; margin-bottom: .1rem;}
        .brand-subtitle {color: #667085; margin-bottom: 1.2rem;}
        .plan-card {
            border: 1px solid rgba(128,128,128,.25);
            border-radius: 14px;
            padding: 1rem;
            min-height: 175px;
        }
        .status-good {color: #137333; font-weight: 700;}
        .status-bad {color: #b3261e; font-weight: 700;}
        .small-muted {font-size: .88rem; color: #667085;}
        div[data-testid="stMetric"] {
            border: 1px solid rgba(128,128,128,.20);
            border-radius: 12px;
            padding: .8rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

LEVELS = [
    "A1 - Beginner",
    "A2 - Elementary",
    "B1 - Intermediate",
    "B2 - Upper-intermediate",
    "C1 - Advanced",
    "C2 - Proficient",
]

TOPICS = [
    "Free conversation",
    "Daily routine",
    "Job interview",
    "Travel and airport",
    "Shopping",
    "Restaurant",
    "School and teaching",
    "Academic discussion",
    "IELTS-style speaking",
    "Public speaking",
    "Custom topic",
]

CORRECTION_MODES = [
    "Correct only major mistakes",
    "Correct every important mistake",
    "Conversation only",
]

PARTNER_STYLES = [
    "Friendly and patient",
    "Professional",
    "Energetic",
    "Calm and thoughtful",
]


def initialise_session_state() -> None:
    defaults: dict[str, Any] = {
        "authenticated": False,
        "user": None,
        "page": "Practice",
        "current_session_id": None,
        "practice_messages": [],
        "last_audio_hash": "",
        "flash_message": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialise_session_state()


def logout() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def set_logged_in_user(user: dict[str, Any]) -> None:
    safe_user = dict(user)
    safe_user.pop("password_hash", None)
    st.session_state.authenticated = True
    st.session_state.user = safe_user
    st.session_state.page = "Practice"
    st.session_state.current_session_id = None
    st.session_state.practice_messages = []
    st.session_state.last_audio_hash = ""


def show_flash_message() -> None:
    if st.session_state.flash_message:
        st.success(st.session_state.flash_message)
        st.session_state.flash_message = ""


def format_datetime(value: str | datetime | None) -> str:
    if not value:
        return "Not available"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return str(value)


def render_authentication() -> None:
    st.markdown('<div class="brand-title">🗣️ SpeakMate</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="brand-subtitle">One-to-one AI English speaking practice with customer accounts, subscriptions, usage control, and progress tracking.</div>',
        unsafe_allow_html=True,
    )

    left, centre, right = st.columns([1, 1.2, 1])
    with centre:
        sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])

        with sign_in_tab:
            with st.form("login_form"):
                email = st.text_input("Email address")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button(
                    "Sign in", type="primary", use_container_width=True
                )

            if submitted:
                success, message, user = auth.authenticate_user(email, password)
                if success and user:
                    set_logged_in_user(user)
                    st.rerun()
                else:
                    st.error(message)

        with register_tab:
            with st.form("registration_form"):
                name = st.text_input("Full name")
                email = st.text_input("Email address", key="register_email")
                password = st.text_input(
                    "Password",
                    type="password",
                    key="register_password",
                    help="Use at least 8 characters, including a letter and a number.",
                )
                confirm = st.text_input(
                    "Confirm password",
                    type="password",
                )
                accepted = st.checkbox(
                    "I agree that the tutor and spoken voice are AI-generated."
                )
                submitted = st.form_submit_button(
                    "Create free account", type="primary", use_container_width=True
                )

            if submitted:
                if not accepted:
                    st.error("You must accept the AI disclosure before registering.")
                else:
                    success, message, user = auth.register_user(
                        name, email, password, confirm
                    )
                    if success and user:
                        set_logged_in_user(user)
                        st.session_state.flash_message = (
                            f"Account created. Your free trial includes "
                            f"{config.free_trial_minutes:g} practice minutes."
                        )
                        st.rerun()
                    else:
                        st.error(message)

        st.caption(
            "The OpenAI API key is kept on the server. Customers never enter or see it."
        )


def render_sidebar(user: dict[str, Any]) -> None:
    with st.sidebar:
        st.markdown("## 🗣️ SpeakMate")
        st.write(f"**{user['name']}**")
        st.caption(user["email"])

        subscription = database.get_active_subscription(int(user["id"]))
        if subscription:
            st.metric(
                "Remaining minutes",
                f"{float(subscription['remaining_minutes']):.1f}",
            )
            st.caption(
                f"{subscription['plan_name']} · expires "
                f"{format_datetime(subscription['expires_at'])}"
            )
        else:
            st.error("No active subscription")

        pages = ["Practice", "Progress", "Account"]
        if user["role"] == "admin":
            pages.append("Admin")

        current_index = pages.index(st.session_state.page) if st.session_state.page in pages else 0
        selected_page = st.radio(
            "Navigation",
            pages,
            index=current_index,
            label_visibility="collapsed",
        )
        if selected_page != st.session_state.page:
            st.session_state.page = selected_page
            st.rerun()

        st.divider()
        st.caption("The spoken tutor voice is generated by AI, not a human.")
        if st.button("Sign out", use_container_width=True):
            logout()


def create_new_practice_session(
    user: dict[str, Any],
    topic: str,
    level: str,
) -> None:
    old_session_id = st.session_state.current_session_id
    if old_session_id:
        database.finish_practice_session(int(old_session_id), int(user["id"]))

    session_id = database.create_practice_session(
        int(user["id"]),
        topic,
        level,
    )
    greeting = (
        f"Hello, {user['name']}! We will practise {topic.lower()} at your "
        f"{level.split(' - ')[0]} level. What would you like to say first?"
    )
    database.save_message(session_id, "assistant", greeting)

    st.session_state.current_session_id = session_id
    st.session_state.practice_messages = [
        {
            "role": "assistant",
            "content": greeting,
            "correction": "",
            "explanation": "",
            "vocabulary": [],
            "audio": None,
        }
    ]
    st.session_state.last_audio_hash = ""


def display_conversation() -> None:
    for message in st.session_state.practice_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            if message["role"] == "assistant":
                if message.get("audio"):
                    st.audio(message["audio"], format="audio/mp3")

                correction = message.get("correction", "")
                explanation = message.get("explanation", "")
                vocabulary = message.get("vocabulary", [])

                if correction or explanation or vocabulary:
                    with st.expander("Learning feedback"):
                        if correction:
                            st.markdown(f"**A more natural version:** {correction}")
                        if explanation:
                            st.markdown(f"**Why:** {explanation}")
                        if vocabulary:
                            st.markdown("**Useful vocabulary:**")
                            for item in vocabulary:
                                if item.get("word"):
                                    st.markdown(
                                        f"- **{item['word']}**: {item.get('meaning', '')}  \n"
                                        f"  *Example:* {item.get('example', '')}"
                                    )


def history_for_openai() -> list[dict[str, str]]:
    return [
        {"role": message["role"], "content": message["content"]}
        for message in st.session_state.practice_messages
    ]


def process_practice_turn(
    user: dict[str, Any],
    learner_text: str,
    audio_minutes: float,
    level: str,
    topic: str,
    correction_mode: str,
    partner_style: str,
    spoken_reply: bool,
    voice: str,
    speed: float,
    accent: str,
    used_transcription: bool,
) -> None:
    learner_text = learner_text.strip()
    if not learner_text:
        raise ValueError("No English speech or text was detected.")
    if len(learner_text) > 1500:
        raise ValueError("Please keep each message under 1,500 characters.")

    user_id = int(user["id"])
    session_id = st.session_state.current_session_id
    if not session_id:
        raise ValueError("Start a conversation before sending a message.")

    subscription = database.get_active_subscription(user_id)
    if not subscription:
        raise ValueError("Your subscription is inactive or expired.")

    reserve = usage.reserve_minutes(
        learner_text=learner_text,
        audio_minutes=audio_minutes,
        spoken_reply_enabled=spoken_reply,
    )
    if float(subscription["remaining_minutes"]) + 1e-9 < reserve:
        raise ValueError(
            f"You need about {reserve:.2f} remaining minutes for this turn. "
            "Please renew or upgrade your plan."
        )

    openai_service.moderate_text(learner_text, config)

    pending_history = history_for_openai() + [
        {"role": "user", "content": learner_text}
    ]
    tutor_reply = openai_service.generate_tutor_reply(
        messages=pending_history,
        learner_name=user["name"],
        level=level,
        topic=topic,
        correction_mode=correction_mode,
        partner_style=partner_style,
        config=config,
    )
    openai_service.moderate_text(tutor_reply.reply, config)

    reply_audio = None
    assistant_audio_minutes = 0.0
    if spoken_reply:
        reply_audio = openai_service.synthesize_speech(
            tutor_reply.reply,
            voice=voice,
            speed=speed,
            accent=accent,
            config=config,
        )
        assistant_audio_minutes = usage.estimated_spoken_minutes(tutor_reply.reply)

    billed_minutes = usage.calculate_billed_minutes(
        learner_text=learner_text,
        assistant_text=tutor_reply.reply,
        audio_minutes=audio_minutes,
        spoken_reply_enabled=spoken_reply,
    )

    # Reservation is deliberately a little higher than a normal reply. This check
    # is retained in case an administrator changes the prompt or limits later.
    current_subscription = database.get_active_subscription(user_id)
    if not current_subscription or float(current_subscription["remaining_minutes"]) < billed_minutes:
        raise ValueError("Your remaining balance is too low for this completed turn.")

    database.consume_minutes(user_id, billed_minutes)

    database.save_message(
        int(session_id),
        "user",
        learner_text,
    )
    database.save_message(
        int(session_id),
        "assistant",
        tutor_reply.reply,
        correction=tutor_reply.correction,
        explanation=tutor_reply.explanation,
        vocabulary=tutor_reply.vocabulary,
    )

    correction_count = 1 if tutor_reply.correction else 0
    database.update_session_statistics(
        int(session_id),
        duration_minutes=billed_minutes,
        learner_words=len(learner_text.split()),
        corrections_count=correction_count,
    )

    if used_transcription:
        database.log_usage(
            user_id=user_id,
            session_id=int(session_id),
            event_type="speech_to_text",
            model=config.transcription_model,
            input_units=audio_minutes,
            estimated_cost_usd=usage.transcription_cost(config, audio_minutes),
        )

    database.log_usage(
        user_id=user_id,
        session_id=int(session_id),
        event_type="text_response",
        model=config.text_model,
        input_units=tutor_reply.input_tokens,
        output_units=tutor_reply.output_tokens,
        estimated_cost_usd=usage.text_cost(
            config,
            tutor_reply.input_tokens,
            tutor_reply.output_tokens,
        ),
    )

    if spoken_reply:
        database.log_usage(
            user_id=user_id,
            session_id=int(session_id),
            event_type="text_to_speech",
            model=config.tts_model,
            output_units=assistant_audio_minutes,
            estimated_cost_usd=usage.tts_cost(config, assistant_audio_minutes),
        )

    database.log_usage(
        user_id=user_id,
        session_id=int(session_id),
        event_type="practice_turn",
        model="internal",
        billed_minutes=billed_minutes,
        metadata={"topic": topic, "level": level},
    )

    st.session_state.practice_messages.extend(
        [
            {"role": "user", "content": learner_text},
            {
                "role": "assistant",
                "content": tutor_reply.reply,
                "correction": tutor_reply.correction,
                "explanation": tutor_reply.explanation,
                "vocabulary": tutor_reply.vocabulary,
                "audio": reply_audio,
            },
        ]
    )


def render_practice_page(user: dict[str, Any]) -> None:
    st.header("English conversation practice")
    show_flash_message()

    subscription = database.get_active_subscription(int(user["id"]))
    if not subscription:
        st.error("Your subscription has expired or is inactive. Open Account to renew it.")
        return

    settings_col, conversation_col = st.columns([1, 2.15], gap="large")

    with settings_col:
        st.subheader("Session settings")
        level = st.selectbox("English level", LEVELS, index=2)
        topic_choice = st.selectbox("Conversation topic", TOPICS)
        custom_topic = ""
        if topic_choice == "Custom topic":
            custom_topic = st.text_input(
                "Custom topic", placeholder="For example: discussing my thesis"
            )
        topic = custom_topic.strip() if topic_choice == "Custom topic" else topic_choice
        topic = topic or "Free conversation"

        correction_mode = st.selectbox("Correction style", CORRECTION_MODES)
        partner_style = st.selectbox("Partner style", PARTNER_STYLES)
        input_mode = st.radio("Input method", ["Voice", "Text"], horizontal=True)
        spoken_reply = st.toggle("Play spoken AI replies", value=True)

        if spoken_reply:
            voice = st.selectbox(
                "AI voice",
                [
                    "marin",
                    "cedar",
                    "coral",
                    "nova",
                    "alloy",
                    "onyx",
                    "sage",
                    "shimmer",
                ],
            )
            accent = st.selectbox("Accent", ["neutral", "British", "American"])
            speed = st.slider("Speaking speed", 0.70, 1.20, 0.90, 0.05)
        else:
            voice = "marin"
            accent = "neutral"
            speed = 1.0

        if st.button("Start new conversation", type="primary", use_container_width=True):
            create_new_practice_session(user, topic, level)
            st.rerun()

        st.info(
            f"Plan: **{subscription['plan_name']}**  \n"
            f"Balance: **{float(subscription['remaining_minutes']):.2f} minutes**"
        )

    with conversation_col:
        if not st.session_state.current_session_id:
            st.info("Choose your settings and press **Start new conversation**.")
            return

        display_conversation()
        st.divider()

        if input_mode == "Voice":
            recording = st.audio_input(
                "Record your English message",
                sample_rate=16_000,
            )
            send_recording = st.button(
                "Send voice message",
                type="primary",
                use_container_width=True,
                disabled=recording is None,
            )

            if send_recording and recording is not None:
                audio_bytes = recording.getvalue()
                audio_hash = hashlib.sha256(audio_bytes).hexdigest()
                if audio_hash == st.session_state.last_audio_hash:
                    st.warning("This recording has already been sent. Record a new message.")
                else:
                    try:
                        audio_minutes = usage.wav_duration_minutes(audio_bytes)
                        pre_subscription = database.get_active_subscription(int(user["id"]))
                        pre_reserve = usage.reserve_minutes(
                            audio_minutes=audio_minutes,
                            spoken_reply_enabled=spoken_reply,
                        )
                        if (
                            not pre_subscription
                            or float(pre_subscription["remaining_minutes"]) < pre_reserve
                        ):
                            raise ValueError(
                                f"You need about {pre_reserve:.2f} remaining minutes "
                                "for this voice turn."
                            )

                        with st.status("Listening and preparing the tutor's reply..."):
                            learner_text = openai_service.transcribe_audio(
                                audio_bytes, config
                            )
                            process_practice_turn(
                                user=user,
                                learner_text=learner_text,
                                audio_minutes=audio_minutes,
                                level=level,
                                topic=topic,
                                correction_mode=correction_mode,
                                partner_style=partner_style,
                                spoken_reply=spoken_reply,
                                voice=voice,
                                speed=speed,
                                accent=accent,
                                used_transcription=True,
                            )
                        st.session_state.last_audio_hash = audio_hash
                        st.rerun()
                    except openai_service.ContentBlockedError as error:
                        st.error(str(error))
                    except Exception as error:
                        st.error(f"The voice message could not be processed: {error}")

        else:
            typed_message = st.chat_input("Write your English message here...")
            if typed_message:
                try:
                    with st.status("Preparing the tutor's reply..."):
                        process_practice_turn(
                            user=user,
                            learner_text=typed_message,
                            audio_minutes=0.0,
                            level=level,
                            topic=topic,
                            correction_mode=correction_mode,
                            partner_style=partner_style,
                            spoken_reply=spoken_reply,
                            voice=voice,
                            speed=speed,
                            accent=accent,
                            used_transcription=False,
                        )
                    st.rerun()
                except openai_service.ContentBlockedError as error:
                    st.error(str(error))
                except Exception as error:
                    st.error(f"The message could not be processed: {error}")

        st.caption(
            "The app stores the transcript and learning feedback for progress tracking. "
            "It does not claim to measure pronunciation from transcription alone."
        )


def render_progress_page(user: dict[str, Any]) -> None:
    st.header("Progress dashboard")
    progress = database.get_user_progress(int(user["id"]))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Practice sessions", int(progress["sessions"]))
    col2.metric("Practice minutes", f"{float(progress['minutes']):.1f}")
    col3.metric("Words practised", int(progress["words"]))
    col4.metric("Corrections received", int(progress["corrections"]))

    st.subheader("Recent sessions")
    sessions = database.get_recent_sessions(int(user["id"]))
    if sessions:
        display_rows = []
        for item in sessions:
            display_rows.append(
                {
                    "Date": format_datetime(item["started_at"]),
                    "Topic": item["topic"],
                    "Level": item["level"],
                    "Minutes": round(float(item["duration_minutes"]), 2),
                    "Words": int(item["learner_words"]),
                    "Corrections": int(item["corrections_count"]),
                    "Status": item["status"],
                }
            )
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No practice sessions have been recorded yet.")

    transcript = []
    for message in st.session_state.practice_messages:
        speaker = "Learner" if message["role"] == "user" else "SpeakMate"
        transcript.append(f"{speaker}: {message['content']}")
        if message.get("correction"):
            transcript.append(f"Correction: {message['correction']}")
        transcript.append("")

    if transcript:
        st.download_button(
            "Download current conversation transcript",
            data="\n".join(transcript),
            file_name="speakmate_conversation.txt",
            mime="text/plain",
        )


def render_account_page(user: dict[str, Any]) -> None:
    st.header("Account and subscription")
    subscription = database.get_active_subscription(int(user["id"]))

    profile_col, subscription_col = st.columns(2)
    with profile_col:
        st.subheader("Profile")
        st.write(f"**Name:** {user['name']}")
        st.write(f"**Email:** {user['email']}")
        st.write(f"**Account type:** {user['role'].title()}")

    with subscription_col:
        st.subheader("Current subscription")
        if subscription:
            st.write(f"**Plan:** {subscription['plan_name']}")
            st.write(
                f"**Remaining:** {float(subscription['remaining_minutes']):.2f} minutes"
            )
            st.write(f"**Expires:** {format_datetime(subscription['expires_at'])}")
        else:
            st.error("No active subscription")

    st.subheader("Available plans")
    plans = database.get_plans()
    columns = st.columns(len(plans))
    for column, plan in zip(columns, plans):
        with column:
            st.markdown('<div class="plan-card">', unsafe_allow_html=True)
            st.markdown(f"### {plan['name']}")
            st.write(f"**{float(plan['monthly_minutes']):g} minutes**")
            if float(plan["price_usd"]) == 0:
                st.write("Free trial")
            else:
                st.write(f"${float(plan['price_usd']):.2f} per billing period")
            st.markdown("</div>", unsafe_allow_html=True)

    if config.payment_link:
        st.link_button("Purchase or renew a plan", config.payment_link)
    else:
        st.info(
            "Online payment is not connected yet. An administrator can activate a paid "
            "plan from the Admin dashboard. Add PAYMENT_LINK in Streamlit secrets when "
            "your checkout page is ready."
        )

    st.divider()
    st.subheader("Privacy controls")
    delete_confirm = st.checkbox(
        "I understand that deleting my history permanently removes my saved practice sessions."
    )
    if st.button(
        "Delete my conversation history",
        disabled=not delete_confirm,
    ):
        database.delete_user_conversation_history(int(user["id"]))
        st.session_state.current_session_id = None
        st.session_state.practice_messages = []
        st.success("Your saved conversation history has been deleted.")


def render_admin_page(user: dict[str, Any]) -> None:
    if user["role"] != "admin":
        st.error("Administrator access is required.")
        return

    st.header("Administrator dashboard")

    if config.admin_password == "ChangeMe123!":
        st.warning(
            "The default administrator password is still configured. Change ADMIN_PASSWORD "
            "in Streamlit Community Cloud Secrets, then update the existing administrator "
            "password record before public deployment."
        )

    summary = database.get_admin_usage_summary()
    users = database.get_admin_users()
    customers = [item for item in users if item["role"] == "customer"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Registered customers", len(customers))
    col2.metric("Customers with usage", int(summary["active_users"]))
    col3.metric("Billed practice minutes", f"{float(summary['billed_minutes']):.1f}")
    col4.metric(
        "Estimated OpenAI cost",
        f"${float(summary['estimated_cost_usd']):.4f}",
    )

    st.subheader("Customer accounts")
    table_rows = []
    for item in customers:
        table_rows.append(
            {
                "ID": item["id"],
                "Name": item["name"],
                "Email": item["email"],
                "Status": item["status"],
                "Plan": item["plan_name"] or "None",
                "Remaining": round(float(item["remaining_minutes"] or 0), 2),
                "Expires": format_datetime(item["expires_at"]),
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)

    if customers:
        customer_by_id = {int(item["id"]): item for item in customers}
        selected_id = st.selectbox(
            "Select a customer to manage",
            options=list(customer_by_id.keys()),
            format_func=lambda value: (
                f"{customer_by_id[value]['name']} · {customer_by_id[value]['email']}"
            ),
        )
        selected_customer = customer_by_id[int(selected_id)]

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            st.markdown("#### Assign or renew plan")
            plan_names = [plan["name"] for plan in database.get_plans()]
            with st.form("assign_plan_form"):
                plan_name = st.selectbox("Plan", plan_names)
                duration_days = st.number_input(
                    "Subscription days", min_value=1, max_value=365, value=30
                )
                custom_minutes_enabled = st.checkbox("Use custom minute allocation")
                custom_minutes = st.number_input(
                    "Custom minutes",
                    min_value=0.0,
                    value=100.0,
                    step=10.0,
                    disabled=not custom_minutes_enabled,
                )
                submitted = st.form_submit_button(
                    "Activate plan", type="primary", use_container_width=True
                )
            if submitted:
                database.assign_plan(
                    int(selected_id),
                    plan_name,
                    int(duration_days),
                    float(custom_minutes) if custom_minutes_enabled else None,
                )
                st.success("The subscription has been activated.")
                st.rerun()

        with action_col2:
            st.markdown("#### Balance and account status")
            with st.form("add_minutes_form"):
                extra_minutes = st.number_input(
                    "Add extra minutes", min_value=1.0, value=10.0, step=5.0
                )
                add_submitted = st.form_submit_button(
                    "Add minutes", use_container_width=True
                )
            if add_submitted:
                database.add_minutes(int(selected_id), float(extra_minutes))
                st.success("Minutes added successfully.")
                st.rerun()

            target_status = (
                "suspended" if selected_customer["status"] == "active" else "active"
            )
            label = (
                "Suspend customer"
                if target_status == "suspended"
                else "Reactivate customer"
            )
            if st.button(label, use_container_width=True):
                database.set_user_status(int(selected_id), target_status)
                st.success(f"Customer status changed to {target_status}.")
                st.rerun()

    st.subheader("Daily usage cost estimates")
    daily_costs = database.get_admin_daily_costs()
    if daily_costs:
        st.dataframe(daily_costs, use_container_width=True, hide_index=True)
        chart_rows = [
            {
                "date": item["date"],
                "estimated_cost_usd": float(item["estimated_cost_usd"] or 0),
            }
            for item in reversed(daily_costs)
        ]
        st.line_chart(
            chart_rows,
            x="date",
            y="estimated_cost_usd",
            y_label="Estimated USD",
        )
    else:
        st.info("No API usage has been logged yet.")

    st.caption(
        "Cost values are estimates based on rates configured in Streamlit secrets. "
        "Use your OpenAI billing dashboard as the final accounting source."
    )


# -----------------------------------------------------------------------------
# Application router
# -----------------------------------------------------------------------------
if not st.session_state.authenticated or not st.session_state.user:
    render_authentication()
else:
    current_user = database.get_user_by_id(int(st.session_state.user["id"]))
    if not current_user or current_user["status"] != "active":
        st.error("This account is unavailable or suspended.")
        if st.button("Return to sign in"):
            logout()
    else:
        current_user.pop("password_hash", None)
        st.session_state.user = current_user
        render_sidebar(current_user)

        if st.session_state.page == "Practice":
            render_practice_page(current_user)
        elif st.session_state.page == "Progress":
            render_progress_page(current_user)
        elif st.session_state.page == "Account":
            render_account_page(current_user)
        elif st.session_state.page == "Admin":
            render_admin_page(current_user)
