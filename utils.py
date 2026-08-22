from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import unescape
import re
from typing import Any

import requests


EVENT_URL = "https://brann.ticketco.events/no/nb/events/{event_id}/seating_arrangement"
SECTION_URL = (
    "https://brann.ticketco.events/no/nb/events/"
    "{event_id}/seating_arrangement/sections/{section_id}.json"
)
SHOP_URL = "https://brann.ticketco.shop"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
}


def get_available_events(shop_url: str = SHOP_URL) -> list[dict[str, Any]]:
    """Return published home matches with their event IDs and names."""
    with requests.Session() as session:
        session.headers.update(REQUEST_HEADERS)
        response = session.get(shop_url, timeout=30)
        response.raise_for_status()

        event_id_pattern = re.compile(
            r"(?:ticketco\.events/no/nb/events/|uploads/event/[^/]+/)(\d+)",
            re.IGNORECASE,
        )
        event_ids = sorted(
            {int(event_id) for event_id in event_id_pattern.findall(response.text)}
        )

        events = []
        for event_id in event_ids:
            event_response = session.get(
                EVENT_URL.format(event_id=event_id), timeout=30
            )
            event_response.raise_for_status()
            title_match = re.search(
                r"<title[^>]*>(.*?)</title>",
                event_response.text,
                re.IGNORECASE | re.DOTALL,
            )
            title = unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
            events.append(
                {
                    "event_id": event_id,
                    "match": title.split(" - select area")[0].strip(),
                    "url": EVENT_URL.format(event_id=event_id),
                }
            )

    return events


def get_available_event_ids(shop_url: str = SHOP_URL) -> list[int]:
    """Return event IDs currently published in the Brann TicketCo shop."""
    return sorted(event["event_id"] for event in get_available_events(shop_url))


def scrape_ticket_sections(event_id: int) -> list[dict[str, Any]]:
    """Scrape section names and ticket status counts for a TicketCo event."""
    snapshot_at = datetime.now(timezone.utc)

    with requests.Session() as session:
        session.headers.update(REQUEST_HEADERS)
        event_response = session.get(EVENT_URL.format(event_id=event_id), timeout=30)
        event_response.raise_for_status()

        section_pattern = re.compile(
            r'xlink:href="sections/(\d+)"[^>]*>.*?'
            r'(?:tc:name|tc:title)="([^"]+)"',
            re.IGNORECASE | re.DOTALL,
        )
        sections = {
            int(match.group(1)): unescape(match.group(2)).strip()
            for match in section_pattern.finditer(event_response.text)
        }

        results = []
        for section_id, section_name in sections.items():
            section_response = session.get(
                SECTION_URL.format(event_id=event_id, section_id=section_id),
                timeout=30,
            )
            section_response.raise_for_status()

            arrangement = section_response.json().get("seating_arrangements", {})
            seats = arrangement.get("seats", [])
            status_counts = Counter(seat.get("status") for seat in seats)
            available = status_counts.get("available", 0)
            unavailable = len(seats) - available
            sold_out = bool(seats) and available == 0
            sold = len(seats) if sold_out else status_counts.get("sold", 0)

            results.append(
                {
                    "snapshot_at": snapshot_at,
                    "event_id": event_id,
                    "section_id": section_id,
                    "section_name": section_name,
                    "total_seats": len(seats),
                    "sold": sold,
                    "available": available,
                    "unavailable": unavailable,
                    "sold_out": sold_out,
                    "other": sum(
                        count
                        for status, count in status_counts.items()
                        if status not in {"sold", "available"}
                    ),
                }
            )

    return results
