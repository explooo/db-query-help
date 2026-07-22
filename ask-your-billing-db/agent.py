from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from audit import log_event
from guardrails import GuardrailVerdict, classify_intent, enforce_row_limit, validate_sql
from prompts import SYSTEM_PROMPT
from schema import format_schema_context, select_relevant_tables

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - dependency may not be installed yet
    END = "__end__"
    StateGraph = None


DEFAULT_DB_PATH = Path(os.getenv("SQLITE_DB_PATH", "db/billing.sqlite"))
DEFAULT_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5-pro")
FALLBACK_MODELS = (
    DEFAULT_MODEL,
    "gemini-2.5-flash",
    "gemini-1.5-pro",
)


class QueryState(TypedDict, total=False):
    question: str
    role: str
    intent: str
    relevant_tables: list[str]
    schema_context: str
    context_explanation: str
    generated_sql: str
    guardrail_verdict: GuardrailVerdict
    rows: list[dict[str, Any]]
    summary: str


class GeminiRESTResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class GeminiRESTClient:
    def __init__(self, api_key: str, models: tuple[str, ...]) -> None:
        self.api_key = api_key
        self.models = models

    @staticmethod
    def _extract_message_content(message: Any) -> str:
        return getattr(message, "content", str(message))

    def _build_prompt(self, messages: list[Any]) -> str:
        parts: list[str] = []
        for message in messages:
            content = self._extract_message_content(message)
            parts.append(content)
        return "\n\n".join(parts)

    def invoke(self, messages: list[Any]) -> GeminiRESTResponse:
        prompt = self._build_prompt(messages)

        last_error: Exception | None = None
        for model in self.models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={self.api_key}"
            )
            payload = json.dumps(
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0,
                    },
                }
            ).encode("utf-8")
            request = Request(url, data=payload, headers={"Content-Type": "application/json"})

            try:
                with urlopen(request, timeout=30) as response:
                    body = json.loads(response.read().decode("utf-8"))
                text = (
                    body.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if text:
                    return GeminiRESTResponse(text)
                last_error = RuntimeError(f"Gemini response from model '{model}' did not include text.")
            except HTTPError as error:
                last_error = error
                if error.code in (400, 404):
                    continue
                raise
            except URLError as error:
                last_error = error
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("Gemini request failed without a response.")


def build_llm() -> Any | None:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_AI_STUDIO_API_KEY")
    if not api_key:
        return None
    models = tuple(dict.fromkeys(model for model in FALLBACK_MODELS if model))
    return GeminiRESTClient(api_key=api_key, models=models)


def strip_sql_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def explain_table_selection(question: str, relevant_tables: list[str]) -> str:
    """Explain why certain tables were selected based on the user question."""
    from schema import TABLES
    
    explanations = []
    lowered = question.lower()
    
    for table_name in relevant_tables:
        table = TABLES.get(table_name)
        if not table:
            continue
        
        matched_keywords = [kw for kw in table.keywords if kw in lowered]
        if matched_keywords:
            reasons = f"matched keywords: {', '.join(matched_keywords)}"
        else:
            reasons = "default table for billing queries"
        
        explanations.append(f"**{table_name}:** {table.description} ({reasons})")
    
    if not explanations:
        return "Using default billing tables (accounts, bill_invoice_detail, transactions)."
    
    return " | ".join(explanations)


def generate_sql_with_fallback(question: str, schema_context: str, role: str) -> str:
    lowered = question.lower()
    if any(word in lowered for word in ("phone", "address", "name")) and role != "compliance_officer":
        return "NO_VALID_QUERY"

    if "overdue" in lowered and "invoice" in lowered:
        return (
            "SELECT a.acc_id, a.region, b.invoice_id, b.invoice_date, b.amount, b.status "
            "FROM accounts a JOIN bill_invoice_detail b ON a.acc_id = b.acc_id "
            "WHERE b.status = 'overdue' ORDER BY b.invoice_date DESC LIMIT 100"
        )

    if "region" in lowered and ("active" in lowered or "status" in lowered or "account status" in lowered):
        where_clause = " WHERE account_status = 'active'" if "active" in lowered else ""
        return (
            "SELECT region, account_status, COUNT(*) AS account_count "
            f"FROM accounts{where_clause} GROUP BY region, account_status ORDER BY account_count DESC LIMIT 100"
        )

    if "region" in lowered and "count" in lowered:
        return "SELECT region, account_status, COUNT(*) AS account_count FROM accounts GROUP BY region, account_status ORDER BY account_count DESC LIMIT 100"

    if any(word in lowered for word in ("count", "how many", "number of")) and "invoice" in lowered:
        return "SELECT COUNT(*) AS invoice_count FROM bill_invoice_detail"

    if any(word in lowered for word in ("count", "how many", "number of")) and "account" in lowered:
        return "SELECT COUNT(*) AS account_count FROM accounts"

    if "transaction" in lowered or "payment" in lowered:
        return (
            "SELECT a.acc_id, a.account_status, t.txn_date, t.txn_type, t.amount "
            "FROM accounts a JOIN transactions t ON a.acc_id = t.acc_id "
            "ORDER BY t.txn_date DESC LIMIT 100"
        )

    if role == "compliance_officer" and any(word in lowered for word in ("phone", "address", "name")):
        return (
            "SELECT c.acc_id, c.full_name, c.phone_number, c.address "
            "FROM customer_pii c ORDER BY c.acc_id LIMIT 100"
        )

    if "region" in lowered or "status" in lowered:
        return "SELECT region, account_status, COUNT(*) AS account_count FROM accounts GROUP BY region, account_status ORDER BY account_count DESC LIMIT 100"

    return "NO_VALID_QUERY"


def generate_sql(question: str, role: str, schema_context: str, llm: Any | None = None) -> str:
    if llm is None:
        llm = build_llm()

    if llm is None:
        return generate_sql_with_fallback(question, schema_context, role)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        return generate_sql_with_fallback(question, schema_context, role)

    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT.format(schema_context=schema_context, user_question=question)),
            HumanMessage(content=question),
        ]
    )
    return strip_sql_fences(getattr(response, "content", str(response)))


