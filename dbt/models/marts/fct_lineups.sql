{{ config(materialized='table') }}


with final as (
   {{ union_tables_by_prefix('raw_eliterserien_lineups_') }}
),


dim_players as (
   select *
   from {{ref('dim_players')}}
)

select *
from final