{{ config(materialized='table') }}


with final as (
   {{ union_tables_by_prefix('raw_match_statistics') }}
)

select *
from final