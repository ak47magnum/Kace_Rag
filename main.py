
######### THIS IS JUST A BASIC CONNECTION TO KACE ############################


from langchain_openai import ChatOpenAI
# from langchain_ollama import ChatOllama
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.agent_toolkits import create_sql_agent
from sqlalchemy import create_engine

import os
from dotenv import load_dotenv
load_dotenv()


# KACE SMA connection
DB_USER = "R1"
DB_PASS = "box747"
DB_HOST = "10.11.3.220"   # your SMA IP
DB_NAME = "ORG1"



def main():
    print("Hello from 01-kace-langchain-rag!")
    question  = input("What do you want to know about your KACE SMA? \n")
    
    engine = create_engine(
        f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}"
    )

    # Prevent sending sample rows (good practice even locally)
    db = SQLDatabase(
        engine,
        sample_rows_in_table_info=0
    )

    # # Local LLM via Ollama
    # llm = ChatOllama(
    #     model="gemma4:e4b",     # or "gemma:4b" or "qwen2.5:7b"
    #     temperature=0
    # )


    # Local LLM via OpenAi
    llm = ChatOpenAI(
        model="gpt-4o-mini",     # gpt models
        temperature=0
    )

    agent = create_sql_agent(
        llm=llm,
        db=db,
        agent_type="tool-calling",   # works fine with ollama too
        verbose=True
    )

    response = agent.invoke(question)

    print(response)


if __name__ == "__main__":
    main()





#### The reliable llm's in ollama for this project

# gemma4:e4b ## GOOD!!!! I think the best!

# "qwen3.5:9b" ## GOOD!!!!

## Example Question!!!!
## how many tickets do we have in the "ALL JBN: IT-REQUISITION" queue and the "ALL JBN: IT-REQUISITION" combined,  in the first quarter of 2026?