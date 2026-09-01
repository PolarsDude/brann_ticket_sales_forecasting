

-- Simple staging: parse result string "3:1" into home_goals and away_goals
select
    date,
    matchday,
    home_team,
    away_team,
    result,
    cast(split_part(result, ':', 1) as integer) as home_goals,
    cast(split_part(result, ':', 2) as integer) as away_goals,
    snapshot_at
from "brann"."raw"."raw_eliteserien_results"