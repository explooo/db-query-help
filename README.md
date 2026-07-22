# Ask Your Billing DB

Natural-language-to-SQL demo for a mock banking and telecom billing database with guardrails, role-based access control, and audit logging.

## What is in place

- SQLite schema and synthetic seed data
- Static SQL guardrails
- Audit logging
- Optional Google AI Studio/LangGraph integration
- Streamlit demo UI

## Quick start

1. Create a virtual environment and install dependencies from `requirements.txt`.
2. Create a .env file with `GOOGLE_API_KEY=` for optional Gemini connection.
3. 3. Seed the database:

```bash
python db/seed_data.py
```

4. Start the app:

```bash
streamlit run app.py
```

## Notes

- The analyst role cannot query `customer_pii` columns.
- The database layer always wraps query execution with a hard row limit.
- `db/seed_data.py` creates intentionally messy staging rows so the demo has realistic edge cases.
