# Role-Based Production Orders Dashboard

A Streamlit dashboard backed by Snowflake. Users sign in with an assigned role; dataset, row, and
column access determine which data and pages they can use. The project includes an executive
overview, data and chart views, an admin access-management page, and a natural-language data
explorer.

## Access model

| Role | Row scope | Seeded pages | Column access |
|---|---|---|---|
| `LEADERSHIP` | All rows | Executive | Excludes owner, remarks, and update timestamp |
| `ANALYST` | All rows | Executive, Analysis, Data | Excludes remarks |
| `OPERATOR` | Own rows | Data | Operational columns |
| `DEVELOPER` | All rows | Analysis, Data, Developer | All production-order columns |
| `ADMIN` | All rows | Executive, Analysis, Data, Developer, Admin | All columns and access administration |

These starter grants are seeded by the SQL scripts and can be adjusted in Snowflake. Dataset and
column checks are applied before the app fetches data. `OPERATOR` rows are scoped to the signed-in
username using the `OWNER` field. The current Data page is read-only; `CAN_EDIT` grants are stored
for access management but are not yet exposed as order-edit controls.

## Requirements

- Python 3.10 or later
- A Snowflake account, warehouse, database, and schema
- A Snowflake role with the permissions needed to create and use the app tables and read
  `PRODUCTION_ORDERS`

## Local setup

From the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your Snowflake connection settings. Keep this file private; it is excluded from
Git. For local SSO, set `SNOWFLAKE_AUTHENTICATOR=externalbrowser`.

In Snowsight, select the database and schema configured in `.env`, then run these scripts in order:

1. `sql/02_create_access_tables.sql` — app, dataset, audit, and admin support tables.
2. `sql/03_seed_access_rules.sql` — starter roles and page access.
3. `sql/04_create_orders_table.sql` — sample production-orders table.
4. `sql/05_seed_orders_data.sql` — 300 sample orders. Re-running this script replaces the sample rows.
5. `sql/06_seed_column_access.sql` — registers the sample dataset and seeds row/column access.

Create an initial administrator. The command prompts for a password:

```powershell
python -m scripts.create_user admin "Dashboard Admin" ADMIN
```

Additional sample-data users can be created as needed. Use `operator1` for an `OPERATOR` account
to see the sample rows owned by that user.

Start the dashboard:

```powershell
streamlit run app.py
```

Open http://localhost:8501.

## Tests

The offline checks use scripted model responses and do not require AI credentials or a live Snowflake
connection:

```powershell
python test_agent_flow.py
python test_agent_offline.py
python test_sql_guard.py
python test_table_dates.py
python test_validate_months.py
```

## Project structure

```text
app.py                 Streamlit entry point and role-aware page routing
src/                   Authentication, data access, charts, and guarded AI query flow
views/                 Executive, data, charts, ask-data, and admin pages
scripts/create_user.py Interactive Snowflake user bootstrap
sql/                   Ordered Snowflake schema and sample-data setup
.env.example           Local configuration template (no real credentials)
```

## Security notes

- Never commit `.env`, Streamlit secrets, private keys, or production credentials.
- Use a least-privilege Snowflake role and review starter access rules before deployment.
- The sample password-based login is intended for this app; use your organization's identity
  provider and HTTPS for a production deployment.
- Review the app's row and column grants against your organization's data-handling requirements.
