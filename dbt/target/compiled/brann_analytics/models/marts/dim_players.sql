WITH all_player_names_goal_contributions AS (
    SELECT
        scorer_player_id AS player_id,
        scorer_name AS player_name,
        date
    FROM "brann"."main"."fct_goal_contributions"
    WHERE scorer_player_id IS NOT NULL
      AND scorer_name IS NOT NULL

    UNION ALL

    SELECT
        assist_player_id AS player_id,
        assist_name AS player_name,
        date
    FROM "brann"."main"."fct_goal_contributions"
    WHERE assist_player_id IS NOT NULL
      AND assist_name IS NOT NULL
),

/* Union all years */
all_player_names_lineups_1 as (








    
    





select * from "raw_eliterserien_lineups_2021"
union all by name

select * from "raw_eliterserien_lineups_2022"
union all by name

select * from "raw_eliterserien_lineups_2023"
union all by name

select * from "raw_eliterserien_lineups_2024"
union all by name

select * from "raw_eliterserien_lineups_2025"
union all by name

select * from "raw_eliterserien_lineups_2026"





),


/* All player names from lineups */
all_player_names_lineups_2 AS (

SELECT
    distinct
    player_id,
    player_name AS latest_name,
    date AS latest_date
FROM all_player_names_lineups_1

),


all_player_names AS (
    SELECT * FROM all_player_names_goal_contributions
    UNION ALL
    SELECT * FROM all_player_names_lineups_2
),


final as (
    SELECT
        distinct
        player_id,
        player_name AS latest_name,
        date AS latest_date
    FROM all_player_names
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_id
        ORDER BY date DESC, player_name ASC
    ) = 1
)

select * from final