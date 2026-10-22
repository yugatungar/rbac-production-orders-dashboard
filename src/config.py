import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    warehouse: str
    role: str
    database: str
    schema: str
    authenticator: str
    password: str

    def missing(self) -> list[str]:
        required = {
            "SNOWFLAKE_ACCOUNT": self.account,
            "SNOWFLAKE_USER": self.user,
            "SNOWFLAKE_WAREHOUSE": self.warehouse,
        }
        return [k for k, v in required.items() if not v]


def load_settings() -> SnowflakeSettings:
    return SnowflakeSettings(
        account=_get("SNOWFLAKE_ACCOUNT"),
        user=_get("SNOWFLAKE_USER"),
        warehouse=_get("SNOWFLAKE_WAREHOUSE"),
        role=_get("SNOWFLAKE_ROLE"),
        database=_get("SNOWFLAKE_DATABASE"),
        schema=_get("SNOWFLAKE_SCHEMA"),
        authenticator=_get("SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
        password=_get("SNOWFLAKE_PASSWORD"),
    )
MAX_FAILED_ATTEMPTS = int(_get("MAX_FAILED_ATTEMPTS", "5"))
LOCK_MINUTES = int(_get("LOCK_MINUTES", "15"))
SESSION_TIMEOUT_MINUTES = int(_get("SESSION_TIMEOUT_MINUTES", "30"))

ORDERS_TABLE = _get("ORDERS_TABLE", "PRODUCTION_ORDERS")
MAX_ROWS = int(_get("MAX_ROWS", "50000"))

# The only columns the app may ever select (identifiers can't be query parameters,
# so this list is the allow-list).
ORDER_COLUMNS = (
    "ORDER_ID", "ENGINE_MODEL", "PLANT", "STATUS", "QTY_PLANNED", "QTY_BUILT",
    "DEFECT_COUNT", "TARGET_DATE", "OWNER", "REMARKS", "UPDATED_AT",
)
