"""Data ingestion pipeline for Brann ticket sales forecasting."""
from datetime import datetime
from typing import Sequence
import duckdb
import polars as pl

from config import DB_PATH, ELITESERIEN_SEASONS, SCRAPE_DELAY_SECONDS
from utils import scrape_eliteserien_results_for_seasons


def ingest_eliteserien_results(
    seasons: Sequence[tuple[int, int | None]],
    delay_seconds: float = SCRAPE_DELAY_SECONDS,
) -> None:
    """Ingest results for several Eliteserien seasons into DuckDB."""
    print(f"Fetching {len(seasons)} Eliteserien season(s)...")
    data = scrape_eliteserien_results_for_seasons(
        list(seasons),
        delay_seconds=delay_seconds,
    )

    df = pl.DataFrame(data)
    df = df.with_columns(pl.lit(datetime.now()).alias("ingested_at"))

    with duckdb.connect(str(DB_PATH)) as connection:
        connection.execute("DROP TABLE IF EXISTS raw_eliteserien_results")
        connection.execute("CREATE TABLE raw_eliteserien_results AS SELECT * FROM df")

    print(f"✓ Ingested {len(data)} Eliteserien records")


if __name__ == "__main__":
    ingest_eliteserien_results(ELITESERIEN_SEASONS)
