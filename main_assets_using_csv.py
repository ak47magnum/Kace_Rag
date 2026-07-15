
# # =======================================================================================================
# ### Working rag using CSV. Using CSV More efficient than a call to the db each time the page is refreshed
# # =======================================================================================================

# import re
# import streamlit as st
# import pandas as pd
# import os
# import time
# from sqlalchemy import create_engine, text
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
# from langchain_openai import ChatOpenAI
# from sql_data_assets import sql_query
# from dotenv import load_dotenv

# load_dotenv()

# # --- CONFIGURATION ---
# CSV_FILE = "kace_assets.csv"
# REFRESH_INTERVAL = 6 * 3600  # 6 hours in seconds
# st.set_page_config(page_title="KACE Asset AI (Knowledge Base)", layout="wide")

# # --- HELPER FUNCTIONS ---
# def needs_csv_refresh(csv_path: str, interval: int) -> bool:
#     """Check if the CSV needs refreshing (missing or older than interval)."""
#     if not os.path.exists(csv_path):
#         return True
#     last_modified = os.path.getmtime(csv_path)
#     return (time.time() - last_modified) > interval

# def refresh_csv():
#     """Run KACE query, normalize data, and overwrite the CSV file."""
#     # Connect to KACE DB using env vars
#     DB_USER = os.environ.get("DB_USER")
#     DB_PASS = os.environ.get("DB_PASS")
#     DB_HOST = os.environ.get("DB_HOST")
#     DB_NAME = os.environ.get("DB_NAME")

#     kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")

#     # Extract data using the same query from sql_data.py
#     with kace_engine.connect() as conn:
#         df = pd.read_sql(text(sql_query.replace("%", "%%")), conn)

#     # --- NORMALIZE DATA (same as test_2.py) ---
#     # Clean column names (lowercase, underscores, no special chars)
#     new_cols = [c.replace(' ', '_').lower() for c in df.columns]
#     new_cols = [re.sub(r'[^a-z0-9_]', '', c) for c in new_cols]
#     df.columns = [c.replace('__', '_').strip('_') for c in new_cols]

#     # Clean cost column (remove symbols, convert to numeric)
#     cost_col = next((c for c in df.columns if 'cost' in c), None)
#     if cost_col:
#         df[cost_col] = df[cost_col].replace(r'[^\d.]', '', regex=True)
#         df[cost_col] = pd.to_numeric(df[cost_col], errors='coerce').fillna(0.0)

#     # Lowercase all string data for case-insensitive matching
#     for col in df.select_dtypes(include=['object']).columns:
#         df[col] = df[col].astype(str).str.lower()

#     # Overwrite the existing CSV file
#     df.to_csv(CSV_FILE, index=False)
#     return df

# # --- DATA LOADING (CSV-backed) ---
# # Check if CSV needs refresh on app start
# if needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
#     st.info("CSV data is stale. Refreshing from KACE database...")
#     refresh_csv()
#     st.success("CSV data refreshed successfully.")

#     # # Clear cached DB if it exists (force reload from new CSV)  
#     # st.cache_resource.clear() ## claude says its not needed/

# @st.cache_resource
# def get_unified_db():
#     """Load data from CSV and create a SQLDatabase for the agent."""
#     # Read the normalized CSV (already cleaned by refresh_csv)
#     raw_df = pd.read_csv(CSV_FILE)

#     # Create local SQLite DB from CSV data (same as before, but data comes from CSV)
#     local_engine = create_engine("sqlite:///local_kace.db")
#     raw_df.to_sql("kace_assets", local_engine, index=False, if_exists='replace')

#     return SQLDatabase(local_engine), raw_df

# # Initialize data
# try:
#     db, raw_df = get_unified_db()
# except FileNotFoundError:
#     st.error(f"CSV file {CSV_FILE} not found. Refreshing now...")
#     refresh_csv()
#     db, raw_df = get_unified_db()

# # --- CHAT UI (same as test_2.py) ---
# st.title("🛡️  KACE SMA Intelligence Portal (Knowledge Base)")

# if "messages" not in st.session_state:
#     st.session_state.messages = []

# # Display chat history
# for message in st.session_state.messages:
#     with st.chat_message(message["role"]):
#         st.markdown(message["content"])

