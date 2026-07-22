from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import streamlit as st

from agent import DEFAULT_DB_PATH, DEFAULT_MODEL, build_llm, run_pipeline
from audit import load_recent_events
from db.seed_data import initialize_database


EXAMPLES = {
    "Show overdue invoices": "Show me overdue invoices by account and amount",
    "Blocked destructive query": "DROP TABLE accounts",
    "PII lookup": "Show me all customer phone numbers",
    "Account summary": "How many accounts are active in each region?",
}


def load_local_env() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

def ensure_database_exists(db_path: Path) -> None:
    if not db_path.exists():
        initialize_database(db_path)


def resolve_db_path() -> Path:
    if "SQLITE_DB_PATH" in os.environ:
        return Path(os.environ["SQLITE_DB_PATH"])
    try:
        return Path(st.secrets.get("SQLITE_DB_PATH", str(DEFAULT_DB_PATH)))
    except Exception:
        return DEFAULT_DB_PATH


def main() -> None:
    st.set_page_config(page_title="Ask Your Billing DB", page_icon="DB", layout="wide")
    st.title("Ask Your Billing DB")
    st.caption("Natural-language SQL demo with guardrails, audit logging, and role-based access control.")

    db_path = resolve_db_path()
    ensure_database_exists(db_path)
    llm = build_llm()

    with st.sidebar:
        st.header("Access")
        role = st.selectbox("Role", ["analyst", "compliance_officer"], index=0)
        st.markdown("The compliance role can query PII columns; the analyst role cannot.")

        st.header("LLM status")
        if llm is not None:
            st.success(f"Gemini enabled: {DEFAULT_MODEL}")
        else:
            st.warning("Fallback mode only: set GOOGLE_API_KEY in .env to enable Gemini.")

        st.header("Demo queries")
        for label, example in EXAMPLES.items():
            if st.button(label, use_container_width=True):
                st.session_state["question"] = example

    question = st.text_area(
        "Ask a billing question",
        value=st.session_state.get("question", "Show me overdue invoices by region"),
        height=120,
    )

    run_clicked = st.button("Run query", type="primary")

    if run_clicked:
        with st.spinner("Generating and validating SQL..."):
            result = run_pipeline(question, role=role, db_path=db_path, llm=llm)

        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("Generated SQL")
            st.code(result.get("generated_sql", ""), language="sql")
            verdict = result.get("guardrail_verdict")
            if verdict and verdict.allowed:
                st.success(verdict.reason)
            elif verdict:
                st.error(verdict.reason)

        with col2:
            st.subheader("Summary")
            st.write(result.get("summary", ""))
            
            if result.get("context_explanation"):
                st.divider()
                st.caption("**Table selection reasoning:**")
                st.markdown(result.get("context_explanation", ""))

        st.subheader("Results")
        rows = result.get("rows", []) or []
        if rows:
            st.dataframe(rows, use_container_width=True)
        else:
            st.info("No rows returned or the query was blocked.")

    st.divider()
    tab1, tab2 = st.tabs(["Blocked query examples", "Audit log"])

    with tab1:
        st.write("These examples are intended to trigger guardrails during a demo.")
        st.markdown("- DROP TABLE accounts")
        st.markdown("- show me all customer phone numbers")
        st.markdown("- update accounts set account_status = 'closed'")
        st.markdown("- SELECT * FROM accounts; DELETE FROM accounts;")

    with tab2:
        st.subheader("Recent audit log")
        try:
            with sqlite3.connect(db_path) as connection:
                events = load_recent_events(connection, limit=10)
            if events:
                for event in events:
                    with st.container(border=True):
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            st.markdown(f"**Q:** {event['user_question']}")
                            st.markdown(f"**SQL:** `{event['generated_sql'] or 'N/A'}`")
                        with col_b:
                            status = "✅ Allowed" if event["guardrail_allowed"] else "🔒 Blocked"
                            st.markdown(status)
                            st.caption(f"Role: {event['role']}")
                            st.caption(event["guardrail_reason"])
            else:
                st.info("No audit log entries yet.")
        except Exception as e:
            st.warning(f"Could not load audit log: {e}")


if __name__ == "__main__":
    main()
