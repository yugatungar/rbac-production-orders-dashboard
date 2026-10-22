import time

import bcrypt
import streamlit as st

from src.config import LOCK_MINUTES, MAX_FAILED_ATTEMPTS, SESSION_TIMEOUT_MINUTES
from src.db import run_query


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def log_event(username: str, action: str, detail: str = "") -> None:
    try:
        run_query(
            "INSERT INTO AUDIT_LOG (USERNAME, ACTION, DETAIL) VALUES (%(u)s, %(a)s, %(d)s)",
            {"u": username, "a": action, "d": detail},
        )
    except Exception as e:
        st.warning(f"Could not write audit log: {e}")


def _find_user(username: str):
    df = run_query(
        """
        SELECT USERNAME, DISPLAY_NAME, PASSWORD_HASH, ROLE_NAME, IS_ACTIVE, FAILED_ATTEMPTS,
               COALESCE(LOCKED_UNTIL > CURRENT_TIMESTAMP(), FALSE) AS IS_LOCKED
        FROM APP_USERS
        WHERE USERNAME = %(u)s
        """,
        {"u": username},
    )
    return None if df.empty else df.iloc[0].to_dict()


def _role_info(role_name: str):
    scope = run_query(
        "SELECT ROW_SCOPE FROM APP_ROLES WHERE ROLE_NAME = %(r)s", {"r": role_name}
    )
    pages = run_query(
        "SELECT PAGE_NAME FROM ROLE_PAGE_ACCESS WHERE ROLE_NAME = %(r)s", {"r": role_name}
    )
    row_scope = scope.iloc[0]["ROW_SCOPE"] if not scope.empty else "OWN"
    return row_scope, sorted(pages["PAGE_NAME"].tolist())


def authenticate(username: str, password: str):
    username = username.strip().lower()
    row = _find_user(username)

    if row is None or not row["IS_ACTIVE"]:
        log_event(username or "?", "LOGIN_FAILED", "unknown or inactive user")
        return None, "Invalid username or password."

    if row["IS_LOCKED"]:
        log_event(username, "LOGIN_BLOCKED", "account locked")
        return None, "Account temporarily locked after too many failed attempts. Try again later."

    if not verify_password(password, row["PASSWORD_HASH"]):
        failed = int(row["FAILED_ATTEMPTS"])
        new_count = 1 if failed >= MAX_FAILED_ATTEMPTS else failed + 1
        lock = new_count >= MAX_FAILED_ATTEMPTS
        run_query(
            """
            UPDATE APP_USERS
            SET FAILED_ATTEMPTS = %(n)s,
                LOCKED_UNTIL = IFF(%(lock)s, DATEADD(minute, %(m)s, CURRENT_TIMESTAMP()), LOCKED_UNTIL)
            WHERE USERNAME = %(u)s
            """,
            {"n": new_count, "lock": lock, "m": LOCK_MINUTES, "u": username},
        )
        log_event(username, "LOGIN_FAILED", "wrong password")
        return None, "Invalid username or password."

    run_query(
        "UPDATE APP_USERS SET FAILED_ATTEMPTS = 0, LOCKED_UNTIL = NULL, "
        "LAST_LOGIN = CURRENT_TIMESTAMP() WHERE USERNAME = %(u)s",
        {"u": username},
    )
    row_scope, pages = _role_info(row["ROLE_NAME"])
    log_event(username, "LOGIN_OK")
    return {
        "username": username,
        "display_name": row["DISPLAY_NAME"] or username,
        "role": row["ROLE_NAME"],
        "row_scope": row_scope,
        "pages": pages,
    }, ""


def logout(reason: str = "LOGOUT") -> None:
    user = st.session_state.get("user")
    if user:
        log_event(user["username"], reason)
    st.session_state.clear()
    if reason == "TIMEOUT":
        st.session_state["notice"] = "Your session timed out. Please sign in again."


def _login_form() -> None:
    st.title("Cummins Dashboard")
    notice = st.session_state.pop("notice", None)
    if notice:
        st.info(notice)
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        if not username or not password:
            st.error("Enter both username and password.")
            return
        user, message = authenticate(username, password)
        if user:
            st.session_state["user"] = user
            st.session_state["last_active"] = time.time()
            st.rerun()
        else:
            st.error(message)


def require_login():
    user = st.session_state.get("user")
    idle = time.time() - st.session_state.get("last_active", 0)
    if user and idle > SESSION_TIMEOUT_MINUTES * 60:
        logout("TIMEOUT")
        user = None
    if user:
        st.session_state["last_active"] = time.time()
        return user
    _login_form()
    st.stop()
