
    

    create  table
      "brann"."main"."dim_players__dbt_tmp"
  
    
    as (
      WITH all_player_names AS (
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
)

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
    );
    
  