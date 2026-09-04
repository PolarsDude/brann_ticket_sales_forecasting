

-- One row per recorded goal in an Eliteserien match report.
select
    season,
    date,
    matchday,
    home_team,
    away_team,
    result,
    scorer_team,
    scorer_name,
    ingested_at
from "brann"."main"."raw_eliteserien_goal_scorers"
order by season, date, matchday, scorer_team, scorer_name