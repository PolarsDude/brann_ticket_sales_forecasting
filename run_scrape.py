from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from utils import scrape_ticket_sections


DATABASE_FILE = Path(__file__).parent / "ticket_sales.duckdb"
EVENT_IDS = [1187151]


def create_database(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_snapshots (
            snapshot_at TIMESTAMP WITH TIME ZONE NOT NULL,
            event_id INTEGER NOT NULL,
            section_id INTEGER NOT NULL,
            section_name VARCHAR NOT NULL,
            total_seats INTEGER NOT NULL,
            sold INTEGER NOT NULL,
            available INTEGER NOT NULL,
            unavailable INTEGER NOT NULL,
            sold_out BOOLEAN NOT NULL,
            other INTEGER NOT NULL
        )
        """
    )


def main() -> None:
    with duckdb.connect(str(DATABASE_FILE)) as connection:
        create_database(connection)

        for event_id in EVENT_IDS:
            rows = scrape_ticket_sections(event_id)
            snapshot = (
                pl.DataFrame(rows)
                .with_columns([
                    pl.col("snapshot_at").cast(pl.String),
                    pl.col("event_id").cast(pl.Int32),
                    pl.col("section_id").cast(pl.Int32),
                    pl.col("section_name").cast(pl.String),
                    pl.col("total_seats").cast(pl.Int32),
                    pl.col("sold").cast(pl.Int32),
                    pl.col("available").cast(pl.Int32),
                    pl.col("unavailable").cast(pl.Int32),
                    pl.col("sold_out").cast(pl.Boolean),
                    pl.col("other").cast(pl.Int32),
                ])
                .select([
                    "snapshot_at",
                    "event_id",
                    "section_id",
                    "section_name",
                    "total_seats",
                    "sold",
                    "available",
                    "unavailable",
                    "sold_out",
                    "other",
                ])
            )

            if snapshot.is_empty():
                print(f"Ingen seksjoner funnet for event {event_id}")
                continue

            connection.executemany(
                """
                INSERT INTO ticket_snapshots
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                , list(snapshot.iter_rows())
            )
            print(f"Lagret {snapshot.height} seksjoner for event {event_id}")

    print(f"Database lagret i {DATABASE_FILE}")


if __name__ == "__main__":
    main()
