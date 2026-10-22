import pandas as pd
import streamlit as st

from src import adminstore as store
from src.auth import require_login

user = require_login()
if user["role"] != store.ADMIN_ROLE:
    st.error("Only administrators can open this page.")
    st.stop()

st.header("Admin: tables and access")
st.caption(
    "Register tables, then decide which roles can open them and which columns each role may view or edit. "
    "Every change is written to the change log."
)

flash = st.session_state.pop("adm_flash", None)
if flash:
    st.success(flash)

tab_access, tab_log = st.tabs(["Tables and access", "Change log"])

with tab_access:
    # ---------- Registered tables ----------
    tables = store.registered_tables()
    st.subheader("Registered tables")
    if tables.empty:
        st.info("No tables are registered yet.")
    else:
        st.dataframe(
            tables.rename(columns={"TABLE_NAME": "Table", "DISPLAY_NAME": "Display name", "OWNER_COLUMN": "Owner column"}),
            hide_index=True,
        )

    # ---------- Add a table ----------
    st.subheader("Add a table")
    st.caption(
        "The app can only read tables that its Snowflake role (APP_ROLE) has been granted SELECT on. "
        "A new table starts visible to ADMIN only. You open it up below."
    )
    with st.expander("Browse a schema for tables"):
        schema = st.text_input("Schema (DATABASE.SCHEMA)", value="APP_DB.PUBLIC", key="adm_schema")
        if st.button("List tables", key="adm_browse"):
            try:
                found = store.browse_schema(store.normalise(schema))
                st.write(", ".join(found) if found else "No tables visible to the app in that schema.")
            except Exception as e:
                st.error(f"Could not list tables: {e}")

    new_name = st.text_input("Table name (DATABASE.SCHEMA.TABLE)", key="adm_new_name", placeholder="APP_DB.PUBLIC.MY_TABLE")
    if st.button("Check table", key="adm_check_btn"):
        name = store.normalise(new_name)
        st.session_state.pop("adm_check", None)
        try:
            cols = store.table_columns(name)
            st.session_state["adm_check"] = {"name": name, "columns": cols}
        except Exception as e:
            st.error(f"Could not read that table: {e}. If it exists, ask a Snowflake admin to grant SELECT on it to APP_ROLE.")

    chk = st.session_state.get("adm_check")
    if chk:
        if chk["name"] in set(tables["TABLE_NAME"]):
            st.info("This table is already registered. Use Edit access below.")
        else:
            st.success(f"Found {len(chk['columns'])} columns: " + ", ".join(chk["columns"]))
            display = st.text_input(
                "Display name", value=chk["name"].split(".")[-1].replace("_", " ").title(), key=f"adm_nd_{chk['name']}"
            )
            owner_pick = st.selectbox(
                "Column holding the owner's username (used by own-rows-only roles)",
                ["(none)"] + chk["columns"],
                key=f"adm_no_{chk['name']}",
            )
            if st.button("Register table", key="adm_register"):
                try:
                    store.register_table(
                        user["username"], chk["name"], display.strip() or chk["name"],
                        None if owner_pick == "(none)" else owner_pick, chk["columns"], store.known_roles(),
                    )
                    st.cache_data.clear()
                    st.session_state.pop("adm_check", None)
                    st.session_state["adm_flash"] = f"{chk['name']} registered. It is visible to ADMIN only until you open it up."
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not register the table: {e}")

    # ---------- Edit access ----------
    st.subheader("Edit access")
    if tables.empty:
        st.stop()

    version = st.session_state.get("adm_ver", 0)
    sel = st.selectbox("Table", list(tables["TABLE_NAME"]), key="adm_sel")
    row = tables[tables["TABLE_NAME"] == sel].iloc[0]

    try:
        columns = store.table_columns(sel)
    except Exception as e:
        st.error(f"The app cannot read {sel} right now: {e}")
        st.stop()

    roles = store.known_roles()
    rules = store.current_rules(sel)
    open_now = store.open_roles(sel)

    display_edit = st.text_input("Display name", value=row["DISPLAY_NAME"] or sel, key=f"adm_disp_{sel}_{version}")
    owner_options = ["(none)"] + columns
    owner_index = owner_options.index(row["OWNER_COLUMN"]) if row["OWNER_COLUMN"] in columns else 0
    owner_edit = st.selectbox(
        "Owner column (own-rows-only roles see only rows where this equals their username; with none, they see nothing)",
        owner_options, index=owner_index, key=f"adm_owner_{sel}_{version}",
    )
    open_pick = st.multiselect(
        "Roles that can open this table", roles,
        default=[r for r in roles if r in open_now or r == store.ADMIN_ROLE],
        key=f"adm_open_{sel}_{version}",
    )

    def _grid(flag: int) -> pd.DataFrame:
        return pd.DataFrame(
            {r: [rules.get((c, r), (False, False))[flag] for c in columns] for r in roles},
            index=columns,
        )

    st.markdown("**Can view** (ADMIN always sees every column)")
    view_df = st.data_editor(_grid(0), key=f"adm_view_{sel}_{version}", disabled=[store.ADMIN_ROLE])
    st.markdown("**Can edit** (a role must be able to view a column before it can edit it)")
    edit_df = st.data_editor(_grid(1), key=f"adm_edit_{sel}_{version}")

    if st.button("Save access for this table", type="primary", key=f"adm_save_{sel}"):
        view = {(c, r): bool(view_df.loc[c, r]) for c in columns for r in roles}
        edit = {(c, r): bool(edit_df.loc[c, r]) for c in columns for r in roles}
        bad = sorted({f"{r}: {c}" for (c, r), e in edit.items() if e and not (view[(c, r)] or r == store.ADMIN_ROLE)})
        hidden_but_open = [r for r in roles if r not in open_pick and r != store.ADMIN_ROLE
                           and any(view[(c, r)] for c in columns)]
        if bad:
            st.error("These roles can edit a column they cannot view. Tick View first: " + "; ".join(bad))
        else:
            try:
                summary = store.save_access(
                    user["username"], sel, display_edit.strip() or sel,
                    None if owner_edit == "(none)" else owner_edit,
                    columns, roles, view, edit, open_pick,
                )
                st.cache_data.clear()
                st.session_state["adm_ver"] = version + 1
                msg = f"Saved. {summary}"
                if hidden_but_open:
                    msg += (" Note: " + ", ".join(hidden_but_open) +
                            " have column access but cannot open the table, so they will not see it.")
                st.session_state["adm_flash"] = msg
                st.rerun()
            except Exception as e:
                st.error(f"Could not save: {e}. If this says insufficient privileges, the app role needs write access "
                         "to the access tables. If it failed part-way, the table may be closed to everyone except "
                         "ADMIN; saving again fixes it.")

    with st.expander("Column descriptions (help the AI understand each column)"):
        st.caption("Say in plain words what each column means. Do not put secrets or personal data here: "
                   "these may be sent to the AI provider, only for roles that can view the column.")
        descs = store.column_descriptions(sel)
        desc_df = st.data_editor(
            pd.DataFrame({"Description": [descs.get(c) or "" for c in columns]}, index=columns),
            key=f"adm_desc_{sel}_{version}",
        )
        if st.button("Save descriptions", key=f"adm_desc_save_{sel}"):
            try:
                new = {c: ("" if pd.isna(desc_df.loc[c, "Description"]) else str(desc_df.loc[c, "Description"])).strip()
                       for c in columns}
                n = store.save_descriptions(user["username"], sel, columns, new)
                st.session_state["adm_flash"] = f"Saved. {n} description(s) changed."
                st.rerun()
            except Exception as e:
                st.error(f"Could not save descriptions: {e}")
    with st.expander("Remove this table from the app"):
        if sel == store.PROTECTED_TABLE:
            st.caption("This table is used by the Data and Executive pages and cannot be removed.")
        else:
            st.caption("This removes the table, its access rules and its metrics from the app. The Snowflake table is not touched.")
            confirm = st.checkbox(f"Yes, remove {sel} from the app", key=f"adm_rm_ok_{sel}")
            if st.button("Remove table", disabled=not confirm, key=f"adm_rm_{sel}"):
                try:
                    store.unregister_table(user["username"], sel)
                    st.cache_data.clear()
                    st.session_state["adm_flash"] = f"{sel} removed from the app."
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not remove it: {e}")

with tab_log:
    st.subheader("Change log")
    try:
        log = store.recent_changes(50)
        if log.empty:
            st.info("No changes recorded yet.")
        else:
            st.dataframe(log, hide_index=True)
    except Exception as e:
        st.error(f"Could not read the change log: {e}. Has the ADMIN_CHANGE_LOG table been created?")



