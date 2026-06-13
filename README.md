# SpeakMate Business: Streamlit Community Cloud Edition

This edition is designed for Streamlit Community Cloud.

## Architecture

```text
Customer browser
    ↓
Streamlit Community Cloud application
    ├── Login and subscription checks
    ├── Remaining-minute checks
    ├── Conversation interface
    └── Progress and admin dashboards
    ↓
Server-side Python backend modules
    ├── OpenAI API key in Streamlit Secrets
    ├── Moderation
    ├── Usage and cost logging
    └── PostgreSQL database access
    ↓                         ↓
OpenAI API              Supabase PostgreSQL
```

The browser never receives the OpenAI key or the PostgreSQL password.

## Why SQLite was removed

Streamlit Community Cloud does not guarantee persistence for files stored on the app's local filesystem. A local SQLite database can therefore disappear after a reboot, redeployment, or platform maintenance. This version uses an external Supabase PostgreSQL database.

## Files to upload to GitHub

```text
app.py
requirements.txt
.python-version
.gitignore
backend/
.streamlit/secrets.example.toml
README.md
```

Do not upload `.streamlit/secrets.toml` containing real credentials.

## Step 1: Create a Supabase project

1. Create a project in Supabase.
2. Open **Project Settings → Database** or the **Connect** panel.
3. Copy the **Session pooler** PostgreSQL connection string.
4. Replace the password placeholder with your real database password.
5. Keep the string private.

The app creates its tables automatically on first launch.

## Step 2: Upload this project to GitHub

Create a GitHub repository and upload the project files while preserving the `backend` and `.streamlit` folders.

## Step 3: Deploy on Streamlit Community Cloud

1. Sign in to Streamlit Community Cloud.
2. Select **Create app**.
3. Choose your GitHub repository and branch.
4. Set the entrypoint file to `app.py`.
5. In **Advanced settings**, choose Python 3.12.
6. Paste your secrets into the **Secrets** box.
7. Deploy.

## Streamlit Cloud Secrets

Copy the contents of `.streamlit/secrets.example.toml`, replace every placeholder, and paste the result into the app's Community Cloud Secrets editor.

Minimum required secrets:

```toml
DATABASE_URL = "your-supabase-session-pooler-url"
OPENAI_API_KEY = "your-openai-api-key"
ADMIN_EMAIL = "your-admin-email"
ADMIN_PASSWORD = "a-strong-admin-password"
```

## Local testing

Create `.streamlit/secrets.toml` from the example file, then run:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Important production notes

- Community Cloud is suitable for an MVP and early customers, but monitor resource limits.
- Supabase is the permanent database; do not switch the cloud edition back to SQLite.
- Keep the OpenAI key and database URL only in Streamlit Secrets.
- Add payment webhooks before enabling automatic paid subscriptions.
- Add password reset, email verification, rate limiting, backups, and legal/privacy pages before a broad public launch.
