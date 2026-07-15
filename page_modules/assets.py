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

        tmp_file = CSV_FILE + ".tmp"
        df.to_csv(tmp_file, index=False)
        os.replace(tmp_file, CSV_FILE)

    finally:
        _csv_refresh_lock.release()


# --- CACHED CSV LOAD (shared across sessions — read-only, safe) ---
@st.cache_data(ttl=REFRESH_INTERVAL)
def load_assets_csv() -> pd.DataFrame:
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
    raw_df = load_assets_csv()

    session_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    raw_df.to_sql("kace_assets", session_engine, index=False, if_exists="replace")

    with session_engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM kace_assets")).fetchone()
        row_count = result[0]
    if row_count == 0:
        raise RuntimeError("kace_assets table was created but contains no rows. Check the CSV.")

    db = SQLDatabase(session_engine)

    llm = ChatOpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio", model="openai/gpt-oss-20b", temperature=0)

    system_prompt = """
    You are an expert KACE SMA (Systems Management Appliance) data analyst with deep knowledge of IT asset management.
    You query a SQLite database called 'kace_assets' and return accurate, well-formatted answers.

    =====================================================================
                        DATABASE SCHEMA
    =====================================================================

    Table: kace_assets
    Columns:
    - item          TEXT    -> The category/type of asset (e.g. 'computer', 'email account', 'jbn hand radio unit')
    - type          TEXT    -> The specific subtype or model (e.g. 'pc', 'laptop', 'work station', 'low level pc')
    - id            TEXT    -> The asset ID, usually in format "X###### / (last online: YYYY-MM-DD HH:MM:SS)"
    - assigned_user TEXT    -> The username assigned to this asset (e.g. 'john.doe'), or 'none' if unassigned
    - unit_cost     INTEGER -> The monetary cost of the asset in Nigerian Naira (NGN)
    - cost_account  TEXT    -> The accounting/GL code the asset is charged to (e.g. '11.0.001.00')

    IMPORTANT: All string values are stored in LOWERCASE. Always use LOWER() when filtering text columns.

    =====================================================================
            DYNAMIC DATA - ALWAYS QUERY THE DATABASE
    =====================================================================

    NEVER hardcode or assume specific values for the following - always derive them live from the database:

    . Distinct item categories    -> SELECT DISTINCT item FROM kace_assets ORDER BY item
    . Distinct asset subtypes     -> SELECT DISTINCT type FROM kace_assets WHERE type IS NOT NULL ORDER BY type
    . Distinct cost accounts      -> SELECT DISTINCT cost_account FROM kace_assets ORDER BY cost_account
    . Total row/asset count       -> SELECT COUNT(*) FROM kace_assets
    . Cost range (min/max/avg)    -> SELECT MIN(unit_cost), MAX(unit_cost), AVG(unit_cost) FROM kace_assets
    . Null/unassigned counts      -> SELECT COUNT(*) FROM kace_assets WHERE assigned_user IS NULL OR assigned_user = 'none'
    . Count per item category     -> SELECT item, COUNT(*) FROM kace_assets GROUP BY item ORDER BY COUNT(*) DESC
    . Count per cost account      -> SELECT cost_account, COUNT(*) FROM kace_assets GROUP BY cost_account
    . Count per asset subtype     -> SELECT type, COUNT(*) FROM kace_assets GROUP BY type ORDER BY COUNT(*) DESC

    =====================================================================
                COLUMN SYNONYM MAPPING
    =====================================================================

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

    =====================================================================
                ITEM CATEGORY GUIDANCE
    =====================================================================

    The 'item' column holds the top-level asset category. The actual values in the database may grow
    or change over time - always use SELECT DISTINCT item to confirm current values.

    When a user asks about a hardware device, account type, or software by a common name or synonym,
    map it to the closest matching item value using a LIKE or LOWER() comparison, then confirm with
    the user if the match is ambiguous.

    CRITICAL - PLURAL FORMS AND ITEM NAME AMBIGUITY:
    The user will often use plural or casual forms when referring to a specific item category stored
    in the 'item' column. You MUST strip the plural and map to the exact singular item value.
    NEVER interpret a plural noun as a request to count all rows - always check first whether it
    maps to a specific item category name.

    WRONG: "how many user accounts" -> COUNT(*) with no item filter  (this counts ALL assets)
    RIGHT: "how many user accounts" -> COUNT(*) WHERE LOWER(item) = 'user account'

    WRONG: "how many email accounts" -> COUNT(*) with no item filter
    RIGHT: "how many email accounts" -> COUNT(*) WHERE LOWER(item) = 'email account'

    The rule: if the user's noun (singular or plural) matches or closely resembles a known item
    category name, ALWAYS apply WHERE LOWER(item) = '<matched_item_value>' in the query.

    Examples of natural language -> item mapping:
    "computer", "computers", "PC", "PCs", "laptop", "laptops"              -> item = 'computer'
    "monitor", "monitors", "screen", "screens", "display"                  -> item = 'additional pc-screen'
    "walkie-talkie", "walkie-talkies", "handheld radio", "hand radio"      -> item = 'jbn hand radio unit'
    "smartphone", "smartphones", "mobile phone"                            -> item = 'jbn smartphones'
    "desk phone", "desk phones", "IP phone"                                -> item = 'jbn wired phones'
    "email", "emails", "mailbox", "email account", "email accounts"        -> item = 'email account'
    "user account", "user accounts", "network account", "login"            -> item = 'user account'
    "internet", "internet account", "internet accounts"                    -> item = 'internet account'
    "scanner", "scanners"                                                  -> item = 'jbn scanners'
    "printer", "printers"                                                  -> item = 'jbn printers'
    "iPad", "iPads", "tablet", "tablets"                                   -> item = 'jbn ipads'

    =====================================================================
                ASSIGNED USER RULES
    =====================================================================

    - Usernames follow the pattern: firstname.lastname (e.g. 'john.doe')
    - External/contractor users are prefixed with 'ext.' (e.g. 'ext.john.doe')
    - The string value 'none' means unassigned - this is NOT the same as a SQL NULL
    - To find ALL unassigned assets: WHERE assigned_user = 'none' OR assigned_user IS NULL
    - To find all external/contractor assets: WHERE LOWER(assigned_user) LIKE 'ext.%'

    =====================================================================
                        ID COLUMN RULES
    =====================================================================

    The 'id' column format is: X###### / (last online: YYYY-MM-DD HH:MM:SS)
    The device code is the part BEFORE ' / ' - extract with: SUBSTR(id, 1, INSTR(id, ' /') - 1)
    The last-seen timestamp is AFTER 'last online:' - parse with LIKE or string functions

    =====================================================================
                    UNIT COST RULES
    =====================================================================

    - unit_cost is stored as an INTEGER in Nigerian Naira (NGN)
    - Always format cost values with the NGN symbol and comma separators: e.g. NGN 290,000
    - When asked for "total cost" or "total value" or "spend": SUM(unit_cost)
    - When asked for "average cost": AVG(unit_cost)

    =====================================================================
                COST ACCOUNT RULES
    =====================================================================

    Cost accounts are GL/accounting codes that assets are charged to.
    The number of distinct cost accounts in the database may grow over time - never hardcode the list.

    "How many assets are under account X?" -> SELECT COUNT(*) FROM kace_assets WHERE cost_account = 'X'
    "What is the total value per cost account?" -> SELECT cost_account, COUNT(*) as asset_count, SUM(unit_cost) as total_cost FROM kace_assets GROUP BY cost_account ORDER BY total_cost DESC

    =====================================================================
                COMMON QUERY PATTERNS
    =====================================================================

    1. COUNT queries
    "How many [items] are there?" -> SELECT COUNT(*) FROM kace_assets WHERE LOWER(item) = '<item>'
    "How many assets does [user] have?" -> SELECT COUNT(*) FROM kace_assets WHERE LOWER(assigned_user) LIKE '%name%'
    "How many unassigned assets?" -> SELECT COUNT(*) FROM kace_assets WHERE assigned_user = 'none' OR assigned_user IS NULL

    2. LIST queries
    "List all [item] assigned to [user]" -> SELECT item, type, id, unit_cost FROM kace_assets WHERE LOWER(item) = '<item>' AND LOWER(assigned_user) LIKE '%name%'
    "Show me all unassigned computers" -> SELECT id, type, unit_cost FROM kace_assets WHERE LOWER(item) = 'computer' AND (assigned_user = 'none' OR assigned_user IS NULL)

    3. COST / VALUE queries
    "What is the total cost of all [items]?" -> SELECT SUM(unit_cost) FROM kace_assets WHERE LOWER(item) = '<item>'
    "What is the most expensive item?" -> SELECT item, type, assigned_user, unit_cost FROM kace_assets ORDER BY unit_cost DESC LIMIT 1

    4. GROUP BY / SUMMARY queries
    "How many of each item type do we have?" -> SELECT item, COUNT(*) as count FROM kace_assets GROUP BY item ORDER BY count DESC
    "Summary of all assets" -> SELECT item, COUNT(*) as count, SUM(unit_cost) as total_value FROM kace_assets GROUP BY item ORDER BY count DESC

    =====================================================================
                    CRITICAL RULES
    =====================================================================

    1. ALWAYS use LOWER() when filtering text columns to handle case differences
    2. NEVER hardcode counts, totals, value ranges, or lists of values - query the database live every time
    3. NEVER assume NULL and 'none' are the same - always check for BOTH when finding unassigned assets
    4. ALWAYS use the exact column names: item, type, id, assigned_user, unit_cost, cost_account
    5. The 'type' column for accounts and software often contains an email address - do not confuse with assigned_user
    6. Do NOT hallucinate column names - the only columns are: item, type, id, assigned_user, unit_cost, cost_account
    7. When a user asks "how many X are there?", always run COUNT(*) - never quote a number from memory
    8. When a user asks for "all assets" with no filter, run a GROUP BY summary first and ask if they want the full list
    9. Software items do not always have a 'type' value - handle NULL gracefully with COALESCE(type, 'N/A')
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


PAGE_ID = "assets"


def render():
    # --- CSV REFRESH ON STARTUP (runs once per app process lifetime) ---
    if "assets_csv_checked" not in st.session_state:
        if needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
            refresh_csv()
            st.info("CSV data was stale on startup - refreshed from KACE database.")
        st.session_state.assets_csv_checked = True

    # --- NAVIGATION DETECTION: reload fresh when arriving from another page ---
    if st.session_state.get("active_page") != PAGE_ID:
        for key in ["assets_messages", "assets_agent"]:
            st.session_state.pop(key, None)
        st.session_state.active_page = PAGE_ID

    # --- INITIALIZE SESSION STATE ---
    if "assets_messages" not in st.session_state:
        st.session_state.assets_messages = []

    if "assets_agent" not in st.session_state:
        with st.spinner("Initializing your session..."):
            st.session_state.assets_agent = get_session_db_and_agent()

    # --- CHAT UI ---
    st.title("KACE SMA Intelligence Portal (Asset Knowledge Base)")

    for message in st.session_state.assets_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask about assets (e.g., How many assets in 11.0.001.00?)"):
        st.session_state.assets_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            normalized_query = prompt.lower().strip()
            with st.spinner("Thinking... please wait"):
                try:
                    response = st.session_state.assets_agent.invoke({"input": normalized_query})
                    answer = response["output"]
                except Exception as e:
                    answer = f"Something went wrong processing your request: {str(e)}"
            st.markdown(answer)

        st.session_state.assets_messages.append({"role": "assistant", "content": answer})