from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterator

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from backend.config import get_config
from backend.security import hash_password, normalize_email


class DuplicateEmailError(ValueError):
    """Raised when a customer tries to register an existing email address."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def _normalise_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, Decimal):
        return float(value)
    return value


def _normalise_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _normalise_value(value) for key, value in row.items()}


def _normalise_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_normalise_row(row) or {} for row in rows]


@lru_cache(maxsize=1)
def get_pool() -> ConnectionPool:
    config = get_config()
    if not config.database_url:
        raise RuntimeError(
            "DATABASE_URL is missing. Add the Supabase PostgreSQL session-pooler "
            "connection string to Streamlit Community Cloud Secrets."
        )

    return ConnectionPool(
        conninfo=config.database_url,
        min_size=1,
        max_size=5,
        timeout=20,
        kwargs={
            "row_factory": dict_row,
            "connect_timeout": 15,
            "sslmode": "require",
        },
        open=True,
    )


@contextmanager
def transaction() -> Iterator[Connection]:
    with get_pool().connection() as connection:
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise


@lru_cache(maxsize=1)
def init_database() -> None:
    config = get_config()

    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'customer'
                        CHECK(role IN ('customer', 'admin')),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'suspended')),
                    created_at TIMESTAMPTZ NOT NULL,
                    last_login_at TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS plans (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    monthly_minutes DOUBLE PRECISION NOT NULL,
                    price_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                    active BOOLEAN NOT NULL DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    plan_id BIGINT NOT NULL REFERENCES plans(id),
                    started_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    allocated_minutes DOUBLE PRECISION NOT NULL,
                    remaining_minutes DOUBLE PRECISION NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'expired', 'cancelled')),
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );

                CREATE TABLE IF NOT EXISTS practice_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    topic TEXT NOT NULL,
                    level TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    ended_at TIMESTAMPTZ,
                    duration_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
                    learner_words BIGINT NOT NULL DEFAULT 0,
                    corrections_count BIGINT NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open', 'completed'))
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id BIGINT NOT NULL
                        REFERENCES practice_sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    correction TEXT NOT NULL DEFAULT '',
                    explanation TEXT NOT NULL DEFAULT '',
                    vocabulary_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_logs (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    session_id BIGINT REFERENCES practice_sessions(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    billed_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
                    input_units DOUBLE PRECISION NOT NULL DEFAULT 0,
                    output_units DOUBLE PRECISION NOT NULL DEFAULT 0,
                    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_subscriptions_user
                    ON subscriptions(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_sessions_user
                    ON practice_sessions(user_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_user
                    ON usage_logs(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                """
            )

            plans = [
                ("Free Trial", config.free_trial_minutes, 0.0),
                ("Basic", 150.0, 9.0),
                ("Premium", 500.0, 24.0),
                ("School", 2000.0, 79.0),
            ]
            for name, minutes, price in plans:
                cursor.execute(
                    """
                    INSERT INTO plans(name, monthly_minutes, price_usd, active)
                    VALUES (%s, %s, %s, TRUE)
                    ON CONFLICT(name) DO UPDATE SET
                        monthly_minutes = EXCLUDED.monthly_minutes,
                        price_usd = EXCLUDED.price_usd,
                        active = TRUE
                    """,
                    (name, minutes, price),
                )

            cursor.execute(
                "SELECT id FROM users WHERE email = %s",
                (normalize_email(config.admin_email),),
            )
            admin = cursor.fetchone()
            if admin is None:
                cursor.execute(
                    """
                    INSERT INTO users(
                        name, email, password_hash, role, status, created_at
                    )
                    VALUES (%s, %s, %s, 'admin', 'active', %s)
                    """,
                    (
                        "Administrator",
                        normalize_email(config.admin_email),
                        hash_password(config.admin_password),
                        utc_now(),
                    ),
                )


