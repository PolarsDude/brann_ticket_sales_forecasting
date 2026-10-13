{{ config(materialized='table') }}


with t1 as (
   {{ union_tables_by_prefix('raw_eliterserien_goal_contributions_') }}
),

/* Create a dimension table for all player names with their latest name and date */
dim_players_1 as (

SELECT
        scorer_player_id AS player_id,
        scorer_name AS player_name,
        date
    FROM t1
    WHERE scorer_player_id IS NOT NULL
      AND scorer_name IS NOT NULL

    UNION ALL

    SELECT
        assist_player_id AS player_id,
        assist_name AS player_name,
        date
    FROM t1
    WHERE assist_player_id IS NOT NULL
      AND assist_name IS NOT NULL
),

/* Filter to get the latest player name for each player */
dim_players_2 as (
SELECT
    distinct
    player_id,
    player_name AS latest_name,
    date AS latest_date
FROM dim_players_1
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_id
    ORDER BY date DESC, player_name ASC
) = 1
),

/* Create the final fact table by joining the goal contributions with the latest player names */
final as (


select 
a.season,
a.date,
a.matchday,
a.home_team,
a.away_team,
b.latest_name as scorer_name,
a.scorer_player_id,
c.latest_name as assist_name,
a.assist_player_id,
a.scorer_team
from t1 a 
left join dim_players_2 b
on a.scorer_player_id = b.player_id
left join dim_players_2 c
on a.assist_player_id = c.player_id

)

select *
from final