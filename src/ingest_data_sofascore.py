"""SofaScore xG ingestion pipeline for Brann football analytics."""
from datetime import datetime
from typing import Sequence

import duckdb
import polars as pl

from config import CURRENT_ELITESERIEN_SEASON, DB_PATH, SCRAPE_DELAY_SECONDS
from utils import scrape_eliteserien_all_xg_for_seasons


def replace_seasons(table_name: str, data: list[dict[str, object]]) -> None:
    """Replace stored rows only for the seasons in ``data``."""
    if not data:
        print(f"No records returned for {table_name}; existing data is unchanged.")
        return

    df = pl.DataFrame(data).with_columns(pl.lit(datetime.now()).alias("ingested_at"))

    with duckdb.connect(str(DB_PATH)) as connection:
        connection.register("new_data", df)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS "
            f"{table_name} AS SELECT * FROM new_data LIMIT 0"
        )
        connection.execute(
            f"DELETE FROM {table_name} "
            "WHERE season IN (SELECT DISTINCT season FROM new_data)"
        )
        connection.execute(f"INSERT INTO {table_name} SELECT * FROM new_data")


def ingest_eliteserien_xg(
    seasons: Sequence[tuple[int, int]],
    delay_seconds: float = SCRAPE_DELAY_SECONDS,
    season_delay_seconds: float = 2.0,
    timeout_seconds: int = 30,
) -> None:
    """Ingest SofaScore xG and match statistics for several seasons."""
    print(f"Fetching xG for {len(seasons)} Eliteserien season(s)...")
    data = scrape_eliteserien_all_xg_for_seasons(
        list(seasons),
        delay_seconds=delay_seconds,
        season_delay_seconds=season_delay_seconds,
        timeout_seconds=timeout_seconds,
    )

    replace_seasons("fct_match_xg", data)

    print(f"Ingested {len(data)} Eliteserien xG records")


if __name__ == "__main__":
    current_season = [CURRENT_ELITESERIEN_SEASON]
    ingest_eliteserien_xg(current_season)