# =======================================================================================================
### Working RAG using CSV. CSV is more efficient than a call to the DB each time the page is refreshed.
### v2 - Fixes for multi-user concurrency:
###   1. threading.Lock() around CSV refresh to prevent concurrent writes
###   2. Per-session SQLite connections to avoid shared connection locking
###   3. Agent created per-session (not shared via cache_resource)
# =======================================================================================================

import re
import threading
import streamlit as st
import pandas as pd
import os
import time
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
from sql_data_tickets import query_tickets
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
CSV_FILE = "kace_tickets.csv"
REFRESH_INTERVAL = 6 * 3600  # 6 hours in seconds

# --- GLOBAL LOCK: prevents concurrent CSV refresh writes ---
_csv_refresh_lock = threading.Lock()

# --- HELPER FUNCTIONS ---
def needs_csv_refresh(csv_path: str, interval: int) -> bool:
    """Check if the CSV needs refreshing (missing or older than interval)."""
    if not os.path.exists(csv_path):
        return True
    last_modified = os.path.getmtime(csv_path)
    return (time.time() - last_modified) > interval

def refresh_csv():
    """
    Run KACE query, normalize data, and overwrite the CSV file.
    Uses a threading lock so only one session refreshes at a time.
    Other sessions that arrive during a refresh will skip and use the existing CSV.
    """
    acquired = _csv_refresh_lock.acquire(blocking=True, timeout=60)
    if not acquired:
        st.warning("CSV refresh is already in progress by another session. Using existing data.")
        return

    try:
        if not needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
            return

        DB_USER = os.environ.get("DB_USER")
        DB_PASS = os.environ.get("DB_PASS")
        DB_HOST = os.environ.get("DB_HOST")
        DB_NAME = os.environ.get("DB_NAME")

        kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")

        with kace_engine.connect() as conn:
            df = pd.read_sql(text(query_tickets.replace("%", "%%")), conn)

        # --- NORMALIZE DATA ---
        new_cols = [c.replace(' ', '_').lower() for c in df.columns]
        new_cols = [re.sub(r'[^a-z0-9_]', '', c) for c in new_cols]
        df.columns = [c.replace('__', '_').strip('_') for c in new_cols]

        cost_col = next((c for c in df.columns if 'cost' in c), None)
        if cost_col:
            df[cost_col] = df[cost_col].replace(r'[^\d.]', '', regex=True)
            df[cost_col] = pd.to_numeric(df[cost_col], errors='coerce').fillna(0.0)

        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.lower().str.strip()

        tmp_file = CSV_FILE + ".tmp"
        df.to_csv(tmp_file, index=False)
        os.replace(tmp_file, CSV_FILE)

    finally:
        _csv_refresh_lock.release()


# --- CACHED CSV LOAD (shared across sessions — read-only, safe) ---
@st.cache_data(ttl=REFRESH_INTERVAL)
def load_tickets_csv() -> pd.DataFrame:
    """Load and return the normalized CSV as a DataFrame."""
    raw_df = pd.read_csv(CSV_FILE)
    for col in raw_df.select_dtypes(include=['object']).columns:
        raw_df[col] = raw_df[col].astype(str).str.strip()
    return raw_df


