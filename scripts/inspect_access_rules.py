from src.db import run_query


def show(title: str, sql: str) -> None:
    print(f"\n{title}")
    df = run_query(sql)
    print(df.to_string(index=False) if not df.empty else "(no rows)")


show(
    "APP_ROLES",
    "SELECT ROLE_NAME, LENGTH(ROLE_NAME) AS NAME_LEN, ROW_SCOPE FROM APP_ROLES ORDER BY 1",
)
show(
    "ROLE_PAGE_ACCESS",
    "SELECT ROLE_NAME, LENGTH(ROLE_NAME) AS NAME_LEN, PAGE_NAME FROM ROLE_PAGE_ACCESS ORDER BY 1, 3",
)
show(
    "APP_USERS",
    "SELECT USERNAME, ROLE_NAME, LENGTH(ROLE_NAME) AS NAME_LEN, IS_ACTIVE FROM APP_USERS ORDER BY 1",
)