# # --- AGENT SETUP ---
# # llm = ChatOllama(model="gemma4:e4b", temperature=0) ## Really good local model  ###************************************************************
# llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# system_prompt = """
# You are an expert KACE SMA data analyst.
# The database 'kace_assets' is fully normalized to lowercase.
# All string-based values and column names are in lowercase.
# Always use the column names exactly as they appear in the schema (using underscores).
# Note that when the user asks for 'Cost Account' or 'Cost Accounts', search the 'cost_account' column.
# When the user asks for 'Asset Name' or 'asset names', search the 'asset_name' column.
# when the user asks for 'Assigned User' or 'assigned users', search the 'assigned_user' column.
# Also when the user asks for user or users, search the 'assigned_user' column.
# Also when a user asks for 'Unit Cost' or 'cost', search the 'unit_cost' column.
# Search all columns for a match with the users search. Not only the 'Item' column.
# Also when asked about the count of email accounts, search the rows in the 'item' column for 'email account' or 'email accounts' 
# """

# agent_executor = create_sql_agent(
#     llm=llm,
#     db=db,
#     verbose=True,
#     agent_type="openai-tools",
#     suffix=system_prompt
# )

# # --- USER INTERACTION ---
# if prompt := st.chat_input("Ask about assets (e.g., How many assets in 11.0.001.00?)"):
#     st.session_state.messages.append({"role": "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     with st.chat_message("assistant"):
#         normalized_query = prompt.lower()
#         response = agent_executor.invoke({"input": normalized_query})
#         answer = response["output"]
#         st.markdown(answer)

#     st.session_state.messages.append({"role": "assistant", "content": answer})








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
from sql_data_assets import sql_query
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
CSV_FILE = "kace_assets.csv"
REFRESH_INTERVAL = 6 * 3600  # 6 hours in seconds
st.set_page_config(page_title="KACE Asset AI (Asset Knowledge Base)", layout="wide")

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
            df = pd.read_sql(text(sql_query.replace("%", "%%")), conn)

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
    raw_df.to_sql("kace_assets", session_engine, index=False, if_exists="replace")

    # Sanity check — confirm the table is actually visible before handing to agent
    with session_engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM kace_assets")).fetchone()
        row_count = result[0]
    if row_count == 0:
        raise RuntimeError("kace_assets table was created but contains no rows. Check the CSV.")

    db = SQLDatabase(session_engine)

             ## --- AGENT SETUP ---
    # llm = ChatOllama(model="gemma4:e4b", temperature=0) ## Really good local model... But still some mistakes if query is complex ###******************************************
    # llm = ChatOllama(model="gemma4:e2b", temperature=0) ## NOT SO GOOD. GOT MISTAKES
    # llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)  ## Works!
    # llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0) ### Really good GPT model - BEST VALUE FOR MONEY
    # llm = ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0)
    # llm = ChatOpenRouter(model="openai/gpt-oss-120b", temperature=0)  ### SO FAR... REALLY GOOD!!! BEST LOCALLY AND CHEAP....!!!  
    llm = ChatOpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio", model="openai/gpt-oss-20b", temperature=0)

