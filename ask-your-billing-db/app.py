from __future__ import annotations

from pathlib import Path
import os

import streamlit as st

from agent import DEFAULT_DB_PATH, run_pipeline
from db.seed_data import initialize_database


EXAMPLES = {
    "Show overdue invoices": "Show me overdue invoices by account and amount",
    "Blocked destructive query": "DROP TABLE accounts",
    "PII lookup": "Show me all customer phone numbers",
    "Account summary": "How many accounts are active in each region?",
}


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

    with st.sidebar:
        st.header("Access")
        role = st.selectbox("Role", ["analyst", "compliance_officer"], index=0)
        st.markdown("The compliance role can query PII columns; the analyst role cannot.")

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
            result = run_pipeline(question, role=role, db_path=db_path)

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

        st.subheader("Results")
        rows = result.get("rows", []) or []
        if rows:
            st.dataframe(rows, use_container_width=True)
        else:
            st.info("No rows returned or the query was blocked.")

    with st.expander("Blocked query examples"):
        st.write("These examples are intended to trigger guardrails during a demo.")
        st.markdown("- DROP TABLE accounts")
        st.markdown("- show me all customer phone numbers")
        st.markdown("- update accounts set account_status = 'closed'")


if __name__ == "__main__":
    main()
