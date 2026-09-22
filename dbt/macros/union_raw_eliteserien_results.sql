{% macro union_raw_eliteserien_results() %}

{% set tables_query %}
    select table_name
    from information_schema.tables
    where table_schema = 'main'
      and table_name like 'raw_eliteserien_results_%'
    order by table_name
{% endset %}

{% set season_tables = [] %}
{% if execute %}
    {% set results = run_query(tables_query) %}
    {% set season_tables = results.columns[0].values() %}
{% endif %}

{% if execute and season_tables | length == 0 %}
    {{ exceptions.raise_compiler_error("No raw_eliteserien_results_<season> tables found in the database.") }}
{% endif %}

{% for table_name in season_tables %}
select * from {{ adapter.quote(table_name) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}

{% endmacro %}
