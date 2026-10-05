{{ config(materialized='table') }}


with final as (
   {{ union_tables_by_prefix('raw_eliterserien_lineups_') }}
)

select *
from final