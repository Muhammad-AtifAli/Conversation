-- The application creates the same tables automatically on first launch.
-- This file is included for inspection and optional manual setup in Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'customer' CHECK(role IN ('customer', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'suspended')),
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
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'expired', 'cancelled')),
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
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'completed'))
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
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
