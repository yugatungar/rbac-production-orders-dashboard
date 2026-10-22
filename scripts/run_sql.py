import sys
from pathlib import Path

from src.db import run_query


def split_statements(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.run_sql sql/02_create_access_tables.sql")
        sys.exit(1)
    sql_text = Path(sys.argv[1]).read_text(encoding="utf-8-sig")
    for statement in split_statements(sql_text):
        print("Running:", statement.splitlines()[0][:70])
        run_query(statement)
    print("Done.")


main()