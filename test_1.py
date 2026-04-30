#############################################################################################################
###############  WORKING BASE CODE !!!!!!!!!!!!!!!!!!! Both local (gemma4:e4b)  and OpenAI api !!!!##########
## Can have issues with capitalization ond being too case sensitive. 
#############################################################################################################


# import pandas as pd
# from sqlalchemy import create_engine
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_openai import ChatOpenAI
# from langchain_ollama import ChatOllama
# from sql_data import sql_query
# from dotenv import load_dotenv

# load_dotenv()



# # KACE SMA connection
# DB_USER = "R1"
# DB_PASS = "box747"
# DB_HOST = "10.11.3.220"   # your SMA IP
# DB_NAME = "ORG1"

# print("Hello from 01-kace-langchain-rag!")
# question  = input("What do you want to know about your KACE SMA? \n")
# # 1. Pull the 30,000 rows from KACE (The "Heavy Lifting")
# kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")


# wizard_sql = sql_query.replace("%", "%%")
# # wizard_sql = sql_query
# df = pd.read_sql(wizard_sql, kace_engine)

# # 2. Push to local memory-only DB
# local_engine = create_engine("sqlite:///:memory:")
# df.to_sql("kace_assets", local_engine, index=False)

# # 3. Connect LangChain to the Sandbox
# db = SQLDatabase(local_engine)
# # llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0) # Or your preferred model
# llm = ChatOllama(model="gemma4:e4b", temperature=0) # Or your preferred model

# agent_executor = create_sql_agent(
#     llm=llm,
#     db=db,
#     verbose=True,
#     agent_type="openai-tools"
# )

# # Now it works perfectly!
# agent_executor.invoke({"input": question})





### WORKING !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
#############################################################################################################
############### Since you're using a local model via Ollama, the "Instruction" method is usually better than the "Pandas Normalization" method. 
# Local models can sometimes be  #### a bit literal, so giving them a clear system prompt helps them write smarter SQL.

## I have updated the code to include a suffix (the instructions) and a quick clean-up of your column names. 
# I also wrapped the SQL execution in a with block to ensure the  connection closes properly. ##########
#############################################################################################################


# import pandas as pd
# from sqlalchemy import create_engine, text
# from langchain_community.utilities import SQLDatabase
# from langchain_community.agent_toolkits import create_sql_agent
# from langchain_ollama import ChatOllama
# from sql_data import sql_query
# from dotenv import load_dotenv

# load_dotenv()

# # KACE SMA connection
# DB_USER = "R1"
# DB_PASS = "box747"
# DB_HOST = "10.11.3.220"
# DB_NAME = "ORG1"

# print("Hello from 01-kace-langchain-rag!")
# question = input("What do you want to know about your KACE SMA? \n")

# # 1. Pull the rows from KACE
# kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")

# # Escape percent signs for SQLAlchemy/Pandas compatibility
# wizard_sql = sql_query.replace("%", "%%")

# # Execute and load to DataFrame
# with kace_engine.connect() as conn:
#     df = pd.read_sql(text(wizard_sql), conn)

# # --- DATA CLEANUP ---
# # Replace spaces in column names with underscores to make it easier for the LLM to write SQL
# df.columns = [c.replace(' ', '_') for c in df.columns]
# # --------------------

# # 2. Push to local memory-only DB
# local_engine = create_engine("sqlite:///:memory:")
# df.to_sql("kace_assets", local_engine, index=False)

# # 3. Connect LangChain to the Sandbox
# db = SQLDatabase(local_engine)

# # Local LLM via Ollama
# llm = ChatOllama(model="gemma4:e4b", temperature=0)

# # 4. Add Case-Insensitivity Instructions
# # We tell the model to use LIKE or LOWER() so it finds "Amin.Kabir" even if you type "amin.kabir"
# custom_suffix = """
# You are working with a table named 'kace_assets'.
# IMPORTANT: 
# 1. If the user provides a name, username, or cost account, it might be in a different case than the database.
# 2. ALWAYS use the 'LIKE' operator or 'LOWER()' function for string comparisons to ensure case-insensitive matching.
# 3. Example: Instead of "WHERE User = 'amin.kabir'", use "WHERE User LIKE 'amin.kabir'".
# """

# agent_executor = create_sql_agent(
#     llm=llm,
#     db=db,
#     verbose=True,
#     agent_type="openai-tools", # Note: Ensure your Ollama version/model supports tool calling
#     suffix=custom_suffix
# )

# # Execute
# agent_executor.invoke({"input": question})







### WORKING !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
#############################################################################################################
############### To make your agent smarter and solve the case-sensitivity issue, we will normalize the data inside 
# your Python script before it hits the SQLite memory. This  is cleaner than relying on the LLM to remember to lowercase things.

###  I have also added a "System Message" wrapper. Even though you are using ChatOllama (Gemma 4), providing a 
# structured system prompt helps the model understand that it is working with a pre-processed, lowercase-focused database. ##########
#############################################################################################################


import pandas as pd
from sqlalchemy import create_engine, text
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_ollama import ChatOllama
from sql_data import sql_query
from dotenv import load_dotenv
import os

load_dotenv()

# KACE SMA connection
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME")

print("Hello from 01-kace-langchain-rag!")

# 1. Pull data and normalize immediately
kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")
escaped_sql = sql_query.replace("%", "%%")

with kace_engine.connect() as conn:
    df = pd.read_sql(text(escaped_sql), conn)

# --- NORMALIZATION STEP ---
# Rename columns to lowercase and replace spaces with underscores
df.columns = [c.replace(' ', '_').lower() for c in df.columns]

# Lowercase all string-based columns to ensure case-insensitive matching
for col in df.select_dtypes(include=['object']).columns:
    df[col] = df[col].str.lower()
# ---------------------------

# 2. Push to local memory-only DB
local_engine = create_engine("sqlite:///:memory:")
df.to_sql("kace_assets", local_engine, index=False)

# 3. Connect LangChain
db = SQLDatabase(local_engine)
llm = ChatOllama(model="gemma4:e4b", temperature=0)

# Define a system prompt to guide the model
system_prompt = """
You are an expert KACE SMA data analyst. 
The database is fully normalized to lowercase. 
When a user asks for 'Amin.Kabir', search for 'amin.kabir'.
When a user asks for 'Cost Account', search the 'cost_account' column.
Always use the column names exactly as they appear in the schema.
"""

agent_executor = create_sql_agent(
    llm=llm,
    db=db,
    verbose=True,
    agent_type="openai-tools",
    system_message=system_prompt
)

# Interaction
question = input("What do you want to know about your KACE SMA? \n")
# Lowercase the input so it matches our normalized data
agent_executor.invoke({"input": question.lower()})









#### The reliable llm's in ollama for this project

# gemma4:e4b ## GOOD!!!! I think the best!

# "qwen3.5:9b" ## GOOD!!!!

## Example Question!!!!
## how many tickets do we have in the "ALL JBN: IT-REQUISITION" queue and the "ALL JBN: IT-REQUISITION" combined,  in the first quarter of 2026?

## what is the sum of the cost for the  11.0.001.00 cost account?  ✅✅✅✅
### what is the total cost of assets in the cost account 11.0.001.00 ❌❌❌❌❌