from __future__ import annotations

from typing import Any

from backend import database
from backend.security import (
    hash_password,
    normalize_email,
    validate_email,
    validate_password,
    verify_password,
)


def register_user(
    name: str,
    email: str,
    password: str,
    confirm_password: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    clean_name = name.strip()
    clean_email = normalize_email(email)

    if len(clean_name) < 2:
        return False, "Please enter your full name.", None
    if not validate_email(clean_email):
        return False, "Please enter a valid email address.", None
    valid_password, password_error = validate_password(password)
    if not valid_password:
        return False, password_error, None
    if password != confirm_password:
        return False, "The passwords do not match.", None

    try:
        user = database.create_user(
            name=clean_name,
            email=clean_email,
            password_hash=hash_password(password),
        )
    except database.DuplicateEmailError:
        return False, "An account with this email already exists.", None

    return True, "Your account has been created.", user


def authenticate_user(
    email: str,
    password: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    user = database.get_user_by_email(email)
    if user is None or not verify_password(password, user["password_hash"]):
        return False, "Incorrect email or password.", None
    if user["status"] != "active":
        return False, "This account has been suspended. Contact support.", None

    database.update_last_login(int(user["id"]))
    user.pop("password_hash", None)
    return True, "Signed in successfully.", user