# --- PER-SESSION DB + AGENT SETUP ---
def get_session_db_and_agent():
    """
    Creates a fresh SQLite DB and SQL agent for this specific user session.
    Stored in st.session_state so each user has their own isolated connection.
    """
    raw_df = load_tickets_csv()

    session_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    raw_df.to_sql("kace_tickets", session_engine, index=False, if_exists="replace")

    with session_engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM kace_tickets")).fetchone()
        row_count = result[0]
    if row_count == 0:
        raise RuntimeError("kace_tickets table was created but contains no rows. Check the CSV.")

    db = SQLDatabase(session_engine)

    llm = ChatOpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio", model="openai/gpt-oss-20b", temperature=0)

    system_prompt = """
    You are an expert KACE SMA data analyst and a friendly assistant.
    The database table is named 'kace_tickets' and is fully normalized to lowercase.
    All string-based values and column names are in lowercase with underscores.
    Always use column names exactly as they appear in the schema.

    ## STATUS FIELD MAPPINGS
    The 'status_name' column contains these exact values: 'opened', 'closed', 'pending', 'reopened', 'New'

    Map user language as follows:
    - "closed", "resolved", "done", "completed", "finished" -> use: status_name = 'closed'
    - "open", "not closed", "active", "unresolved", "in progress", "still open", "outstanding", "New"
    -> use: status_name != 'closed'
    -> This MUST include ALL non-closed statuses: opened, pending, reopened, etc.
    -> ALWAYS write this as: WHERE status_name != 'closed'  (never just = 'opened')
    - "pending" -> use: status_name = 'pending'
    - "reopened" -> use: status_name = 'reopened'
    - "New" -> use: status_name = 'New'

    Remember:
    When the user asks about the 'requisition queue', this is a reference to the tickets in the 'ALL JBN: IT-REQUISITION' queue.
    When the user asks about the 'support queue', this is a reference to the tickets in the 'ALL JBN : REQUEST IT SUPPORT HELP' queue.

    CRITICAL: Never equate "open" with only status_name = 'opened'.
    Any ticket that is not 'closed' counts as open unless the user asks for a specific status.

    ## QUEUE MAPPINGS:
    The 'queue_name' column contains these queues (always match case-insensitively):
    - "support queue", "support tickets", "help desk" -> 'all jbn : request it support help'
    - "requisition queue", "it requisition", "requisition tickets" -> 'all jbn: it-requisition'

    ## PRIORITY MAPPINGS:
    The 'priority' column uses: 'high', 'medium', 'low'
    - "urgent", "critical" -> 'high'
    - "normal", "standard" -> 'medium'
    - "minor", "low priority" -> 'low'

    ## CATEGORY / LOCATION HINTS
    - The 'category_text' column contains values like 'abuja-hq', 'abuja::internet', 'abuja::network', 'lagos::software'
    - When users ask about a location/site, filter on category_text using LIKE '%location%'

    ## DATE & TIME
    - 'created' = ticket open/submission timestamp
    - 'time_closed' = when ticket was resolved/closed
    - For duration/resolution time: use julianday(time_closed) - julianday(created)
    - "this week", "last month", etc -> translate to appropriate date filters on 'created'
    - Both columns are in format: 'YYYY-MM-DD HH:MM:SS'

    ## COLUMN REFERENCE
    - queue_name: which queue the ticket belongs to
    - title: short description of the issue
    - created: when the ticket was submitted
    - time_closed: when the ticket was closed (may be empty if still open)
    - status_name: current status ('opened' or 'closed' or 'Pending' or 'Reopened' or 'New')
    - system_name: system/device identifier
    - asset_name: asset tag
    - category_text: location/category of the ticket
    - submitter_name: person who submitted the ticket
    - owner_name: person responsible for resolving it
    - priority: ticket priority level

    ## BEHAVIOR RULES
    1. ALWAYS translate natural language status terms to exact DB values before querying.
    2. If the user greets you (hi, hello, hey, good morning), respond warmly and ask how you can help with ticket data. Do NOT query the database.
    3. If the question is unrelated to ticket/asset data, politely explain you specialize in KACE ticket analysis.
    4. When asked for counts by queue, always GROUP BY queue_name unless a specific queue is mentioned.
    5. For open ticket counts, always use: WHERE status_name = 'opened'
    6. For ambiguous queries, state your assumption (e.g., "Interpreting 'open' as status_name = 'opened'...") before showing the result.
    7. Always present results in a clear, readable format. For tables, describe them in markdown.
    8. If a query returns 0 results, say so clearly and suggest the user may want to check spelling or rephrase.
    """

    agent_executor = create_sql_agent(
        llm=llm,
        db=db,
        verbose=True,
        agent_type="openai-tools",
        suffix=system_prompt
    )

    return agent_executor


PAGE_ID = "tickets"


def render():
    # --- CSV REFRESH ON STARTUP (runs once per app process lifetime) ---
    if "tickets_csv_checked" not in st.session_state:
        if needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
            refresh_csv()
            st.info("CSV data was stale on startup - refreshed from KACE database.")
        st.session_state.tickets_csv_checked = True

    # --- NAVIGATION DETECTION: reload fresh when arriving from another page ---
    if st.session_state.get("active_page") != PAGE_ID:
        for key in ["tickets_messages", "tickets_agent"]:
            st.session_state.pop(key, None)
        st.session_state.active_page = PAGE_ID

    # --- INITIALIZE SESSION STATE ---
    if "tickets_messages" not in st.session_state:
        st.session_state.tickets_messages = []

    if "tickets_agent" not in st.session_state:
        with st.spinner("Initializing your session..."):
            st.session_state.tickets_agent = get_session_db_and_agent()

    # --- CHAT UI ---
    st.title("KACE SMA Intelligence Portal (Tickets Knowledge Base)")

    for message in st.session_state.tickets_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask about tickets (e.g., How many open tickets are in the support queue?)"):
        st.session_state.tickets_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            normalized_query = prompt.lower().strip()
            with st.spinner("Thinking... please wait"):
                try:
                    response = st.session_state.tickets_agent.invoke({"input": normalized_query})
                    answer = response["output"]
                except Exception as e:
                    answer = f"Something went wrong processing your request: {str(e)}"
            st.markdown(answer)

        st.session_state.tickets_messages.append({"role": "assistant", "content": answer})