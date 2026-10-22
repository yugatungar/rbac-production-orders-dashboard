"""Tests the AI building blocks WITHOUT any AI. Run from the project folder:  python test_agent_offline.py"""
from src.agent.compiler import compile_spec, distinct_values, run_spec
from src.agent.schema import build_schema, schema_for_prompt
from src.agent.validator import validate

USERS = {
    "admin": {"username": "admin", "role": "ADMIN", "row_scope": "ALL"},
    "leadership1": {"username": "leadership1", "role": "LEADERSHIP", "row_scope": "ALL"},
    "operator1": {"username": "operator1", "role": "OPERATOR", "row_scope": "OWN"},
}

REQUESTS = {
    "planned vs built by plant": {
        "table": "PRODUCTION_ORDERS", "chart": "Bar", "x": "PLANT",
        "measures": [{"column": "QTY_PLANNED", "agg": "Sum"}, {"column": "QTY_BUILT", "agg": "Sum"}],
    },
    "built per month, split by status": {
        "table": "PRODUCTION_ORDERS", "chart": "Line", "x": "TARGET_DATE",
        "measures": [{"column": "QTY_BUILT", "agg": "Sum"}], "color": "STATUS",
    },
    "orders per OWNER (hidden for some roles)": {
        "table": "PRODUCTION_ORDERS", "chart": "Bar", "x": "OWNER",
        "measures": [{"column": None, "agg": "Count"}],
    },
    "plant filter with a value that does not exist": {
        "table": "PRODUCTION_ORDERS", "chart": "Bar", "x": "STATUS",
        "measures": [{"column": None, "agg": "Count"}],
        "filters": [{"column": "PLANT", "values": ["Pune", "Mumbai"]}],
    },
}

for name, user in USERS.items():
    print("=" * 70)
    print(f"USER {name}  (role {user['role']}, rows: {user['row_scope']})")
    schema = build_schema(user)
    if name == "leadership1":
        print("\n--- EXACTLY what the AI would be told about the database ---")
        print(schema_for_prompt(schema))
        print("--- end ---")
    check = lambda t, c, u=user, s=schema: distinct_values(u, t, c, s)
    for label, req in REQUESTS.items():
        print(f"\n> {label}")
        res = validate(req, schema, check)
        if not res["ok"]:
            print("  REJECTED:", "; ".join(res["errors"]))
            continue
        if res["clarify"]:
            for c in res["clarify"]:
                print(f"  WOULD ASK THE USER: no {c['column']} called '{c['asked']}'. Choices: {', '.join(c['choices'])}")
        for n in res["notes"]:
            print("  note:", n)
        sql, params, info = compile_spec(user, res["spec"], schema)
        print("  SQL:", sql)
        print("  params:", params)
        df, _ = run_spec(user, res["spec"], schema)
        print(df.head(5).to_string(index=False))
print("\nDone.")
