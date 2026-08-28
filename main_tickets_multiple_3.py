# # =======================================================================================================
# ### Working RAG using CSV. CSV is more efficient than a call to the DB each time the page is refreshed.
# ### v2 - Fixes for multi-user concurrency:
# ###   1. threading.Lock() around CSV refresh to prevent concurrent writes
# ###   2. Per-session SQLite connections to avoid shared connection locking
# ###   3. Agent created per-session (not shared via cache_resource)
# # =======================================================================================================

# import re
# import threading
# import streamlit as st
# import pandas as pd
# import os
# import time
# from sqlalchemy import create_engine, text
# from sqlalchemy.pool import StaticPool
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
# from langchain_openai import ChatOpenAI
# from langchain_openrouter import ChatOpenRouter
# from sql_data_tickets import query_tickets
# from dotenv import load_dotenv

# load_dotenv()

# # --- CONFIGURATION ---
# CSV_FILE = "kace_tickets.csv"
# REFRESH_INTERVAL = 6 * 3600  # 6 hours in seconds
# st.set_page_config(page_title="KACE Asset AI (Ticket Knowledge Base)", layout="wide")

# # --- GLOBAL LOCK: prevents concurrent CSV refresh writes ---
# _csv_refresh_lock = threading.Lock()

# # --- HELPER FUNCTIONS ---
# def needs_csv_refresh(csv_path: str, interval: int) -> bool:
#     """Check if the CSV needs refreshing (missing or older than interval)."""
#     if not os.path.exists(csv_path):
#         return True
#     last_modified = os.path.getmtime(csv_path)
#     return (time.time() - last_modified) > interval

# def refresh_csv():
#     """
#     Run KACE query, normalize data, and overwrite the CSV file.
#     Uses a threading lock so only one session refreshes at a time.
#     Other sessions that arrive during a refresh will skip and use the existing CSV.
#     """
#     # Try to acquire the lock without blocking other sessions indefinitely
#     acquired = _csv_refresh_lock.acquire(blocking=True, timeout=60)
#     if not acquired:
#         st.warning("CSV refresh is already in progress by another session. Using existing data.")
#         return

#     try:
#         # Double-check after acquiring lock — another session may have just refreshed
#         if not needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
#             return  # Already refreshed by the session that held the lock

#         DB_USER = os.environ.get("DB_USER")
#         DB_PASS = os.environ.get("DB_PASS")
#         DB_HOST = os.environ.get("DB_HOST")
#         DB_NAME = os.environ.get("DB_NAME")

#         kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")

#         with kace_engine.connect() as conn:
#             df = pd.read_sql(text(query_tickets.replace("%", "%%")), conn)

#         # --- NORMALIZE DATA ---
#         new_cols = [c.replace(' ', '_').lower() for c in df.columns]
#         new_cols = [re.sub(r'[^a-z0-9_]', '', c) for c in new_cols]
#         df.columns = [c.replace('__', '_').strip('_') for c in new_cols]

#         cost_col = next((c for c in df.columns if 'cost' in c), None)
#         if cost_col:
#             df[cost_col] = df[cost_col].replace(r'[^\d.]', '', regex=True)
#             df[cost_col] = pd.to_numeric(df[cost_col], errors='coerce').fillna(0.0)

#         for col in df.select_dtypes(include=['object']).columns:
#             df[col] = df[col].astype(str).str.lower().str.strip()

#         # Write to a temp file first, then rename — prevents corrupt reads mid-write
#         tmp_file = CSV_FILE + ".tmp"
#         df.to_csv(tmp_file, index=False)
#         os.replace(tmp_file, CSV_FILE)

#     finally:
#         _csv_refresh_lock.release()

# # --- CSV REFRESH ON STARTUP ---
# if needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
#     st.info("CSV data is stale. Refreshing from KACE database...")
#     refresh_csv()
#     st.success("CSV data refreshed successfully.")

