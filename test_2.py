


# #### STREAMLIT VERSION WORKING BELOW. But capitalization is not ignored. So "Amin" is not  "amin"
#####  Capitalization should  be ignored when searchin the DB!
# ##########################################################################################
# ##########################################################################################
# ##########################################################################################

# import streamlit as st
# import pandas as pd
# from sqlalchemy import create_engine, text
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
# from sql_data_assets import sql_query

# # --- CONFIG ---
# st.set_page_config(page_title="KACE AI Agent", layout="wide")

# @st.cache_resource
# def get_sql_engine():
#     """Connects to KACE once and caches the local SQLite engine."""
#     # 1. Connect to KACE
#     kace_engine = create_engine("mysql+pymysql://R1:box747@10.11.3.220:3306/ORG1")
    
#     # 2. Extract 
#     with kace_engine.connect() as conn:
#         df = pd.read_sql(text(sql_query.replace("%", "%%")), conn)
    
#     # 3. Clean column names
#     df.columns = [c.replace(' ', '_') for c in df.columns]
    
#     # 4. FIXED: Use a local file instead of :memory:
#     # This ensures the table persists across Streamlit reruns
#     local_db_path = "sqlite:///local_kace.db"
#     local_engine = create_engine(local_db_path)
#     df.to_sql("kace_assets", local_engine, index=False, if_exists='replace')
    
#     return SQLDatabase(local_engine), df

# # Load the engine and dataframe
# db, raw_df = get_sql_engine()

# # --- CHAT UI ---
# st.title("🤖 KACE SMA Intelligence")

# if "messages" not in st.session_state:
#     st.session_state.messages = []

# # Display chat history
# for message in st.session_state.messages:
#     with st.chat_message(message["role"]):
#         st.markdown(message["content"])

# # --- AGENT SETUP ---
# # Note: Using gemma4:e4b as requested
# llm = ChatOllama(model="gemma4:e4b", temperature=0)

# agent_executor = create_sql_agent(
#     llm=llm,
#     db=db,
#     verbose=True,
#     agent_type="openai-tools",
#     # Added instructions to handle the specific columns seen in your error
#     suffix="Always use LIKE or LOWER() for string searches. The table name is 'kace_assets'."
# )

# # --- CHAT INPUT ---
# if prompt := st.chat_input("Ask about assets..."):
#     st.session_state.messages.append({"role": "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     with st.chat_message("assistant"):
#         # The agent now looks at the local_kace.db file which won't be empty
#         response = agent_executor.invoke({"input": prompt})
#         answer = response["output"]
#         st.markdown(answer)
        
#         # --- DYNAMIC CHARTING ---
#         # Using a case-insensitive check for your "COST_ACCOUNT" column
#         if "cost account" in prompt.lower():
#             # Check for the actual column name from your error trace
#             col_name = "COST_ACCOUNT" if "COST_ACCOUNT" in raw_df.columns else "Cost_Account"
#             st.bar_chart(raw_df[col_name].value_counts().head(10))
            
#     st.session_state.messages.append({"role": "assistant", "content": answer})



#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################
########### WORKING- Solved cCapitalization issue ...BUT LOTS OF ITERATIONS because of NAIRA sign ##

# import re
# import streamlit as st
# import pandas as pd
# import os
# from sqlalchemy import create_engine, text
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
# from sql_data_assets import sql_query
# from dotenv import load_dotenv

# load_dotenv()

# # --- CONFIG ---
# st.set_page_config(page_title="KACE Asset AI", layout="wide")

# @st.cache_resource
# def get_unified_db():
#     """Combines KACE connection, strict normalization, and SQLite persistence."""
#     # 1. Connection
#     DB_USER = os.environ.get("DB_USER")
#     DB_PASS = os.environ.get("DB_PASS")
#     DB_HOST = os.environ.get("DB_HOST")
#     DB_NAME = os.environ.get("DB_NAME")
    
#     kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")
    
#     # 2. Extract
#     with kace_engine.connect() as conn:
#         df = pd.read_sql(text(sql_query.replace("%", "%%")), conn)
    
#     # --- YOUR NORMALIZATION LOGIC ---
#     # Rename columns: lowercase and underscores
#     df.columns = [c.replace(' ', '_').lower() for c in df.columns]

#     # Lowercase all string data for case-insensitive matching
#     for col in df.select_dtypes(include=['object']).columns:
#         df[col] = df[col].str.lower()
#     # ---------------------------------
    
#     # 3. Persistence (Using a local file instead of :memory: for Streamlit stability)
#     local_engine = create_engine("sqlite:///local_kace.db")
#     df.to_sql("kace_assets", local_engine, index=False, if_exists='replace')
    
#     return SQLDatabase(local_engine), df

# # Initialize Data
# db, raw_df = get_unified_db()

# # --- CHAT UI ---
# st.title("🛡️ KACE SMA Intelligence Portal")

# if "messages" not in st.session_state:
#     st.session_state.messages = []