def summarize_rows(question: str, rows: list[dict[str, Any]], sql: str, llm: Any | None = None) -> str:
    if not rows:
        return "No rows matched the query."

    first_row = rows[0]
    sample_bits = ", ".join(f"{key}={value}" for key, value in list(first_row.items())[:4])
    return f"Returned {len(rows)} row(s). Sample: {sample_bits}."


def open_readonly_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    resolved = Path(db_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Database not found at {resolved}. Run db/seed_data.py first.")
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def execute_query(connection: sqlite3.Connection, sql: str, limit: int = 100) -> list[dict[str, Any]]:
    limited_sql = enforce_row_limit(sql, limit=limit)
    rows = connection.execute(limited_sql).fetchall()
    return [dict(row) for row in rows]


def run_pipeline(
    question: str,
    *,
    role: str = "analyst",
    db_path: str | Path = DEFAULT_DB_PATH,
    llm: Any | None = None,
) -> QueryState:
    state: QueryState = {"question": question, "role": role}
    state["intent"] = classify_intent(question)
    relevant_tables = select_relevant_tables(question)
    state["relevant_tables"] = relevant_tables
    state["schema_context"] = format_schema_context(relevant_tables)
    state["context_explanation"] = explain_table_selection(question, relevant_tables)

    if state["intent"] != "read_query":
        state["generated_sql"] = "NO_VALID_QUERY"
        state["guardrail_verdict"] = GuardrailVerdict(False, f"Query intent classified as {state['intent']}.")
        state["summary"] = "Query blocked before SQL generation."
        return state

    generated_sql = generate_sql(question, role, state["schema_context"], llm=llm)
    state["generated_sql"] = generated_sql
    verdict = validate_sql(generated_sql, role=role)
    state["guardrail_verdict"] = verdict

    if not verdict.allowed:
        state["summary"] = verdict.reason
        with sqlite3.connect(db_path) as connection:
            log_event(
                connection,
                role=role,
                user_question=question,
                intent=state["intent"],
                generated_sql=generated_sql,
                verdict=verdict,
                result_preview=[],
            )
        return state

    with open_readonly_connection(db_path) as connection:
        rows = execute_query(connection, generated_sql)
    state["rows"] = rows
    state["summary"] = summarize_rows(question, rows, generated_sql, llm=llm)

    with sqlite3.connect(db_path) as connection:
        log_event(
            connection,
            role=role,
            user_question=question,
            intent=state["intent"],
            generated_sql=generated_sql,
            verdict=verdict,
            result_preview=rows[:5],
        )
    return state


def build_graph(llm: Any | None = None):
    if StateGraph is None:
        raise RuntimeError("langgraph is not installed. Install requirements.txt first.")

    graph = StateGraph(QueryState)

    def intent_check(state: QueryState) -> QueryState:
        state["intent"] = classify_intent(state["question"])
        return state

    def schema_context_builder(state: QueryState) -> QueryState:
        state["schema_context"] = format_schema_context(select_relevant_tables(state["question"]))
        return state

    def generate_sql_node(state: QueryState) -> QueryState:
        state["generated_sql"] = generate_sql(state["question"], state["role"], state["schema_context"], llm=llm)
        return state

    def guardrail_node(state: QueryState) -> QueryState:
        state["guardrail_verdict"] = validate_sql(state["generated_sql"], role=state["role"])
        return state

    def execute_query_node(state: QueryState) -> QueryState:
        with open_readonly_connection(DEFAULT_DB_PATH) as connection:
            state["rows"] = execute_query(connection, state["generated_sql"])
        return state

    def summary_node(state: QueryState) -> QueryState:
        state["summary"] = summarize_rows(state["question"], state.get("rows", []), state["generated_sql"], llm=llm)
        return state

    graph.add_node("intent_check", intent_check)
    graph.add_node("schema_context_builder", schema_context_builder)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("guardrail_check", guardrail_node)
    graph.add_node("execute_query", execute_query_node)
    graph.add_node("summarize_results", summary_node)

    graph.set_entry_point("intent_check")
    graph.add_edge("intent_check", "schema_context_builder")
    graph.add_edge("schema_context_builder", "generate_sql")
    graph.add_edge("generate_sql", "guardrail_check")
    graph.add_conditional_edges(
        "guardrail_check",
        lambda state: "execute_query" if state["guardrail_verdict"].allowed else END,
        {"execute_query": "execute_query", END: END},
    )
    graph.add_edge("execute_query", "summarize_results")
    graph.add_edge("summarize_results", END)
    return graph.compile()
