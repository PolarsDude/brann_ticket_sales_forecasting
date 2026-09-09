from __future__ import annotations
import asyncio
import polars as pl
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from collections import Counter
from datetime import date, datetime, timezone
from html import unescape
import re
import sys
from time import sleep
from typing import Any
from urllib.parse import quote_plus, urljoin
from unicodedata import normalize as unicode_normalize

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
SOFASCORE_EVENT_ID_PATTERN = re.compile(r"#id:(\d+)")
TEAM_NOISE_TOKENS = {
    "fk",
    "if",
    "il",
    "bk",
    "sk",
    "tf",
    "fotball",
    "fkf",
}
SOFASCORE_ALL_REQUESTED_KEYS = {
    "ballPossession",
    "kilometersCovered",
    "bigChanceCreated",
    "totalShotsOnGoal",
    "goalkeeperSaves",
    "numberOfSprints",
    "cornerKicks",
    "fouls",
    "freeKicks",
    "passes",
    "totalTackle",
    "yellowCards",
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


def _extract_sofascore_event_id(match_url: str) -> int:
    """Extract event id from a SofaScore match URL fragment (#id:...)."""
    event_id_match = SOFASCORE_EVENT_ID_PATTERN.search(match_url)
    if event_id_match is None:
        raise ValueError("Fant ikke SofaScore event_id i URL-en. Forventet '#id:<tall>'.")
    return int(event_id_match.group(1))


def _has_running_event_loop() -> bool:
    """Return True when called inside an active asyncio event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _run_blocking_safely(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run blocking Playwright code safely when inside asyncio loop.

    On Windows notebooks, a thread can inherit an event-loop policy that does not
    support subprocess transports, which Playwright needs. Use a process there.
    """
    if not _has_running_event_loop():
        return func(*args, **kwargs)

    if sys.platform == "win32":
        with ProcessPoolExecutor(max_workers=1) as executor:
            return executor.submit(_call_with_args, func, args, kwargs).result()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(func, *args, **kwargs).result()


def _call_with_args(func: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Helper for process executor to call a target with args/kwargs."""
    return func(*args, **kwargs)


def _normalize_team_name_for_matching(name: str) -> str:
    """Return a case/diacritic-insensitive representation for team matching."""
    for source, target in {
        "æ": "ae",
        "ø": "o",
        "å": "a",
        "Æ": "AE",
        "Ø": "O",
        "Å": "A",
        "ä": "a",
        "ö": "o",
        "ü": "u",
        "Ä": "A",
        "Ö": "O",
        "Ü": "U",
    }.items():
        name = name.replace(source, target)

    normalized = unicode_normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_name).strip().casefold()


def _team_match_key(name: str) -> str:
    """Create a canonical team key by removing punctuation and club suffix noise."""
    normalized = _normalize_team_name_for_matching(name)
    tokens = [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", normalized).split()
        if token and token not in TEAM_NOISE_TOKENS
    ]
    return " ".join(tokens)


def _team_names_match(left: str, right: str) -> bool:
    """Match team names across common naming variants."""
    left_key = _team_match_key(left)
    right_key = _team_match_key(right)
    if not left_key or not right_key:
        return False
    return left_key == right_key or left_key in right_key or right_key in left_key


def _parse_optional_match_date(match_date: date | datetime | str | None) -> date | None:
    """Parse match date from date/datetime/ISO string, else None."""
    if match_date is None:
        return None
    if isinstance(match_date, date) and not isinstance(match_date, datetime):
        return match_date
    if isinstance(match_date, datetime):
        return match_date.date()
    try:
        return datetime.fromisoformat(match_date).date()
    except ValueError as error:
        raise ValueError(
            "match_date må være date, datetime, eller ISO-streng (YYYY-MM-DD)."
        ) from error


def _fetch_sofascore_json(page: Any, path: str) -> dict[str, Any]:
    """Fetch SofaScore JSON within browser context to avoid direct-request 403."""
    response = page.evaluate(
        """async (apiPath) => {
            const url = `https://www.sofascore.com${apiPath}`;
            const response = await fetch(url, {
                credentials: 'include',
                headers: { accept: 'application/json' },
            });
            const raw = await response.text();
            let data = null;
            try {
                data = JSON.parse(raw);
            } catch (error) {
                data = null;
            }
            return { ok: response.ok, status: response.status, data, raw };
        }""",
        path,
    )
    if not response.get("ok"):
        raise RuntimeError(
            f"SofaScore API svarte med {response.get('status')} for {path}."
        )
    payload = response.get("data")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ugyldig JSON-format fra SofaScore for {path}.")
    return payload


def _select_sofascore_event(
    events: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    match_date: date | None,
) -> dict[str, Any]:
    """Return the best matching SofaScore event for teams and optional date."""
    matching_events = [
        event for event in events
        if (
            _team_names_match(str(event.get("homeTeam", {}).get("name", "")), home_team)
            and _team_names_match(str(event.get("awayTeam", {}).get("name", "")), away_team)
        ) or (
            _team_names_match(str(event.get("homeTeam", {}).get("name", "")), away_team)
            and _team_names_match(str(event.get("awayTeam", {}).get("name", "")), home_team)
        )
    ]

    if match_date is not None:
        matching_events = [
            event for event in matching_events
            if datetime.fromtimestamp(int(event.get("startTimestamp", 0)), tz=timezone.utc).date() == match_date
        ]

    if not matching_events:
        date_info = f" på dato {match_date.isoformat()}" if match_date else ""
        raise RuntimeError(
            f"Fant ingen SofaScore-kamp mellom {home_team} og {away_team}{date_info}."
        )

    if match_date is None:
        finished_events = [
            event for event in matching_events
            if str(event.get("status", {}).get("type", "")).casefold() == "finished"
        ]
        selection_pool = finished_events or matching_events
    else:
        selection_pool = matching_events

    return max(selection_pool, key=lambda event: int(event.get("startTimestamp", 0)))


def _find_sofascore_event(
    page: Any,
    home_team: str,
    away_team: str,
    match_date: date | None,
) -> dict[str, Any]:
    """Find SofaScore event by searching for both team-order query variants."""
    queries = [
        f"{home_team} {away_team}",
        f"{away_team} {home_team}",
    ]
    last_error: RuntimeError | None = None

    for query_text in queries:
        query = quote_plus(query_text)
        payload = _fetch_sofascore_json(page, f"/api/v1/search/all?q={query}")
        results = payload.get("results", [])
        events = [
            result.get("entity")
            for result in results
            if result.get("type") == "event" and isinstance(result.get("entity"), dict)
        ]
        try:
            return _select_sofascore_event(events, home_team, away_team, match_date)
        except RuntimeError as error:
            last_error = error

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Fant ingen SofaScore-resultater for lagene {home_team} og {away_team}.")


def _extract_xg_from_stats_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract expected goals from period ALL in SofaScore statistics payload."""
    expected_goals_item = _extract_xg_item_from_period(payload, "ALL")
    return {
        "period": "ALL",
        "metric": "expectedGoals",
        "home_xg": expected_goals_item.get("homeValue"),
        "away_xg": expected_goals_item.get("awayValue"),
        "home_display": expected_goals_item.get("home"),
        "away_display": expected_goals_item.get("away"),
    }


def _extract_xg_item_from_period(payload: dict[str, Any], period: str) -> dict[str, Any]:
    """Return SofaScore expectedGoals item for a period (ALL, 1ST, 2ND)."""
    periods = payload.get("statistics", [])
    selected_period = next(
        (entry for entry in periods if entry.get("period") == period),
        None,
    )
    if selected_period is None:
        raise RuntimeError(f"Fant ikke statistikksiden for perioden {period} i SofaScore-responsen.")

    expected_goals_item: dict[str, Any] | None = None
    for group in selected_period.get("groups", []):
        for statistic in group.get("statisticsItems", []):
            if statistic.get("key") == "expectedGoals":
                expected_goals_item = statistic
                break
        if expected_goals_item is not None:
            break

    if expected_goals_item is None:
        raise RuntimeError(f"Fant ikke expectedGoals (xG) i perioden {period}.")

    return expected_goals_item


def _extract_xg_breakdown_from_stats_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract xG for ALL, first half and second half from SofaScore payload."""
    all_item = _extract_xg_item_from_period(payload, "ALL")
    first_item = _extract_xg_item_from_period(payload, "1ST")
    second_item = _extract_xg_item_from_period(payload, "2ND")

    return {
        "home_xg_all": all_item.get("homeValue"),
        "away_xg_all": all_item.get("awayValue"),
        "home_xg_1st": first_item.get("homeValue"),
        "away_xg_1st": first_item.get("awayValue"),
        "home_xg_2nd": second_item.get("homeValue"),
        "away_xg_2nd": second_item.get("awayValue"),
        "home_xg_all_display": all_item.get("home"),
        "away_xg_all_display": all_item.get("away"),
        "home_xg_1st_display": first_item.get("home"),
        "away_xg_1st_display": first_item.get("away"),
        "home_xg_2nd_display": second_item.get("home"),
        "away_xg_2nd_display": second_item.get("away"),
    }


def _normalize_stat_field_name(name: str) -> str:
    """Convert a SofaScore stat key/name into a stable snake_case suffix."""
    normalized = _normalize_team_name_for_matching(name)
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown_stat"


def _extract_period_stats_flat(
    payload: dict[str, Any],
    period: str = "ALL",
    allowed_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Flatten all statistics items for one SofaScore period.

    Output keys are prefixed as home_<stat> and away_<stat>.
    """
    periods = payload.get("statistics", [])
    selected_period = next(
        (entry for entry in periods if entry.get("period") == period),
        None,
    )
    if selected_period is None:
        raise RuntimeError(f"Fant ikke statistikksiden for perioden {period} i SofaScore-responsen.")

    flat_stats: dict[str, Any] = {}
    used_keys: set[str] = set()
    seen_raw_keys: set[str] = set()

    for group in selected_period.get("groups", []):
        for item in group.get("statisticsItems", []):
            raw_key = str(item.get("key") or item.get("name") or "unknown_stat")
            if allowed_keys is not None and raw_key not in allowed_keys:
                continue
            if raw_key in seen_raw_keys:
                continue
            seen_raw_keys.add(raw_key)

            base_key = _normalize_stat_field_name(raw_key)
            key = base_key
            suffix = 2
            while key in used_keys:
                key = f"{base_key}_{suffix}"
                suffix += 1
            used_keys.add(key)

            flat_stats[f"home_{key}"] = item.get("homeValue")
            flat_stats[f"away_{key}"] = item.get("awayValue")

    return flat_stats


def find_sofascore_match_url(
    home_team: str,
    away_team: str,
    match_date: date | datetime | str | None = None,
    timeout_seconds: int = 30,
) -> str:
    """Find SofaScore match URL by teams and optional date."""
    return _run_blocking_safely(
        _find_sofascore_match_url_impl,
        home_team,
        away_team,
        match_date,
        timeout_seconds,
    )


def _find_sofascore_match_url_impl(
    home_team: str,
    away_team: str,
    match_date: date | datetime | str | None = None,
    timeout_seconds: int = 30,
) -> str:
    """Find SofaScore match URL by teams and optional date.

    Uses browser-context API calls via Playwright to avoid SofaScore 403 blocks
    seen with plain requests.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds må være større enn 0.")

    target_date = _parse_optional_match_date(match_date)
    normalized_home = _normalize_team_name_for_matching(home_team)
    normalized_away = _normalize_team_name_for_matching(away_team)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright mangler. Installer med 'uv add playwright' og kjør "
            "'uv run playwright install chromium'."
        ) from error

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=REQUEST_HEADERS["User-Agent"],
            locale="nb-NO",
        )
        page = context.new_page()
        page.goto("https://www.sofascore.com", wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        best_match = _find_sofascore_event(
            page=page,
            home_team=home_team,
            away_team=away_team,
            match_date=target_date,
        )

        browser.close()

    slug = best_match.get("slug")
    custom_id = best_match.get("customId")
    event_id = best_match.get("id")
    if not slug or not custom_id or not event_id:
        raise RuntimeError("Fant kamp, men mangler URL-felter (slug/customId/id) fra SofaScore.")

    return f"https://www.sofascore.com/no/football/match/{slug}/{custom_id}#id:{event_id}"


def scrape_sofascore_all_xg(match_url: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """Return xG from SofaScore statistics period ALL for one match."""
    return _run_blocking_safely(_scrape_sofascore_all_xg_impl, match_url, timeout_seconds)


def _scrape_sofascore_all_xg_impl(match_url: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """Return xG from SofaScore statistics period ALL for one match.

    Uses Playwright because direct requests to SofaScore APIs are often blocked
    outside a browser context.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds må være større enn 0.")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright mangler. Installer med 'uv add playwright' og kjør "
            "'uv run playwright install chromium'."
        ) from error

    event_id = _extract_sofascore_event_id(match_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=REQUEST_HEADERS["User-Agent"],
            locale="nb-NO",
        )
        page = context.new_page()
        page.goto(match_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)

        payload = _fetch_sofascore_json(page, f"/api/v1/event/{event_id}/statistics")
        event_payload = _fetch_sofascore_json(page, f"/api/v1/event/{event_id}")
        browser.close()

    xg = _extract_xg_from_stats_payload(payload)
    all_stats_flat = _extract_period_stats_flat(
        payload,
        period="ALL",
        allowed_keys=SOFASCORE_ALL_REQUESTED_KEYS,
    )
    event = event_payload.get("event", {})
    start_timestamp = int(event.get("startTimestamp", 0))
    event_date = (
        datetime.fromtimestamp(start_timestamp, tz=timezone.utc).date()
        if start_timestamp
        else None
    )

    return {
        "source": match_url,
        "event_id": event_id,
        "season": event_date.year if event_date else None,
        "date": event_date,
        "home_team": event.get("homeTeam", {}).get("name"),
        "away_team": event.get("awayTeam", {}).get("name"),
        **xg,
        **all_stats_flat,
    }


def scrape_sofascore_all_xg_by_teams(
    home_team: str,
    away_team: str,
    match_date: date | datetime | str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Find match URL automatically, then return ALL-tab xG for that match."""
    return _run_blocking_safely(
        _scrape_sofascore_all_xg_by_teams_impl,
        home_team,
        away_team,
        match_date,
        timeout_seconds,
    )


def _scrape_sofascore_all_xg_by_teams_impl(
    home_team: str,
    away_team: str,
    match_date: date | datetime | str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Implementation for team-based xG lookup without asyncio concerns."""
    match_url = _find_sofascore_match_url_impl(
        home_team=home_team,
        away_team=away_team,
        match_date=match_date,
        timeout_seconds=timeout_seconds,
    )
    return _scrape_sofascore_all_xg_impl(match_url=match_url, timeout_seconds=timeout_seconds)


def scrape_eliteserien_all_xg_for_season(
    season_id: int = 2025,
    year: int = 2026,
    delay_seconds: float = 0.2,
    timeout_seconds: int = 30,
) -> list[dict[str, Any]]:
    """Return ALL-tab xG for all completed Eliteserien matches in one season."""
    return _run_blocking_safely(
        _scrape_eliteserien_all_xg_for_season_impl,
        season_id,
        year,
        delay_seconds,
        timeout_seconds,
    )


def _scrape_eliteserien_all_xg_for_season_impl(
    season_id: int = 2025,
    year: int = 2026,
    delay_seconds: float = 0.2,
    timeout_seconds: int = 30,
) -> list[dict[str, Any]]:
    """Return ALL-tab xG for all completed Eliteserien matches in one season.

    Uses Transfermarkt schedule scraping for the match list and SofaScore for xG.
    """
    if delay_seconds < 0:
        raise ValueError("delay_seconds kan ikke være negativ.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds må være større enn 0.")

    matches = scrape_eliteserien_results(season_id=season_id, year=year)
    if not matches:
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright mangler. Installer med 'uv add playwright' og kjør "
            "'uv run playwright install chromium'."
        ) from error

    snapshot_at = datetime.now(timezone.utc)
    xg_rows: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=REQUEST_HEADERS["User-Agent"],
            locale="nb-NO",
        )
        page = context.new_page()
        page.goto("https://www.sofascore.com", wait_until="domcontentloaded", timeout=timeout_seconds * 1000)

        for index, match in enumerate(matches):
            if index:
                sleep(delay_seconds)

            match_date = match.get("date")
            if not isinstance(match_date, date):
                continue

            home_team = str(match.get("home_team", ""))
            away_team = str(match.get("away_team", ""))
            try:
                event = _find_sofascore_event(
                    page=page,
                    home_team=home_team,
                    away_team=away_team,
                    match_date=match_date,
                )
                event_id = int(event["id"])
                slug = str(event.get("slug", ""))
                custom_id = str(event.get("customId", ""))
                if not slug or not custom_id:
                    raise RuntimeError("Manglende slug/customId for SofaScore event.")

                stats_payload = _fetch_sofascore_json(page, f"/api/v1/event/{event_id}/statistics")
                xg_breakdown = _extract_xg_breakdown_from_stats_payload(stats_payload)
                all_stats_flat = _extract_period_stats_flat(
                    stats_payload,
                    period="ALL",
                    allowed_keys=SOFASCORE_ALL_REQUESTED_KEYS,
                )

                home_xg_all = xg_breakdown["home_xg_all"]
                away_xg_all = xg_breakdown["away_xg_all"]
                home_xg_1st = xg_breakdown["home_xg_1st"]
                away_xg_1st = xg_breakdown["away_xg_1st"]
                home_xg_2nd = xg_breakdown["home_xg_2nd"]
                away_xg_2nd = xg_breakdown["away_xg_2nd"]

                xg_rows.append(
                    {
                        "season": year,
                        "date": match_date,
                        "matchday": match.get("matchday"),
                        "home_team": home_team,
                        "away_team": away_team,
                        "result": match.get("result"),
                        "sofascore_event_id": event_id,
                        "sofascore_url": (
                            f"https://www.sofascore.com/no/football/match/{slug}/{custom_id}#id:{event_id}"
                        ),
                        "home_xg": home_xg_all,
                        "away_xg": away_xg_all,
                        "home_xg_display": xg_breakdown["home_xg_all_display"],
                        "away_xg_display": xg_breakdown["away_xg_all_display"],
                        "home_xg_all": home_xg_all,
                        "away_xg_all": away_xg_all,
                        "home_xg_1st": home_xg_1st,
                        "away_xg_1st": away_xg_1st,
                        "home_xg_2nd": home_xg_2nd,
                        "away_xg_2nd": away_xg_2nd,
                        "home_xg_all_display": xg_breakdown["home_xg_all_display"],
                        "away_xg_all_display": xg_breakdown["away_xg_all_display"],
                        "home_xg_1st_display": xg_breakdown["home_xg_1st_display"],
                        "away_xg_1st_display": xg_breakdown["away_xg_1st_display"],
                        "home_xg_2nd_display": xg_breakdown["home_xg_2nd_display"],
                        "away_xg_2nd_display": xg_breakdown["away_xg_2nd_display"],
                        "snapshot_at": snapshot_at,
                        **all_stats_flat,
                    }
                )
                print(
                    f"Done {index + 1}/{len(matches)} | season={year} | date={match_date} | "
                    f"{home_team} vs {away_team} | "
                    f"xG ALL {home_xg_all}-{away_xg_all} | "
                    f"1ST {home_xg_1st}-{away_xg_1st} | "
                    f"2ND {home_xg_2nd}-{away_xg_2nd}"
                )
            except RuntimeError as error:
                print(f"Skipping {home_team} vs {away_team} ({match_date}): {error}")

        browser.close()

    return xg_rows