# # --- CACHED CSV LOAD (shared across sessions — read-only, safe) ---
# @st.cache_data(ttl=REFRESH_INTERVAL)
# def load_csv() -> pd.DataFrame:
#     """
#     Load and return the normalized CSV as a DataFrame.
#     Cached with TTL matching the refresh interval.
#     This is read-only so it's safe to share across sessions.
#     """
#     raw_df = pd.read_csv(CSV_FILE)
#     for col in raw_df.select_dtypes(include=['object']).columns:
#         raw_df[col] = raw_df[col].astype(str).str.strip()
#     return raw_df

# # --- PER-SESSION DB + AGENT SETUP ---
# def get_session_db_and_agent():
#     """
#     Creates a fresh SQLite DB and SQL agent for this specific user session.
#     Stored in st.session_state so each user has their own isolated connection.
#     This avoids SQLite locking issues under concurrent load.
#     """
#     raw_df = load_csv()

#     # StaticPool ensures all connections (to_sql AND SQLDatabase) share the exact
#     # same in-memory SQLite instance. Without this, each new connection gets a fresh
#     # empty DB and the table written by to_sql is invisible to the agent.
#     session_engine = create_engine(
#         "sqlite:///:memory:",
#         connect_args={"check_same_thread": False},
#         poolclass=StaticPool,
#     )

#     # Write the ticket data into the shared in-memory DB
#     raw_df.to_sql("kace_tickets", session_engine, index=False, if_exists="replace")

#     # Sanity check — confirm the table is actually visible before handing to agent
#     with session_engine.connect() as conn:
#         result = conn.execute(text("SELECT COUNT(*) FROM kace_tickets")).fetchone()
#         row_count = result[0]
#     if row_count == 0:
#         raise RuntimeError("kace_tickets table was created but contains no rows. Check the CSV.")

#     db = SQLDatabase(session_engine)

#          # --- AGENT SETUP ---
#     # llm = ChatOllama(model="gemma4:e4b", temperature=0) ## Really good local model... But still some mistakes if query is complex ###******************************************
#     # llm = ChatOllama(model="gemma4:e2b", temperature=0) ## NOT SO GOOD. GOT MISTAKES
#     # llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)  ## Works!
#     # llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0) ### Really good GPT model - BEST VALUE FOR MONEY
#     # llm = ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0)
#     # llm = ChatOpenRouter(model="openai/gpt-oss-120b", temperature=0)  ### SO FAR... REALLY GOOD!!! BEST LOCALLYAND CHEAP....!!!
#     llm = ChatOpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")

#     system_prompt = """
# You are an expert KACE SMA data analyst and a friendly assistant.
# The database 'kace_tickets' is fully normalized to lowercase.
# All string-based values and column names are in lowercase.
# Always use the column names exactly as they appear in the schema (using underscores).

# When a user asks for a count of tickets in a specific queue, translate the question into a SQL COUNT query that filters on the queue_name column.
# Normalize the queue name in the user's question (lowercase, trim whitespace) before comparing it to the stored values.
# Provide the count result after executing the query.
# When the user asks about the 'requisition queue', this is a reference to the tickets with queue_name = 'ALL JBN: IT-REQUISITION'.
# When the user asks about the 'support queue', this is a reference to the tickets with queue_name = 'ALL JBN : REQUEST IT SUPPORT HELP'.

# If the user greets you (e.g., "hi", "hello", "hey", "good morning"), respond with a friendly greeting and ask how you can help them with ticket data. Do NOT try to query the database for greetings.
# If the user asks something unrelated to the ticket data, politely let them know you specialize in KACE ticket analysis.
# """

#     agent_executor = create_sql_agent(
#         llm=llm,
#         db=db,
#         verbose=True,
#         agent_type="openai-tools",
#         suffix=system_prompt
#     )

#     return agent_executor

# # --- INITIALIZE SESSION STATE ---
# if "messages" not in st.session_state:
#     st.session_state.messages = []

