from __future__ import annotations
import polars as pl
from collections import Counter
from datetime import date, datetime, timezone
from html import unescape
import re
from time import sleep
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


EVENT_URL = "https://brann.ticketco.events/no/nb/events/{event_id}/seating_arrangement"
SECTION_URL = (
    "https://brann.ticketco.events/no/nb/events/"
    "{event_id}/seating_arrangement/sections/{section_id}.json"
)
SHOP_URL = "https://brann.ticketco.shop"
TRANSFERMARKT_MATCHES_URL = (
    "https://www.transfermarkt.com/sk-brann/spielplan/verein/1100/"
    "saison_id/{season_id}/plus/1"
)
TRANSFERMARKT_BASE_URL = "https://www.transfermarkt.com"
ELITESERIEN_SCHEDULE_URL = (
    "https://www.transfermarkt.com/eliteserien/gesamtspielplan/"
    "wettbewerb/NO1/saison_id/{season_id}"
)
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


def scrape_match_results(
    season_id: int = 2025,
    url: str | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Return completed SK Brann matches from Transfermarkt."""
    match_url = url or TRANSFERMARKT_MATCHES_URL.format(season_id=season_id)
    response = requests.get(
        match_url,
        headers={"User-Agent": REQUEST_HEADERS["User-Agent"]},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    snapshot_at = datetime.now(timezone.utc)
    matches: list[dict[str, Any]] = []
    date_pattern = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
    result_pattern = re.compile(r"\b\d+\s*:\s*\d+(?:\s+(?:AET|on pens))?\b")

    for row in soup.select("table tr"):
        cells = row.find_all("td")
        row_text = " ".join(row.stripped_strings)
        date_match = date_pattern.search(row_text)
        result_text = " ".join(cells[-1].stripped_strings) if cells else ""
        result_match = result_pattern.search(result_text)
        report_link = next(
            (
                urljoin(TRANSFERMARKT_BASE_URL, link["href"])
                for link in row.select("a[href*='/spielbericht/']")
                if link.get("href")
            ),
            None,
        )
        team_cells = row.select("td.no-border-links")
        raw_teams = [" ".join(cell.stripped_strings) for cell in team_cells]
        teams = [
            re.sub(r"\s+\(\d+\.\)$", "", team).strip()
            for team in raw_teams
        ]
        if not date_match or not result_match or len(teams) < 2:
            continue

        match_date = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
        if year is not None and match_date.year != year:
            continue

        matches.append(
            {
                "date": match_date,
                "home_team": teams[0],
                "away_team": teams[1],
                "result": result_match.group(0),
                "snapshot_at": snapshot_at,
                "brann_goal_scorers": scrape_brann_goal_scorers(
                    report_link,
                    home_team=teams[0],
                    away_team=teams[1],
                ),
            }
        )

    return matches


def create_table_after_round(
    eliteserien_results: list[dict[str, Any]],
) -> pl.DataFrame:
    matches = pl.DataFrame(eliteserien_results).with_columns([
        pl.col("result")
        .str.split_exact(":", 1)
        .struct.field("field_0")
        .cast(pl.Int64)
        .alias("home_goals"),
        pl.col("result")
        .str.split_exact(":", 1)
        .struct.field("field_1")
        .cast(pl.Int64)
        .alias("away_goals"),
    ])

    home = matches.select([
        "matchday",
        pl.col("home_team").alias("team"),
        pl.col("home_goals").alias("goals_for"),
        pl.col("away_goals").alias("goals_against"),
        pl.when(pl.col("home_goals") > pl.col("away_goals"))
        .then(3)
        .when(pl.col("home_goals") == pl.col("away_goals"))
        .then(1)
        .otherwise(0)
        .alias("points"),
    ])

    away = matches.select([
        "matchday",
        pl.col("away_team").alias("team"),
        pl.col("away_goals").alias("goals_for"),
        pl.col("home_goals").alias("goals_against"),
        pl.when(pl.col("away_goals") > pl.col("home_goals"))
        .then(3)
        .when(pl.col("away_goals") == pl.col("home_goals"))
        .then(1)
        .otherwise(0)
        .alias("points"),
    ])

    round_table = (
        pl.concat([home, away])
        .group_by(["matchday", "team"])
        .agg([
            pl.col("points").sum(),
            pl.col("goals_for").sum(),
            pl.col("goals_against").sum(),
        ])
        .with_columns(
            (pl.col("goals_for") - pl.col("goals_against"))
            .alias("goal_difference")
        )
        .sort(["team", "matchday"])
    )

    return (
        round_table
        .with_columns([
            pl.col("points").cum_sum().over("team").alias("total_points"),
            pl.col("goals_for").cum_sum().over("team").alias("total_goals_for"),
            pl.col("goals_against")
            .cum_sum()
            .over("team")
            .alias("total_goals_against"),
            pl.col("goal_difference")
            .cum_sum()
            .over("team")
            .alias("total_goal_difference"),
        ])
        .with_columns(
            pl.col("total_points")
            .rank("min", descending=True)
            .over("matchday")
            .alias("table_position")
        )
        .sort(["matchday", "table_position", "team"])
    )


def scrape_eliteserien_results(
    season_id: int = 2025,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Return Eliteserien results with their matchday."""
    url = ELITESERIEN_SCHEDULE_URL.format(season_id=season_id)
    response = requests.get(
        url,
        headers={"User-Agent": REQUEST_HEADERS["User-Agent"]},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    snapshot_at = datetime.now(timezone.utc)
    date_pattern = re.compile(r"(\d{2}/\d{2}/\d{2})")
    result_pattern = re.compile(r"^(\d+)\s*:\s*(\d+)")
    matchday_pattern = re.compile(r"(\d+)\.Matchday", re.IGNORECASE)
    scheduled_matches: list[dict[str, Any]] = []

    for table in soup.select("table"):
        headline = table.find_previous(
            "div", class_="content-box-headline"
        )
        matchday_match = (
            matchday_pattern.search(headline.get_text(" ", strip=True))
            if headline
            else None
        )
        if not matchday_match:
            continue
        matchday = int(matchday_match.group(1))
        current_date: date | None = None

        for row in table.select("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            row_text = " ".join(row.stripped_strings)
            date_match = date_pattern.search(row_text)
            if date_match:
                current_date = datetime.strptime(
                    date_match.group(1), "%d/%m/%y"
                ).date()

            if current_date is None or len(cells) < 7:
                continue

            home_team = re.sub(
                r"^\(\d+\.\)\s*|\s+\(\d+\.\)$",
                "",
                " ".join(cells[2].stripped_strings),
            ).strip()
            result_text = " ".join(cells[4].stripped_strings)
            away_team = re.sub(
                r"^\(\d+\.\)\s*|\s+\(\d+\.\)$",
                "",
                " ".join(cells[6].stripped_strings),
            ).strip()
            report_link = next(
                (
                    urljoin(TRANSFERMARKT_BASE_URL, link["href"])
                    for link in row.select("a[href*='/spielbericht/']")
                    if link.get("href")
                ),
                None,
            )
            result_match = result_pattern.fullmatch(result_text)
            if not result_match or not home_team or not away_team:
                continue
            scheduled_matches.append(
                {
                    "date": current_date,
                    "matchday": matchday,
                    "home_team": home_team,
                    "away_team": away_team,
                    "result": result_text,
                    "report_url": report_link,
                }
            )

    scheduled_matches.sort(key=lambda match: match["date"])
    return [
        {
            **match,
            "snapshot_at": snapshot_at,
        }
        for match in scheduled_matches
        if year is None or match["date"].year == year
    ]


def scrape_eliteserien_results_for_seasons(
    seasons: list[tuple[int, int | None]],
    delay_seconds: float = 2.0,
) -> list[dict[str, Any]]:
    """Return Eliteserien results for several seasons, pausing between requests.

    Each item in ``seasons`` is a ``(season_id, year)`` pair. For example,
    ``[(2025, 2026), (2024, 2025)]`` fetches the 2026 and 2025 seasons.
    """
    if delay_seconds < 0:
        raise ValueError("delay_seconds kan ikke være negativ.")

    all_results: list[dict[str, Any]] = []
    for index, (season_id, year) in enumerate(seasons):
        if index:
            sleep(delay_seconds)
        season_results = scrape_eliteserien_results(
            season_id=season_id,
            year=year,
        )
        all_results.extend(
            {**match, "season": year}
            for match in season_results
        )

    return all_results


def scrape_eliteserien_goal_scorers(
    season_id: int = 2025,
    year: int = 2026,
    delay_seconds: float = 2.0,
) -> list[dict[str, Any]]:
    """Return one goal-scorer row per completed Eliteserien match event."""
    if delay_seconds < 0:
        raise ValueError("delay_seconds kan ikke være negativ.")

    matches = scrape_eliteserien_results(season_id=season_id, year=year)
    goal_scorers: list[dict[str, Any]] = []
    completed_matches = [match for match in matches if match["report_url"]]

    for index, match in enumerate(completed_matches):
        print("processing match", index + 1, "of", len(completed_matches))
        if index:
            sleep(delay_seconds)
        for scorer in scrape_goal_scorers(match["report_url"]):
            goal_scorers.append(
                {
                    "season": year,
                    "date": match["date"],
                    "matchday": match["matchday"],
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "result": match["result"],
                    **scorer,
                }
            )

    return goal_scorers


def scrape_eliteserien_goal_scorers_for_seasons(
    seasons: list[tuple[int, int]],
    delay_seconds: float = 2.0,
) -> list[dict[str, Any]]:
    """Return goal scorers for several Eliteserien seasons.

    Each item in ``seasons`` is a ``(season_id, year)`` pair. The scraper
    pauses between both match reports and seasons.
    """
    if delay_seconds < 0:
        raise ValueError("delay_seconds kan ikke være negativ.")

    all_goal_scorers: list[dict[str, Any]] = []
    for index, (season_id, year) in enumerate(seasons):
        if index:
            sleep(delay_seconds)
        print(f"Fetching goal scorers for season {year} (ID: {season_id})...")
        all_goal_scorers.extend(
            scrape_eliteserien_goal_scorers(
                season_id=season_id,
                year=year,
                delay_seconds=delay_seconds,
            )
        )

    return all_goal_scorers


def scrape_goal_scorers(report_url: str | None) -> list[dict[str, str]]:
    """Return scorer and team for every goal registered in a match report."""
    if not report_url:
        return []

    response = requests.get(
        report_url,
        headers={
            "User-Agent": REQUEST_HEADERS["User-Agent"],
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    scorers: list[dict[str, str]] = []

    for event in soup.select(".sb-leiste-ereignis[data-content]"):
        if not event.select_one(".sb-sprite.sb-tor"):
            continue

        event_url = urljoin(report_url, event["data-content"])
        event_response = _get_goal_event(event_url)
        if event_response is None:
            print(f"Skipping unavailable goal event: {event_url}")
            continue
        event_soup = BeautifulSoup(event_response.text, "html.parser")
        team_image = event_soup.select_one(".sb-tt-verein img[title]")
        scorer = event_soup.select_one(".sb-tt-spielername a")

        if team_image and scorer:
            scorers.append(
                {
                    "scorer_team": team_image["title"],
                    "scorer_name": " ".join(scorer.stripped_strings),
                }
            )

    return scorers


def _get_goal_event(url: str, max_attempts: int = 3) -> requests.Response | None:
    """Fetch a goal-event fragment, retrying transient Transfermarkt failures."""
    for attempt in range(max_attempts):
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": REQUEST_HEADERS["User-Agent"],
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt < max_attempts - 1:
                sleep(2 ** attempt)

    return None


def scrape_brann_goal_scorers(
    report_url: str | None,
    home_team: str,
    away_team: str,
) -> list[str]:
    """Return Brann players who scored in a Transfermarkt match report."""
    return [
        scorer["scorer_name"]
        for scorer in scrape_goal_scorers(report_url)
        if scorer["scorer_team"] in {home_team, away_team}
        and "brann" in scorer["scorer_team"].lower()
    ]


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