def create_user(name: str, email: str, password_hash: str) -> dict[str, Any]:
    config = get_config()
    now = utc_now()
    expires = now + timedelta(days=config.free_trial_days)

    try:
        with transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users(
                        name, email, password_hash, role, status, created_at
                    )
                    VALUES (%s, %s, %s, 'customer', 'active', %s)
                    RETURNING id
                    """,
                    (name.strip(), normalize_email(email), password_hash, now),
                )
                user_id = int(cursor.fetchone()["id"])

                cursor.execute(
                    """
                    SELECT id, monthly_minutes
                    FROM plans
                    WHERE name = 'Free Trial' AND active = TRUE
                    """
                )
                free_plan = cursor.fetchone()
                if free_plan is None:
                    raise RuntimeError("Free Trial plan is missing.")

                cursor.execute(
                    """
                    INSERT INTO subscriptions(
                        user_id, plan_id, started_at, expires_at,
                        allocated_minutes, remaining_minutes,
                        status, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s)
                    """,
                    (
                        user_id,
                        free_plan["id"],
                        now,
                        expires,
                        free_plan["monthly_minutes"],
                        free_plan["monthly_minutes"],
                        now,
                        now,
                    ),
                )
    except UniqueViolation as exc:
        raise DuplicateEmailError("That email is already registered.") from exc

    user = get_user_by_id(user_id)
    if user is None:
        raise RuntimeError("User creation failed.")
    return user


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE email = %s",
                (normalize_email(email),),
            )
            return _normalise_row(cursor.fetchone())


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return _normalise_row(cursor.fetchone())


def update_last_login(user_id: int) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET last_login_at = %s WHERE id = %s",
                (utc_now(), user_id),
            )


def get_plans() -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM plans WHERE active = TRUE ORDER BY monthly_minutes"
            )
            return _normalise_rows(cursor.fetchall())


def _expire_old_subscriptions(cursor: Any, user_id: int) -> None:
    now = utc_now()
    cursor.execute(
        """
        UPDATE subscriptions
        SET status = 'expired', updated_at = %s
        WHERE user_id = %s AND status = 'active' AND expires_at <= %s
        """,
        (now, user_id, now),
    )


def get_active_subscription(user_id: int) -> dict[str, Any] | None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            _expire_old_subscriptions(cursor, user_id)
            cursor.execute(
                """
                SELECT
                    s.*,
                    p.name AS plan_name,
                    p.price_usd,
                    p.monthly_minutes
                FROM subscriptions s
                JOIN plans p ON p.id = s.plan_id
                WHERE s.user_id = %s AND s.status = 'active'
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            return _normalise_row(cursor.fetchone())


def assign_plan(
    user_id: int,
    plan_name: str,
    duration_days: int = 30,
    minutes_override: float | None = None,
) -> None:
    now = utc_now()
    expires = now + timedelta(days=max(1, duration_days))

    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM plans WHERE name = %s AND active = TRUE",
                (plan_name,),
            )
            plan = cursor.fetchone()
            if plan is None:
                raise ValueError("The selected plan does not exist.")

            allocated = (
                float(minutes_override)
                if minutes_override is not None
                else float(plan["monthly_minutes"])
            )
            if allocated < 0:
                raise ValueError("Minutes cannot be negative.")

            cursor.execute(
                """
                UPDATE subscriptions
                SET status = 'cancelled', updated_at = %s
                WHERE user_id = %s AND status = 'active'
                """,
                (now, user_id),
            )
            cursor.execute(
                """
                INSERT INTO subscriptions(
                    user_id, plan_id, started_at, expires_at,
                    allocated_minutes, remaining_minutes,
                    status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s)
                """,
                (
                    user_id,
                    plan["id"],
                    now,
                    expires,
                    allocated,
                    allocated,
                    now,
                    now,
                ),
            )


def add_minutes(user_id: int, minutes: float) -> None:
    if minutes <= 0:
        raise ValueError("Added minutes must be greater than zero.")

    with transaction() as connection:
        with connection.cursor() as cursor:
            _expire_old_subscriptions(cursor, user_id)
            cursor.execute(
                """
                SELECT id
                FROM subscriptions
                WHERE user_id = %s AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id,),
            )
            subscription = cursor.fetchone()
            if subscription is None:
                raise ValueError("The customer does not have an active subscription.")

            cursor.execute(
                """
                UPDATE subscriptions
                SET remaining_minutes = remaining_minutes + %s,
                    allocated_minutes = allocated_minutes + %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (minutes, minutes, utc_now(), subscription["id"]),
            )


def consume_minutes(user_id: int, minutes: float) -> float:
    amount = max(0.0, round(float(minutes), 3))
    if amount == 0:
        return 0.0

    with transaction() as connection:
        with connection.cursor() as cursor:
            _expire_old_subscriptions(cursor, user_id)
            cursor.execute(
                """
                SELECT id, remaining_minutes
                FROM subscriptions
                WHERE user_id = %s AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id,),
            )
            subscription = cursor.fetchone()
            if subscription is None:
                raise ValueError("No active subscription was found.")

            remaining = float(subscription["remaining_minutes"])
            if remaining + 1e-9 < amount:
                raise ValueError(
                    "Not enough remaining minutes for this conversation turn."
                )

            cursor.execute(
                """
                UPDATE subscriptions
                SET remaining_minutes = remaining_minutes - %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (amount, utc_now(), subscription["id"]),
            )
    return amount


def set_user_status(user_id: int, status: str) -> None:
    if status not in {"active", "suspended"}:
        raise ValueError("Invalid user status.")
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET status = %s WHERE id = %s",
                (status, user_id),
            )


def create_practice_session(user_id: int, topic: str, level: str) -> int:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE practice_sessions
                SET status = 'completed', ended_at = %s
                WHERE user_id = %s AND status = 'open'
                """,
                (utc_now(), user_id),
            )
            cursor.execute(
                """
                INSERT INTO practice_sessions(
                    user_id, topic, level, started_at, status
                )
                VALUES (%s, %s, %s, %s, 'open')
                RETURNING id
                """,
                (user_id, topic, level, utc_now()),
            )
            return int(cursor.fetchone()["id"])


def finish_practice_session(session_id: int, user_id: int) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE practice_sessions
                SET status = 'completed', ended_at = %s
                WHERE id = %s AND user_id = %s
                """,
                (utc_now(), session_id, user_id),
            )


