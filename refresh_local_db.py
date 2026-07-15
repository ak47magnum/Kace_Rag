"""
Standalone script to refresh local_kace.db from the KACE database.

Creates two tables: kace_assets and kace_tickets.

Run this whenever you want an up-to-date SQLite database to browse:
    uv run python refresh_local_db.py

Or with your package manager:
    python refresh_local_db.py
"""

import re
import os
import time
from sqlalchemy import create_engine, text
import pandas as pd
from dotenv import load_dotenv
from sql_data_assets import sql_query as assets_query
from sql_data_tickets import query_tickets as tickets_query

load_dotenv()

# --- CONFIG ---
DB_FILE = "local_kace.db"

# --- CONNECT TO KACE ---
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME")

print(f"Connecting to KACE MySQL at {DB_HOST}...")
kace_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/{DB_NAME}")

# ------------------------------------------------------------------
# HELPER: normalize column names and data (same logic as the apps)
# ------------------------------------------------------------------
def normalize(df):
    new_cols = [c.replace(" ", "_").lower() for c in df.columns]
    new_cols = [re.sub(r"[^a-z0-9_]", "", c) for c in new_cols]
    df.columns = [c.replace("__", "_").strip("_") for c in new_cols]

    cost_col = next((c for c in df.columns if "cost" in c), None)
    if cost_col:
        df[cost_col] = df[cost_col].replace(r"[^\d.]", "", regex=True)
        df[cost_col] = pd.to_numeric(df[cost_col], errors="coerce").fillna(0.0)

    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.lower().str.strip()
    return df


# ------------------------------------------------------------------
# ASSETS
# ------------------------------------------------------------------
print("--- Assets ---")
print("Running asset query...")
start = time.time()
with kace_engine.connect() as conn:
    assets_df = pd.read_sql(text(assets_query.replace("%", "%%")), conn)
print(f"Fetched {len(assets_df)} rows in {time.time() - start:.1f}s")

assets_df = normalize(assets_df)

# ------------------------------------------------------------------
# TICKETS
# ------------------------------------------------------------------
print("--- Tickets ---")
print("Running ticket query...")
start = time.time()
with kace_engine.connect() as conn:
    tickets_df = pd.read_sql(text(tickets_query.replace("%", "%%")), conn)
print(f"Fetched {len(tickets_df)} rows in {time.time() - start:.1f}s")

tickets_df = normalize(tickets_df)

# ------------------------------------------------------------------
# WRITE TO local_kace.db
# ------------------------------------------------------------------
print(f"\nWriting to {DB_FILE}...")
local_engine = create_engine(f"sqlite:///{DB_FILE}")

assets_df.to_sql("kace_assets", local_engine, index=False, if_exists="replace")
tickets_df.to_sql("kace_tickets", local_engine, index=False, if_exists="replace")

# Verify
with local_engine.connect() as conn:
    asset_count = conn.execute(text("SELECT COUNT(*) FROM kace_assets")).fetchone()[0]
    ticket_count = conn.execute(text("SELECT COUNT(*) FROM kace_tickets")).fetchone()[0]

print(f"Done! {DB_FILE} now has:")
print(f"  kace_assets   -> {asset_count} rows")
print(f"  kace_tickets  -> {ticket_count} rows")
