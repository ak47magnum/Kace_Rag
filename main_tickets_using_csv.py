
# =======================================================================================================
### Working rag using CSV. Using CSV More efficient than a call to the db each time the page is refreshed
# =======================================================================================================


import re
import streamlit as st
import pandas as pd
import os
import time
from sqlalchemy import create_engine, text
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
# from sql_data_assets import sql_query
from sql_data_tickets import query_tickets
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
CSV_FILE = "kace_tickets.csv"
REFRESH_INTERVAL = 6 * 3600  # 6 hours in seconds
st.set_page_config(page_title="KACE Asset AI (Ticket Knowledge Base)", layout="wide")

# --- HELPER FUNCTIONS ---
def needs_csv_refresh(csv_path: str, interval: int) -> bool:
    """Check if the CSV needs refreshing (missing or older than interval)."""
    if not os.path.exists(csv_path):
        return True
    last_modified = os.path.getmtime(csv_path)
    return (time.time() - last_modified) > interval

def refresh_csv():
    """Run KACE query, normalize data, and overwrite the CSV file."""
    # Connect to KACE DB using env vars
    DB_USER = os.environ.get("DB_USER")
    DB_PASS = os.environ.get("DB_PASS")
    DB_HOST = os.environ.get("DB_HOST")
    DB_NAME = os.environ.get("DB_NAME")

    kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")

    # Extract data using the same query from sql_data.py
    with kace_engine.connect() as conn:
        df = pd.read_sql(text(query_tickets.replace("%", "%%")), conn)

    # --- NORMALIZE DATA (same as test_2.py) ---
    # Clean column names (lowercase, underscores, no special chars)
    new_cols = [c.replace(' ', '_').lower() for c in df.columns]
    new_cols = [re.sub(r'[^a-z0-9_]', '', c) for c in new_cols]
    df.columns = [c.replace('__', '_').strip('_') for c in new_cols]

    # Clean cost column (remove symbols, convert to numeric)
    cost_col = next((c for c in df.columns if 'cost' in c), None)
    if cost_col:
        df[cost_col] = df[cost_col].replace(r'[^\d.]', '', regex=True)
        df[cost_col] = pd.to_numeric(df[cost_col], errors='coerce').fillna(0.0)

    # Lowercase all string data for case-insensitive matching
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].astype(str).str.lower().str.strip()

    # Overwrite the existing CSV file
    df.to_csv(CSV_FILE, index=False)
    return df

# --- DATA LOADING (CSV-backed) ---
# Check if CSV needs refresh on app start
if needs_csv_refresh(CSV_FILE, REFRESH_INTERVAL):
    st.info("CSV data is stale. Refreshing from KACE database...")
    refresh_csv()
    st.success("CSV data refreshed successfully.")

    # # Clear cached DB if it exists (force reload from new CSV)  
    # st.cache_resource.clear() ## claude says its not needed/

@st.cache_resource
def get_unified_db():
    """Load data from CSV and create a SQLDatabase for the agent."""
    # Read the normalized CSV (already cleaned by refresh_csv)
    raw_df = pd.read_csv(CSV_FILE)

    # Strip whitespace from string columns (handles existing CSV with trailing spaces)
    for col in raw_df.select_dtypes(include=['object']).columns:
        raw_df[col] = raw_df[col].astype(str).str.strip()

    # Create local SQLite DB from CSV data (same as before, but data comes from CSV)
    local_engine = create_engine("sqlite:///local_kace.db")
    raw_df.to_sql("kace_tickets", local_engine, index=False, if_exists='replace')

    return SQLDatabase(local_engine), raw_df

# Initialize data
try:
    db, raw_df = get_unified_db()
except FileNotFoundError:
    st.error(f"CSV file {CSV_FILE} not found. Refreshing now...")
    refresh_csv()
    db, raw_df = get_unified_db()

# --- CHAT UI (same as test_2.py) ---
st.title("🛡️  KACE SMA Intelligence Portal (Tickets Knowledge Base)")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- AGENT SETUP ---
# llm = ChatOllama(model="gemma4:e4b", temperature=0) ## Really good local model  ###************************************************************
# llm = ChatOpenAI(model="gpt-4o-mini", temperature=0) ## Cheapest option. Works! # But have noticed some mistakes if query is complex 
# llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)  ## Works!
# llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0) ### Really good GPT model - BEST VALUE FOR MONEY
llm = ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0)
# llm = ChatOpenRouter(model="openai/gpt-oss-120b", temperature=0)  ### SO FAR... REALLY GOOD!!! ANF CHEAP....!!!


system_prompt = """
You are an expert KACE SMA data analyst and a friendly assistant.
The database 'kace_tickets' is fully normalized to lowercase.
All string-based values and column names are in lowercase.
Always use the column names exactly as they appear in the schema (using underscores).

When a user asks for a count of tickets in a specific queue, translate the question into a SQL COUNT query that filters on the queue_name column.
Normalize the queue name in the user's question (lowercase, trim whitespace) before comparing it to the stored values.
Provide the count result after executing the query.
when the user asks about the 'requisition queue', this is a reference to the tickets with queue_name = 'ALL JBN: IT-REQUISITION'.
when the user asks about the 'support queue', this is a reference to the tickets with queue_name = 'ALL JBN : REQUEST IT SUPPORT HELP'.

If the user greets you (e.g., "hi", "hello", "hey", "good morning"), responds with a friendly greeting and asks how you can help them with ticket data. Do NOT try to query the database for greetings.
If the user asks something unrelated to the ticket data, politely let them know you specialize in KACE ticket analysis.

"""

agent_executor = create_sql_agent(
    llm=llm,
    db=db,
    verbose=True,
    agent_type="openai-tools",
    suffix=system_prompt
)

# --- USER INTERACTION ---
if prompt := st.chat_input("Ask about assets (e.g., How many assets in 11.0.001.00?)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        normalized_query = prompt.lower().strip()
        response = agent_executor.invoke({"input": normalized_query})
        answer = response["output"]
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})




### Questions

###  how many tickets have a title containing "VPN" ?  ✅
###  how many tickets have a title containing "vpn" in the first quarter of 2026?  ✅
###  how many tickts do we have? ✅
###  how many queues do we have? ✅
###  how many tickets did we have in the first quarter of 2026? ✅
###  how many tickets in the queue 'all jbn : request it support help' did we have in the first quarter of 2026? ✅
###  how many tickets in the queue 'all jbn: it-requisition' did we have in the first quarter of 2026? ✅

###  how many tickets in the queue 'all jbn : request it support help'? ✅
###  how many tickets did we have in each queue , in january 2026? ✅

### how many tickets in the support queue did we have in the first quarter of 2026?