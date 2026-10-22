from src.config import load_settings
from src.db import run_query

settings = load_settings()
print("Settings read from .env:")
print("  role     :", settings.role or "(blank)")
print("  database :", settings.database or "(blank)")
print("  schema   :", settings.schema or "(blank)")
print("  warehouse:", settings.warehouse or "(blank)")

print("\nWhat Snowflake says the session is using:")
print(
    run_query(
        "SELECT CURRENT_ROLE() AS ROLE_NAME, "
        "CURRENT_DATABASE() AS DATABASE_NAME, "
        "CURRENT_SCHEMA() AS SCHEMA_NAME"
    ).to_string(index=False)
)

print("\nDatabases this role can see:")
print(run_query("SHOW DATABASES")[["name"]].to_string(index=False))