# # Each session gets its own agent — created once per session, reused across queries
# if "agent_executor" not in st.session_state:
#     with st.spinner("Initializing your session..."):
#         st.session_state.agent_executor = get_session_db_and_agent()

# # --- CHAT UI ---
# st.title("🛡️  KACE SMA Intelligence Portal (Tickets Knowledge Base)")

# # Display chat history
# for message in st.session_state.messages:
#     with st.chat_message(message["role"]):
#         st.markdown(message["content"])

# # --- USER INTERACTION ---
# if prompt := st.chat_input("Ask about tickets (e.g., How many open tickets are in the support queue?)"):
#     st.session_state.messages.append({"role": "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     with st.chat_message("assistant"):
#         normalized_query = prompt.lower().strip()
#         with st.spinner("Querying the database... please wait ⏳"):
#             try:
#                 response = st.session_state.agent_executor.invoke({"input": normalized_query})
#                 answer = response["output"]
#             except Exception as e:
#                 answer = f"⚠️ Something went wrong processing your request: {str(e)}"
#         st.markdown(answer)

#     st.session_state.messages.append({"role": "assistant", "content": answer})



# ### Questions

# ###  how many tickets have a title containing "VPN" ?  ✅
# ###  how many tickets have a title containing "vpn" in the first quarter of 2026?  ✅
# ###  how many tickts do we have? ✅
# ###  how many queues do we have? ✅
# ###  how many tickets did we have in the first quarter of 2026? ✅
# ###  how many tickets in the queue 'all jbn : request it support help' did we have in the first quarter of 2026? ✅
# ###  how many tickets in the queue 'all jbn: it-requisition' did we have in the first quarter of 2026? ✅

# ###  how many tickets in the queue 'all jbn : request it support help'? ✅
# ###  how many tickets did we have in each queue , in january 2026? ✅

# ### how many tickets in the support queue did we have in the first quarter of 2026?
# ### There are 36 tickets with “login” in the title in 2026. ✅













##############################################################################################################################
##############################################################################################################################
##############################################################################################################################
##############################################################################################################################
##############################################################################################################################
#### More optoimized code. Does not refresh csv on every user interaction. which apparently the previous one did ////////////


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
st.set_page_config(page_title="KACE Asset AI (Ticket Knowledge Base)", layout="wide")

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
    # Try to acquire the lock without blocking other sessions indefinitely
    acquired = _csv_refresh_lock.acquire(blocking=True, timeout=60)
    if not acquired:
        st.warning("CSV refresh is already in progress by another session. Using existing data.")
        return

    try:
        # Double-check after acquiring lock — another session may have just refreshed
        if not needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
            return  # Already refreshed by the session that held the lock

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

        # Write to a temp file first, then rename — prevents corrupt reads mid-write
        tmp_file = CSV_FILE + ".tmp"
        df.to_csv(tmp_file, index=False)
        os.replace(tmp_file, CSV_FILE)

    finally:
        _csv_refresh_lock.release()

# --- CSV REFRESH ON STARTUP ---
# st.cache_resource runs once per app process lifetime, not once per script rerun.
# This is the correct place for a one-time startup side effect in Streamlit.
# The dummy return value is irrelevant — the side effect (CSV refresh) is what matters.
@st.cache_resource
def _startup_csv_check():
    """Runs once when the app process starts. Never reruns on user interaction."""
    if needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
        refresh_csv()
        return "refreshed"
    return "ok"

_startup_result = _startup_csv_check()
if _startup_result == "refreshed":
    st.info("CSV data was stale on startup — refreshed from KACE database. ✅")

# --- CACHED CSV LOAD (shared across sessions — read-only, safe) ---
@st.cache_data(ttl=REFRESH_INTERVAL)
def load_csv() -> pd.DataFrame:
    """
    Load and return the normalized CSV as a DataFrame.
    Cached with TTL matching the refresh interval.
    This is read-only so it's safe to share across sessions.
    """
    raw_df = pd.read_csv(CSV_FILE)
    for col in raw_df.select_dtypes(include=['object']).columns:
        raw_df[col] = raw_df[col].astype(str).str.strip()
    return raw_df