def save_message(
    session_id: int,
    role: str,
    content: str,
    correction: str = "",
    explanation: str = "",
    vocabulary: list[dict[str, str]] | None = None,
) -> int:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messages(
                    session_id, role, content, correction,
                    explanation, vocabulary_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING id
                """,
                (
                    session_id,
                    role,
                    content,
                    correction,
                    explanation,
                    json.dumps(vocabulary or [], ensure_ascii=False),
                    utc_now(),
                ),
            )
            return int(cursor.fetchone()["id"])


def get_session_messages(session_id: int, user_id: int) -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.*
                FROM messages m
                JOIN practice_sessions s ON s.id = m.session_id
                WHERE m.session_id = %s AND s.user_id = %s
                ORDER BY m.id
                """,
                (session_id, user_id),
            )
            rows = cursor.fetchall()

    messages: list[dict[str, Any]] = []
    for raw_row in rows:
        row = _normalise_row(raw_row) or {}
        vocabulary = row.pop("vocabulary_json", [])
        if isinstance(vocabulary, str):
            try:
                vocabulary = json.loads(vocabulary)
            except json.JSONDecodeError:
                vocabulary = []
        row["vocabulary"] = vocabulary if isinstance(vocabulary, list) else []
        messages.append(row)
    return messages


def update_session_statistics(
    session_id: int,
    duration_minutes: float,
    learner_words: int,
    corrections_count: int,
) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE practice_sessions
                SET duration_minutes = duration_minutes + %s,
                    learner_words = learner_words + %s,
                    corrections_count = corrections_count + %s
                WHERE id = %s
                """,
                (
                    max(0.0, duration_minutes),
                    max(0, learner_words),
                    max(0, corrections_count),
                    session_id,
                ),
            )


def log_usage(
    user_id: int,
    session_id: int | None,
    event_type: str,
    model: str,
    billed_minutes: float = 0.0,
    input_units: float = 0.0,
    output_units: float = 0.0,
    estimated_cost_usd: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO usage_logs(
                    user_id, session_id, event_type, model,
                    billed_minutes, input_units, output_units,
                    estimated_cost_usd, metadata_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    user_id,
                    session_id,
                    event_type,
                    model,
                    billed_minutes,
                    input_units,
                    output_units,
                    estimated_cost_usd,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )


def get_user_progress(user_id: int) -> dict[str, Any]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS sessions,
                    COALESCE(SUM(duration_minutes), 0) AS minutes,
                    COALESCE(SUM(learner_words), 0) AS words,
                    COALESCE(SUM(corrections_count), 0) AS corrections
                FROM practice_sessions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return _normalise_row(cursor.fetchone()) or {
                "sessions": 0,
                "minutes": 0,
                "words": 0,
                "corrections": 0,
            }


def get_recent_sessions(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, topic, level, started_at, ended_at,
                       duration_minutes, learner_words, corrections_count, status
                FROM practice_sessions
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return _normalise_rows(cursor.fetchall())


def get_admin_users() -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    u.id, u.name, u.email, u.role, u.status,
                    u.created_at, u.last_login_at,
                    p.name AS plan_name,
                    s.remaining_minutes,
                    s.allocated_minutes,
                    s.expires_at,
                    s.status AS subscription_status
                FROM users u
                LEFT JOIN LATERAL (
                    SELECT s2.*
                    FROM subscriptions s2
                    WHERE s2.user_id = u.id
                    ORDER BY s2.id DESC
                    LIMIT 1
                ) s ON TRUE
                LEFT JOIN plans p ON p.id = s.plan_id
                ORDER BY u.id DESC
                """
            )
            return _normalise_rows(cursor.fetchall())


def get_admin_usage_summary() -> dict[str, Any]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS usage_events,
                    COALESCE(SUM(billed_minutes), 0) AS billed_minutes,
                    COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                    COUNT(DISTINCT user_id) AS active_users
                FROM usage_logs
                """
            )
            return _normalise_row(cursor.fetchone()) or {
                "usage_events": 0,
                "billed_minutes": 0,
                "estimated_cost_usd": 0,
                "active_users": 0,
            }


def get_admin_daily_costs(limit: int = 30) -> list[dict[str, Any]]:
    with get_pool().connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date,
                    ROUND(SUM(estimated_cost_usd)::numeric, 6) AS estimated_cost_usd,
                    ROUND(SUM(billed_minutes)::numeric, 3) AS billed_minutes,
                    COUNT(*) AS events
                FROM usage_logs
                GROUP BY TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                ORDER BY date DESC
                LIMIT %s
                """,
                (limit,),
            )
            return _normalise_rows(cursor.fetchall())


def delete_user_conversation_history(user_id: int) -> None:
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM practice_sessions WHERE user_id = %s",
                (user_id,),
            )