######*******************************************************************************************************************************************************************
######*******************************************************************************************************************************************************************
######*******************************************************************************************************************************************************************
######*******************************************************************************************************************************************************************
    system_prompt = """
    You are an expert KACE SMA (Systems Management Appliance) data analyst with deep knowledge of IT asset management.
    You query a SQLite database called 'kace_assets' and return accurate, well-formatted answers.

    ═══════════════════════════════════════════════════════
                        DATABASE SCHEMA
    ═══════════════════════════════════════════════════════

    Table: kace_assets
    Columns:
    - item          TEXT    → The category/type of asset (e.g. 'computer', 'email account', 'jbn hand radio unit')
    - type          TEXT    → The specific subtype or model (e.g. 'pc', 'laptop', 'work station', 'low level pc')
    - id            TEXT    → The asset ID, usually in format "X###### / (last online: YYYY-MM-DD HH:MM:SS)"
    - assigned_user TEXT    → The username assigned to this asset (e.g. 'john.doe'), or 'none' if unassigned
    - unit_cost     INTEGER → The monetary cost of the asset in Nigerian Naira (NGN / ₦)
    - cost_account  TEXT    → The accounting/GL code the asset is charged to (e.g. '11.0.001.00')

    IMPORTANT: All string values are stored in LOWERCASE. Always use LOWER() when filtering text columns.

    ═══════════════════════════════════════════════════════
            DYNAMIC DATA — ALWAYS QUERY THE DATABASE
    ═══════════════════════════════════════════════════════

    NEVER hardcode or assume specific values for the following — always derive them live from the database:

    • Distinct item categories    → SELECT DISTINCT item FROM kace_assets ORDER BY item
    • Distinct asset subtypes     → SELECT DISTINCT type FROM kace_assets WHERE type IS NOT NULL ORDER BY type
    • Distinct cost accounts      → SELECT DISTINCT cost_account FROM kace_assets ORDER BY cost_account
    • Total row/asset count       → SELECT COUNT(*) FROM kace_assets
    • Cost range (min/max/avg)    → SELECT MIN(unit_cost), MAX(unit_cost), AVG(unit_cost) FROM kace_assets
    • Null/unassigned counts      → SELECT COUNT(*) FROM kace_assets WHERE assigned_user IS NULL OR assigned_user = 'none'
    • Count per item category     → SELECT item, COUNT(*) FROM kace_assets GROUP BY item ORDER BY COUNT(*) DESC
    • Count per cost account      → SELECT cost_account, COUNT(*) FROM kace_assets GROUP BY cost_account
    • Count per asset subtype     → SELECT type, COUNT(*) FROM kace_assets GROUP BY type ORDER BY COUNT(*) DESC

    If a user asks "what items exist?", "list all cost accounts", "what types of computers are there?", or any
    question about what values exist in the database — run the appropriate SELECT DISTINCT query above and
    return the live results. Do not answer from memory.

    ═══════════════════════════════════════════════════════
                COLUMN SYNONYM MAPPING
    ═══════════════════════════════════════════════════════

    When the user refers to any of the following terms, map them to the correct column:

    | User Says                                      | Column to Query                              |
    |------------------------------------------------|----------------------------------------------|
    | asset name, asset, asset names                 | item                                         |
    | item, items, category, categories              | item                                         |
    | type, subtype, model, spec, specification      | type                                         |
    | asset id, device id, machine id, id, ids       | id                                           |
    | hostname, device name, machine name            | id  (extract prefix before " /")             |
    | last online, last seen, last active, last sync | id  (extract date after "last online:")      |
    | user, users, assigned user, assigned to        | assigned_user                                |
    | who has, who is using, who owns                | assigned_user                                |
    | owner, owners                                  | assigned_user                                |
    | cost, price, value, amount                     | unit_cost                                    |
    | unit cost, unit price                          | unit_cost                                    |
    | cost account, cost accounts, account code      | cost_account                                 |
    | GL code, accounting code, charge code          | cost_account                                 |
    | department code, department account            | cost_account                                 |

    ═══════════════════════════════════════════════════════
                ITEM CATEGORY GUIDANCE
    ═══════════════════════════════════════════════════════

    The 'item' column holds the top-level asset category. The actual values in the database may grow
    or change over time — always use SELECT DISTINCT item to confirm current values. As a general guide,
    items tend to fall into these logical groups:

    Hardware      → physical devices (computers, screens, phones, radios, scanners, printers, iPads, etc.)
    Accounts      → digital access records (user accounts, email accounts, internet accounts)
    Software      → licences and application subscriptions (e.g. SAP, AutoCAD, Adobe, RIB iTWO)
    Other         → site fees, project records, or anything that does not fit the above

    When a user asks about a hardware device, account type, or software by a common name or synonym,
    map it to the closest matching item value using a LIKE or LOWER() comparison, then confirm with
    the user if the match is ambiguous.

        ⚠️  CRITICAL — PLURAL FORMS AND ITEM NAME AMBIGUITY:
    The user will often use plural or casual forms when referring to a specific item category stored
    in the 'item' column. You MUST strip the plural and map to the exact singular item value.
    NEVER interpret a plural noun as a request to count all rows — always check first whether it
    maps to a specific item category name.

    WRONG: "how many user accounts" → COUNT(*) with no item filter  (this counts ALL assets)
    RIGHT: "how many user accounts" → COUNT(*) WHERE LOWER(item) = 'user account'

    WRONG: "how many email accounts" → COUNT(*) with no item filter
    RIGHT: "how many email accounts" → COUNT(*) WHERE LOWER(item) = 'email account'

    WRONG: "how many internet accounts" → COUNT(*) with no item filter
    RIGHT: "how many internet accounts" → COUNT(*) WHERE LOWER(item) = 'internet account'

    The rule: if the user's noun (singular or plural) matches or closely resembles a known item
    category name, ALWAYS apply WHERE LOWER(item) = '<matched_item_value>' in the query.

    Examples of natural language → item mapping (singular AND plural forms, illustrative not exhaustive):
    "computer", "computers", "PC", "PCs", "laptop", "laptops",
    "desktop", "desktops", "workstation", "workstations"          → item = 'computer'

    "monitor", "monitors", "screen", "screens", "display"         → item = 'additional pc-screen'

    "walkie-talkie", "walkie-talkies", "handheld radio",
    "hand radio", "hand radios"                                   → item = 'jbn hand radio unit'

    "smartphone", "smartphones", "mobile phone", "mobile phones"  → item = 'jbn smartphones'

    "desk phone", "desk phones", "IP phone", "IP phones",
    "wired phone", "wired phones", "office phone"                 → item = 'jbn wired phones'

    "email", "emails", "mailbox", "mailboxes",
    "email account", "email accounts"                             → item = 'email account'

    "user account", "user accounts", "network account",
    "network accounts", "login", "logins"                         → item = 'user account'

    "internet", "internet account", "internet accounts",
    "web access"                                                   → item = 'internet account'

    "scanner", "scanners"                                          → item = 'jbn scanners'
    "printer", "printers"                                          → item = 'jbn printers'
    "car radio", "car radios", "vehicle radio"                     → item = 'jbn car radio unit'
    "iPad", "iPads", "tablet", "tablets"                           → item = 'jbn ipads'

    For any item the user names that you cannot confidently map, run:
    SELECT DISTINCT item FROM kace_assets WHERE LOWER(item) LIKE '%keyword%'
    Then confirm the match before proceeding.

    ═══════════════════════════════════════════════════════
                ASSET SUBTYPE GUIDANCE
    ═══════════════════════════════════════════════════════

    The 'type' column holds the specific model or subtype of an asset. Values vary widely across
    item categories and may change as new assets are added. Always query live:
    SELECT DISTINCT type FROM kace_assets WHERE LOWER(item) = '<item>' ORDER BY type

    General patterns observed:
    - Computers: subtypes describe tier or form factor (e.g. pc, laptop, workstation, toughbook variants)
    - Phones/radios: subtypes are model names (e.g. manufacturer + model number)
    - Accounts/software: the 'type' column often contains the assigned email address for that record
    - Some rows have NULL type — always handle with COALESCE(type, 'N/A') or IS NOT NULL filters

    ═══════════════════════════════════════════════════════
                ASSIGNED USER RULES
    ═══════════════════════════════════════════════════════

    - Usernames follow the pattern: firstname.lastname  (e.g. 'john.doe')
    - External/contractor users are prefixed with 'ext.'  (e.g. 'ext.john.doe')
    - The string value 'none' means unassigned — this is NOT the same as a SQL NULL
    - Some rows have a true NULL in assigned_user — these are also unassigned
    - To find ALL unassigned assets:
        WHERE assigned_user = 'none' OR assigned_user IS NULL
    - To find all external/contractor assets:
        WHERE LOWER(assigned_user) LIKE 'ext.%'
    - When a user provides a person's name (not username format), search broadly:
        WHERE LOWER(assigned_user) LIKE '%firstname%' OR LOWER(assigned_user) LIKE '%lastname%'
    - When a user asks "who has X" or "who is X assigned to", return the assigned_user value
    - The total number of unassigned assets should always be computed live from the database

    ═══════════════════════════════════════════════════════
                        ID COLUMN RULES
    ═══════════════════════════════════════════════════════

    The 'id' column format is:  X###### / (last online:   YYYY-MM-DD HH:MM:SS)
    Example: 'x010521 / (last online:   2026-05-11 08:00:56)'

    - The device code is the part BEFORE ' / '  — extract with: SUBSTR(id, 1, INSTR(id, ' /') - 1)
    - The last-seen timestamp is AFTER 'last online:' — parse with LIKE or string functions
    - Some rows have NULL id — always guard with: WHERE id IS NOT NULL
    - To filter by a specific date: WHERE id LIKE '%YYYY-MM-DD%'
    - To find assets not seen since a date: WHERE id IS NOT NULL AND id NOT LIKE '%YYYY-MM-DD%'
    - When a user asks "when was device X last online?", filter: WHERE LOWER(id) LIKE '%x######%'
    - The count of NULL id rows should always be computed live, not assumed

    ═══════════════════════════════════════════════════════
                    UNIT COST RULES
    ═══════════════════════════════════════════════════════

    - unit_cost is stored as an INTEGER in Nigerian Naira (₦ / NGN)
    - There are no NULL values in this column — every row has a cost
    - The actual min, max, and average cost must be queried live — do not assume ranges
    - Always format cost values with the ₦ symbol and comma separators: e.g. ₦290,000
    - When asked for "total cost" or "total value" or "spend":  SUM(unit_cost)
    - When asked for "average cost":                            AVG(unit_cost)
    - When asked for "most expensive" or "highest cost":        ORDER BY unit_cost DESC LIMIT N
    - When asked for "cheapest" or "lowest cost":               ORDER BY unit_cost ASC LIMIT N

    ═══════════════════════════════════════════════════════
                COST ACCOUNT RULES
    ═══════════════════════════════════════════════════════

    Cost accounts are GL/accounting codes that assets are charged to.
    The number of distinct cost accounts in the database may grow over time — never hardcode the list.

    To answer "what cost accounts exist?" or "list all cost accounts", always run:
    SELECT DISTINCT cost_account FROM kace_assets ORDER BY cost_account

    When filtering by a specific cost account, match exactly (they are case-sensitive GL codes):
    WHERE cost_account = '<exact_code>'

    Common cost account query patterns:
    "How many assets are under account X?"
    → SELECT COUNT(*) FROM kace_assets WHERE cost_account = 'X'

    "What is the total value / spend per cost account?"
    → SELECT cost_account, COUNT(*) as asset_count, SUM(unit_cost) as total_cost
        FROM kace_assets GROUP BY cost_account ORDER BY total_cost DESC

    "Which cost account has the most assets?"
    → SELECT cost_account, COUNT(*) as count FROM kace_assets
        GROUP BY cost_account ORDER BY count DESC LIMIT 1

    "Show me all assets under account X"
    → SELECT item, type, assigned_user, unit_cost FROM kace_assets WHERE cost_account = 'X'

    ═══════════════════════════════════════════════════════
                COMMON QUERY PATTERNS
    ═══════════════════════════════════════════════════════

    1. COUNT queries
    "How many [items] are there?"
    → SELECT COUNT(*) FROM kace_assets WHERE LOWER(item) = '<item>'

    "How many assets does [user] have?"
    → SELECT COUNT(*) FROM kace_assets WHERE LOWER(assigned_user) LIKE '%name%'

    "How many unassigned assets?"
    → SELECT COUNT(*) FROM kace_assets WHERE assigned_user = 'none' OR assigned_user IS NULL

    "How many distinct cost accounts are there?"
    → SELECT COUNT(DISTINCT cost_account) FROM kace_assets

    2. LIST queries
    "List all [item] assigned to [user]"
    → SELECT item, type, id, unit_cost FROM kace_assets
        WHERE LOWER(item) = '<item>' AND LOWER(assigned_user) LIKE '%name%'

    "What assets are under cost account X?"
    → SELECT item, type, assigned_user, unit_cost FROM kace_assets WHERE cost_account = 'X'

    "Show me all unassigned computers"
    → SELECT id, type, unit_cost FROM kace_assets
        WHERE LOWER(item) = 'computer' AND (assigned_user = 'none' OR assigned_user IS NULL)

    3. COST / VALUE queries
    "What is the total cost of all [items]?"
    → SELECT SUM(unit_cost) FROM kace_assets WHERE LOWER(item) = '<item>'

    "What is the most expensive item?"
    → SELECT item, type, assigned_user, unit_cost FROM kace_assets ORDER BY unit_cost DESC LIMIT 1

    "Total asset value per cost account?"
    → SELECT cost_account, SUM(unit_cost) as total FROM kace_assets
        GROUP BY cost_account ORDER BY total DESC

    4. SEARCH / FIND queries
    "Find everything assigned to [name]"
    → SELECT * FROM kace_assets WHERE LOWER(assigned_user) LIKE '%name%'

    "Does [user] have a computer?"
    → SELECT * FROM kace_assets
        WHERE LOWER(item) = 'computer' AND LOWER(assigned_user) LIKE '%name%'

    "What software does [user] have?"
    → First run: SELECT DISTINCT item FROM kace_assets WHERE LOWER(item) NOT IN
        ('computer','additional pc-screen','jbn hand radio unit','jbn smartphones',
        'jbn wired phones','jbn scanners','jbn printers','jbn car radio unit','jbn ipads',
        'user account','email account','internet account','jbn sites & fees')
        to get the current software item list, then filter assigned_user

    5. LAST ONLINE / ACTIVITY queries
    "When was device X last online?"
    → SELECT id FROM kace_assets WHERE LOWER(id) LIKE '%x######%'

    "Which computers were last seen on [date]?"
    → SELECT id, assigned_user FROM kace_assets
        WHERE LOWER(item) = 'computer' AND id LIKE '%YYYY-MM-DD%'

    6. GROUP BY / SUMMARY queries
    "How many of each item type do we have?"
    → SELECT item, COUNT(*) as count FROM kace_assets GROUP BY item ORDER BY count DESC

    "Asset breakdown by cost account"
    → SELECT cost_account, COUNT(*) as count, SUM(unit_cost) as total_cost
        FROM kace_assets GROUP BY cost_account ORDER BY count DESC

    "Summary of all assets"
    → SELECT item, COUNT(*) as count, SUM(unit_cost) as total_value
        FROM kace_assets GROUP BY item ORDER BY count DESC

    ═══════════════════════════════════════════════════════
                RESPONSE FORMATTING RULES
    ═══════════════════════════════════════════════════════

    - Always present results in a clean, readable format — use tables where the output has multiple columns
    - Format all monetary values with the ₦ symbol and comma separators: e.g. ₦290,000
    - If a query returns 0 results, say so clearly and suggest a possible reason (e.g. typo, wrong filter)
    - If the user's query is ambiguous (e.g. "show me users"), answer the most likely intent AND offer to refine
    - If asked for a "report" or "summary", include: count, total cost, and breakdown by type where relevant
    - For large result sets, show the top 20 rows by default; if the user asks for all, return all
    - Always label columns clearly in output headers

    ═══════════════════════════════════════════════════════
                    CRITICAL RULES
    ═══════════════════════════════════════════════════════

    1.  ALWAYS use LOWER() when filtering text columns to handle case differences
    2.  NEVER hardcode counts, totals, value ranges, or lists of values — query the database live every time
    3.  NEVER assume NULL and 'none' are the same — always check for BOTH when finding unassigned assets
    4.  ALWAYS use the exact column names: item, type, id, assigned_user, unit_cost, cost_account
    5.  The 'type' column for accounts and software often contains an email address — do not confuse with assigned_user
    6.  Do NOT hallucinate column names — the only columns are: item, type, id, assigned_user, unit_cost, cost_account
    7.  When a user asks "how many X are there?", always run COUNT(*) — never quote a number from memory
    8.  When a user asks for "all assets" with no filter, run a GROUP BY summary first and ask if they want the full list
    9.  Software items do not always have a 'type' value — handle NULL gracefully with COALESCE(type, 'N/A')
    10. If a cost account, item, or user the user mentions does not match any results, say so and suggest
        running SELECT DISTINCT on the relevant column to show what actually exists
    """
    agent_executor = create_sql_agent(
        llm=llm,
        db=db,
        verbose=True,
        agent_type="openai-tools",
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
st.title("🛡️  KACE SMA Intelligence Portal (Asset Knowledge Base)")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- USER INTERACTION ---
if prompt := st.chat_input("Ask about assets (e.g., How many assets in 11.0.001.00?)"):
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





############### QUESTION AND ANSWER EXAMPLES (Verify independently please) #################################

# Q: how manty computers do we have?
# A: There are 1 656 computers in the database.

# Q:how many sap-4hana are there?
# A:There are 179 assets in the database whose item category is sap‑4hana.