# --- PER-SESSION DB + AGENT SETUP ---
def get_session_db_and_agent():
    """
    Creates a fresh SQLite DB and SQL agent for this specific user session.
    Stored in st.session_state so each user has their own isolated connection.
    This avoids SQLite locking issues under concurrent load.
    """
    raw_df = load_csv()

    # StaticPool ensures all connections (to_sql AND SQLDatabase) share the exact
    # same in-memory SQLite instance. Without this, each new connection gets a fresh
    # empty DB and the table written by to_sql is invisible to the agent.
    session_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Write the ticket data into the shared in-memory DB
    raw_df.to_sql("kace_tickets", session_engine, index=False, if_exists="replace")

    # Sanity check — confirm the table is actually visible before handing to agent
    with session_engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM kace_tickets")).fetchone()
        row_count = result[0]
    if row_count == 0:
        raise RuntimeError("kace_tickets table was created but contains no rows. Check the CSV.")

    db = SQLDatabase(session_engine)

             ## --- AGENT SETUP ---
    # llm = ChatOllama(model="gemma4:e4b", temperature=0) ## Really good local model... But still some mistakes if query is complex ###******************************************
    # llm = ChatOllama(model="gemma4:e2b", temperature=0) ## NOT SO GOOD. GOT MISTAKES
    # llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)  ## Works!
    # llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0) ### Really good GPT model - BEST VALUE FOR MONEY and FAST!! MT FAV!!!!! 👍👍👍👍👍
    # llm = ChatOpenRouter(model="gpt-5.4-mini", temperature=0) ### Really good GPT model - BEST VALUE FOR MONEY and FAST!! Open router version of above *********
    # llm = ChatOpenRouter(model="gpt-5.6-luna", temperature=0) ### Really good GPT model - Greatest VALUE FOR MONEY and FAST & CHEAP!!
    # llm = ChatOpenRouter(model="google/gemini-3.7-flash", temperature=0) ### Really good GPT model - Greatest VALUE FOR MONEY and FAST & CHEAP!!
    # llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none") ### ????? seem to be having api issues and errors...'👎❌❌
    # llm = ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0)
    llm = ChatOpenRouter(model="~deepseek/deepseek-v4-flash-latest", temperature=0)  ## always redirects to latest deepseek flash model 
    # llm = ChatOpenRouter(model="openai/gpt-oss-120b", temperature=0)  ### SO FAR... REALLY GOOD!!! BEST  AND CHEAP....!!!  
    # llm = ChatOpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio", model="openai/gpt-oss-20b", temperature=0) ## Using model LOCALLY in lmstudio.. GOOD, FAST!!!

    system_prompt = system_prompt = """
    You are an expert KACE SMA data analyst and a friendly assistant.
    The database table is named 'kace_tickets' and is fully normalized to lowercase.
    All string-based values and column names are in lowercase with underscores.
    Always use column names exactly as they appear in the schema.

    ## STATUS FIELD MAPPINGS
    The 'status_name' column contains these exact values: 'opened', 'closed', 'pending', 'reopened', 'New'
    (replace this list with whatever your actual DB contains)

    Map user language as follows:
    - "closed", "resolved", "done", "completed", "finished" → use: status_name = 'closed'
    - "open", "not closed", "active", "unresolved", "in progress", "still open", "outstanding", "New"
    → use: status_name != 'closed'
    → This MUST include ALL non-closed statuses: opened, pending, reopened, etc.
    → ALWAYS write this as: WHERE status_name != 'closed'  (never just = 'opened')
    - "pending" → use: status_name = 'pending'
    - "reopened" → use: status_name = 'reopened'
    - "New" → use: status_name = 'New'

    Remember:
    When the user asks about the 'requisition queue', this is a reference to the tickets in the 'ALL JBN: IT-REQUISITION' queue.
    When the user asks about the 'support queue', this is a reference to the tickets in the 'ALL JBN : REQUEST IT SUPPORT HELP' queue.

    CRITICAL: Never equate "open" with only status_name = 'opened'. 
    Any ticket that is not 'closed' counts as open unless the user asks for a specific status.

    ## QUEUE MAPPINGS:
    The 'queue_name' column contains these queues (always match case-insensitively):
    - "support queue", "support tickets", "help desk" → 'all jbn : request it support help'
    - "requisition queue", "it requisition", "requisition tickets" → 'all jbn: it-requisition'

    ## PRIORITY MAPPINGS:
    The 'priority' column uses: 'high', 'medium', 'low'
    - "urgent", "critical" → 'high'
    - "normal", "standard" → 'medium'
    - "minor", "low priority" → 'low'

    ## CATEGORY / LOCATION HINTS
    - The 'category_text' column contains values like 'abuja-hq', 'abuja::internet', 'abuja::network', 'lagos::software'
    - When users ask about a location/site, filter on category_text using LIKE '%location%'

    ## DATE & TIME
    - 'created' = ticket open/submission timestamp
    - 'time_closed' = when ticket was resolved/closed
    - For duration/resolution time: use julianday(time_closed) - julianday(created)
    - "this week", "last month", etc → translate to appropriate date filters on 'created'
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
        # agent_type="openai-tools",
        agent_type="tool-calling",  ##  "tool-calling"  is recommended in the documentation over the legacy "openai-tools"
        suffix=system_prompt
    )

    return agent_executor

# --- INITIALIZE SESSION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Each session gets its own agent — created once per session, reused across queries
if "agent_executor" not in st.session_state:
    with st.spinner("Initializing your session..."):
        st.session_state.agent_executor = get_session_db_and_agent()

# --- CHAT UI ---
st.title("🛡️  KACE SMA Intelligence Portal (Tickets Knowledge Base)")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- USER INTERACTION ---
if prompt := st.chat_input("Ask about tickets (e.g., How many open tickets are in the support queue?)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        normalized_query = prompt.lower().strip()
        with st.spinner("Thinking... please wait ⏳"):
            try:
                response = st.session_state.agent_executor.invoke({"input": normalized_query})
                answer = response["output"]
            except Exception as e:
                answer = f"⚠️ Something went wrong processing your request: {str(e)}"
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})


# ### Questions

# ###  how many tickets have a title containing "VPN" ?  ✅
# ###  how many tickets have a title containing "vpn" in the first quarter of 2026?  ✅
# ###  how many tickets have a title containing "vpn" in january of 2026?  ✅  ?????
# ###  how many tickts do we have? ✅
# ###  how many queues do we have? ✅
# ###  how many tickets did we have in the first quarter of 2026? ✅
# ###  how many tickets in the queue 'all jbn : request it support help' did we have in the first quarter of 2026? ✅
# ###  how many tickets in the queue 'all jbn: it-requisition' did we have in the first quarter of 2026? ✅

# ###  how many tickets in the queue 'all jbn : request it support help'? ✅
# ###  how many tickets did we have in each queue , in january 2026? ✅
# ###  what are the available column to search in the queues?✅

# ### how many tickets in the support queue did we have in the first quarter of 2026?

# ### how many tickets are still open in each queue? ✅
# ### how many tickets have a status of pending in the support queue?  ✅``
# ## how many tickets do we have between april 1st 2026 and june 30th 2026? Break it down by queues.
# ## how many tickets did the owner "kabir, amin" get in 2026?
# ## how many tickets do we have between april 1st 2026 and june 30th 2026? Break it down by queues. From the requisition queue, count only tickets with [\*r\*] in the title.

# ## how many tickets did the owner containing "kabir", get in 2026?

