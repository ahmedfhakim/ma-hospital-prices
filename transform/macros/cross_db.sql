{#
  Cross-database helpers. The models run on two engines:
    * DuckDB  -- local development, CI and the free live dashboard
    * Athena  -- the AWS pipeline (Athena runs Trino SQL)
  Most SQL in this project is written to work on both as-is. These macros cover
  the few places where the dialects genuinely differ. Each one dispatches to
  <adapter>__<name>, so adding another warehouse means adding one implementation.
#}

{# ---- regex: does the string match the pattern anywhere? ------------------ #}
{% macro regex_match(expr, pattern) %}{{ return(adapter.dispatch('regex_match')(expr, pattern)) }}{% endmacro %}
{% macro default__regex_match(expr, pattern) %}regexp_matches({{ expr }}, '{{ pattern }}'){% endmacro %}
{% macro athena__regex_match(expr, pattern) %}regexp_like({{ expr }}, '{{ pattern }}'){% endmacro %}

{# ---- median: Athena has no exact median, only approx_percentile ---------- #}
{% macro median(expr) %}{{ return(adapter.dispatch('median')(expr)) }}{% endmacro %}
{% macro default__median(expr) %}median({{ expr }}){% endmacro %}
{% macro athena__median(expr) %}approx_percentile({{ expr }}, 0.5){% endmacro %}

{# ---- first element of an array (NULL when empty; arrays are 1-based in both) #}
{% macro array_first(arr) %}{{ return(adapter.dispatch('array_first')(arr)) }}{% endmacro %}
{% macro default__array_first(arr) %}({{ arr }})[1]{% endmacro %}
{% macro athena__array_first(arr) %}element_at({{ arr }}, 1){% endmacro %}

{% macro array_length(arr) %}{{ return(adapter.dispatch('array_length')(arr)) }}{% endmacro %}
{% macro default__array_length(arr) %}len({{ arr }}){% endmacro %}
{% macro athena__array_length(arr) %}cardinality({{ arr }}){% endmacro %}

{# ---- first code of the given types from a list of {code, type} structs ---- #}
{% macro first_code_of_type(codes, types) %}{{ return(adapter.dispatch('first_code_of_type')(codes, types)) }}{% endmacro %}
{% macro default__first_code_of_type(codes, types) -%}
    list_filter({{ codes }}, x -> x.type in ({{ types }}))[1]
{%- endmacro %}
{% macro athena__first_code_of_type(codes, types) -%}
    element_at(filter({{ codes }}, x -> x.type in ({{ types }})), 1)
{%- endmacro %}

{# ---- every code on an item as one sorted string: 'CPT:70551,RC:0610' ----- #}
{% macro code_signature(codes) %}{{ return(adapter.dispatch('code_signature')(codes)) }}{% endmacro %}
{% macro default__code_signature(codes) -%}
    array_to_string(list_sort(list_transform({{ codes }}, x -> x.type || ':' || x.code)), ',')
{%- endmacro %}
{% macro athena__code_signature(codes) -%}
    array_join(array_sort(transform({{ codes }}, x -> x.type || ':' || x.code)), ',')
{%- endmacro %}

{# ---- a date written as 2026-07-01 or 7/1/2026 ---------------------------- #}
{% macro parse_flexible_date(expr) %}{{ return(adapter.dispatch('parse_flexible_date')(expr)) }}{% endmacro %}
{% macro default__parse_flexible_date(expr) -%}
    cast(coalesce(
        try_strptime(cast({{ expr }} as varchar), '%Y-%m-%d'),
        try_strptime(cast({{ expr }} as varchar), '%m/%d/%Y')
    ) as date)
{%- endmacro %}
{% macro athena__parse_flexible_date(expr) -%}
    cast(coalesce(
        try(date_parse(cast({{ expr }} as varchar), '%Y-%m-%d')),
        try(date_parse(cast({{ expr }} as varchar), '%m/%d/%Y'))
    ) as date)
{%- endmacro %}

{# ---- an ISO-8601 timestamp string like 2026-09-27T17:07:51+00:00 --------- #}
{% macro parse_iso_timestamp(expr) %}{{ return(adapter.dispatch('parse_iso_timestamp')(expr)) }}{% endmacro %}
{% macro default__parse_iso_timestamp(expr) %}cast({{ expr }} as timestamp){% endmacro %}
{% macro athena__parse_iso_timestamp(expr) -%}
    cast(from_iso8601_timestamp(cast({{ expr }} as varchar)) as timestamp)
{%- endmacro %}
