from __future__ import annotations

import json
from pathlib import Path

from utils import get_available_events, scrape_ticket_sections


SNAPSHOT_FILE = Path("data/ticket_snapshots.jsonl")


def main() -> None:
    SNAPSHOT_FILE.parent.mkdir(exist_ok=True)

    with SNAPSHOT_FILE.open("a", encoding="utf-8") as file:
        for event in [1187151]:#get_available_events():
            rows = scrape_ticket_sections(event)
            print(rows)
            for row in rows:
                row["snapshot_at"] = row["snapshot_at"].isoformat()
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Snapshots saved to {SNAPSHOT_FILE}")


if __name__ == "__main__":
    main()