# # Display Chat History
# for message in st.session_state.messages:
#     with st.chat_message(message["role"]):
#         st.markdown(message["content"])

# # --- AGENT SETUP ---
# llm = ChatOllama(model="gemma4:e4b", temperature=0)

# system_prompt = """
# You are an expert KACE SMA data analyst. 
# The database 'kace_assets' is fully normalized to lowercase. 
# All string-based values and column names are in lowercase.
# Always use the column names exactly as they appear in the schema (using underscores).
# """

# agent_executor = create_sql_agent(
#     llm=llm,
#     db=db,
#     verbose=True,
#     agent_type="openai-tools",
#     suffix=system_prompt  # Using suffix/system_message to guide the local model
# )

# # --- USER INTERACTION ---
# if prompt := st.chat_input("Ask about assets (e.g., How many assets in 11.0.001.00?)"):
#     # Store and show user message
#     st.session_state.messages.append({"role": "user", "content": prompt})
#     with st.chat_message("user"):
#         st.markdown(prompt)

#     with st.chat_message("assistant"):
#         # LOWERCASE the input here to match your normalized DB
#         normalized_query = prompt.lower()
        
#         response = agent_executor.invoke({"input": normalized_query})
#         answer = response["output"]
#         st.markdown(answer)
        
#         # # --- AUTO-CHARTS (Using normalized column name) ---
#         # if "cost_account" in raw_df.columns and "cost account" in prompt.lower():
#         #     st.bar_chart(raw_df['cost_account'].value_counts().head(10))
            
#     st.session_state.messages.append({"role": "assistant", "content": answer})









#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################







import re
import streamlit as st
import pandas as pd
import os
from sqlalchemy import create_engine, text
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from sql_data_assets import sql_query
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
st.set_page_config(page_title="KACE Asset AI", layout="wide")

@st.cache_resource
def get_unified_db():
    """Combines KACE connection, strict normalization, and SQLite persistence."""
    # 1. Connection
    DB_USER = os.environ.get("DB_USER")
    DB_PASS = os.environ.get("DB_PASS")
    DB_HOST = os.environ.get("DB_HOST")
    DB_NAME = os.environ.get("DB_NAME")
    
    kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")
    
    # 2. Extract
    with kace_engine.connect() as conn:
        df = pd.read_sql(text(sql_query.replace("%", "%%")), conn)
    
    # --- ENHANCED NORMALIZATION LOGIC ---
    # A. Clean Column Names (Lowercase + Underscores + No Special Chars)
    new_cols = [c.replace(' ', '_').lower() for c in df.columns]
    # This regex removes everything except letters, numbers, and underscores
    new_cols = [re.sub(r'[^a-z0-9_]', '', c) for c in new_cols]
    df.columns = [c.replace('__', '_').strip('_') for c in new_cols]

    # B. Clean Numeric Data (Handle symbols and commas in "unit_cost")
    # Identify the cost column even after renaming
    cost_col = next((c for c in df.columns if 'cost' in c), None)
    if cost_col:
        # Remove anything that isn't a digit or a decimal point
        df[cost_col] = df[cost_col].replace(r'[^\d.]', '', regex=True)
        df[cost_col] = pd.to_numeric(df[cost_col], errors='coerce').fillna(0.0)

    # C. Lowercase all remaining string data for matching
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].astype(str).str.lower()
    # ------------------------------------
    
    # 3. Persistence
    local_engine = create_engine("sqlite:///local_kace.db")
    df.to_sql("kace_assets", local_engine, index=False, if_exists='replace')
    
    return SQLDatabase(local_engine), df

# Initialize Data
db, raw_df = get_unified_db()

# --- CHAT UI ---
st.title("🛡️ KACE SMA Intelligence Portal")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- AGENT SETUP ---
# llm = ChatOllama(model="gemma4:e4b", temperature=0)
llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)

system_prompt = """
You are an expert KACE SMA data analyst. 
The database 'kace_assets' is fully normalized to lowercase. 
All string-based values and column names are in lowercase.
Always use the column names exactly as they appear in the schema (using underscores).
"""

agent_executor = create_sql_agent(
    llm=llm,
    db=db,
    verbose=True,
    agent_type="openai-tools",
    suffix=system_prompt  # Using suffix/system_message to guide the local model
)

# --- USER INTERACTION ---
if prompt := st.chat_input("Ask about assets (e.g., How many assets in 11.0.001.00?)"):
    # Store and show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # LOWERCASE the input here to match your normalized DB
        normalized_query = prompt.lower()
        
        response = agent_executor.invoke({"input": normalized_query})
        answer = response["output"]
        st.markdown(answer)
        
        # # --- AUTO-CHARTS (Using normalized column name) ---
        # if "cost_account" in raw_df.columns and "cost account" in prompt.lower():
        #     st.bar_chart(raw_df['cost_account'].value_counts().head(10))
            
    st.session_state.messages.append({"role": "assistant", "content": answer})