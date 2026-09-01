"""Data ingestion pipeline for Brann ticket sales forecasting."""
from datetime import datetime
import duckdb
import polars as pl

from config import DB_PATH
from utils import scrape_eliteserien_results


def ingest_eliteserien_results(season_id: int, year: int) -> None:
    """Ingest Eliteserien results into DuckDB raw table."""
    con = duckdb.connect(str(DB_PATH))
    
    print(f"Fetching Eliteserien results for season {season_id} ({year})...")
    data = scrape_eliteserien_results(season_id=season_id, year=year)
    
    # Convert to Polars for easier manipulation
    df = pl.DataFrame(data)
    
    # Add ingestion timestamp
    df = df.with_columns([
        pl.lit(datetime.now()).alias("ingested_at")
    ])
    
    # Create or replace raw table
    con.execute("DROP TABLE IF EXISTS raw_eliteserien_results")
    con.execute(f"CREATE TABLE raw_eliteserien_results AS SELECT * FROM df")
    
    con.close()
    print(f"✓ Ingested {len(data)} Eliteserien records")


if __name__ == "__main__":
    ingest_eliteserien_results(season_id=2025, year=2026)
