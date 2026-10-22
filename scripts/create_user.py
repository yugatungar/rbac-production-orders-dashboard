import getpass
import sys

from src.auth import hash_password
from src.db import run_query


def main():
    if len(sys.argv) != 4:
        print('Usage: python -m scripts.create_user <username> "<Display Name>" <ROLE>')
        sys.exit(1)

    username = sys.argv[1].strip().lower()
    display_name = sys.argv[2].strip()
    role = sys.argv[3].strip().upper()

    valid_roles = run_query("SELECT ROLE_NAME FROM APP_ROLES")["ROLE_NAME"].tolist()
    if role not in valid_roles:
        print(f"Unknown role {role}. Valid roles: {', '.join(valid_roles)}")
        sys.exit(1)

    password = getpass.getpass("Password (min 8 characters): ")
    if len(password) < 8:
        print("Password too short.")
        sys.exit(1)
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        sys.exit(1)

    hashed = hash_password(password)
    exists = run_query("SELECT 1 FROM APP_USERS WHERE USERNAME = %(u)s", {"u": username})
    if exists.empty:
        run_query(
            "INSERT INTO APP_USERS (USERNAME, DISPLAY_NAME, PASSWORD_HASH, ROLE_NAME) "
            "VALUES (%(u)s, %(d)s, %(h)s, %(r)s)",
            {"u": username, "d": display_name, "h": hashed, "r": role},
        )
        print(f"Created user {username} ({role}).")
    else:
        run_query(
            "UPDATE APP_USERS SET DISPLAY_NAME = %(d)s, PASSWORD_HASH = %(h)s, ROLE_NAME = %(r)s, "
            "IS_ACTIVE = TRUE, FAILED_ATTEMPTS = 0, LOCKED_UNTIL = NULL WHERE USERNAME = %(u)s",
            {"u": username, "d": display_name, "h": hashed, "r": role},
        )
        print(f"Updated user {username} ({role}).")


main()
