import streamlit as st

from src.auth import logout, require_login

st.set_page_config(page_title="Cummins Dashboard", page_icon=":bar_chart:", layout="wide")

user = require_login()

PAGE_ORDER = ["Executive", "Analysis", "Charts", "Ask", "Data", "Developer", "Admin"]
CHART_ROLES_PAGES = {"Executive", "Analysis", "Developer", "Admin"}


def _coming_soon(title: str):
    def render():
        st.header(title)
        st.info("This page is built in a later step.")
    render.__name__ = f"page_{title.lower()}"
    return render


def _build_page(name: str):
    if name == "Data":
        return st.Page("views/data.py", title="Data", url_path="data")
    if name == "Executive":
        return st.Page("views/executive.py", title="Executive", url_path="executive")
    if name == "Admin":
        return st.Page("views/admin.py", title="Admin", url_path="admin")
    if name == "Charts":
        return st.Page("views/charts.py", title="Charts", url_path="charts")
    if name == "Ask":
        return st.Page("views/ask.py", title="Ask your data", url_path="ask")
    return st.Page(_coming_soon(name), title=name, url_path=name.lower())


# Anyone who can see a chart page can also build their own charts
allowed_names = set(user["pages"])
if user["role"] == "ADMIN":
    allowed_names.add("Admin")
if allowed_names & CHART_ROLES_PAGES:
    allowed_names.add("Charts")
    allowed_names.add("Ask")

pages = [_build_page(n) for n in PAGE_ORDER if n in allowed_names]
if not pages:
    st.error("No pages are assigned to your role. Contact an administrator.")
    st.stop()

with st.sidebar:
    st.subheader(user["display_name"])
    st.caption(f"Role: {user['role']}")
    if st.button("Sign out"):
        logout()
        st.rerun()

st.navigation(pages).run()

