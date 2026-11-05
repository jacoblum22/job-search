{#
  The few places where Postgres and Snowflake write the same thing differently
  (docs/snowflake-guide.md). Each macro below is called the same way in every model;
  dbt picks the postgres__ or snowflake__ version for the database it's building in.
  The default__ versions are the Postgres ones, which every model was first written in.
#}

{# A regular expression as a string literal. Postgres takes backslashes as they are;
   Snowflake reads '\d' as an escape, so each backslash is doubled. (Not a $$...$$
   string: a pattern ending in $ would run into the closing $$.) #}
{% macro regex(pattern) %}{{ return(adapter.dispatch('regex')(pattern)) }}{% endmacro %}
{% macro default__regex(pattern) %}'{{ pattern | replace("'", "''") }}'{% endmacro %}
{% macro snowflake__regex(pattern) %}'{{ pattern | replace("\\", "\\\\") | replace("'", "''") }}'{% endmacro %}

{# Whether the pattern matches anywhere in the text (Postgres's ~). Snowflake's
   regexp_like has to match the whole text, so it counts matches instead. #}
{% macro regex_found(expr, pattern) %}{{ return(adapter.dispatch('regex_found')(expr, pattern)) }}{% endmacro %}
{% macro default__regex_found(expr, pattern) %}({{ expr }} ~ {{ regex(pattern) }}){% endmacro %}
{% macro snowflake__regex_found(expr, pattern) %}(regexp_instr({{ expr }}, {{ regex(pattern) }}) > 0){% endmacro %}

{# Replace every match (Snowflake replaces all of them unless told otherwise). #}
{% macro regex_replace_all(expr, pattern, replacement) %}{{ return(adapter.dispatch('regex_replace_all')(expr, pattern, replacement)) }}{% endmacro %}
{% macro default__regex_replace_all(expr, pattern, replacement) %}regexp_replace({{ expr }}, {{ regex(pattern) }}, '{{ replacement }}', 'g'){% endmacro %}
{% macro snowflake__regex_replace_all(expr, pattern, replacement) %}regexp_replace({{ expr }}, {{ regex(pattern) }}, '{{ replacement }}'){% endmacro %}

{# The first piece of text the pattern matches. #}
{% macro regex_first(expr, pattern) %}{{ return(adapter.dispatch('regex_first')(expr, pattern)) }}{% endmacro %}
{% macro default__regex_first(expr, pattern) %}substring({{ expr }} from {{ regex(pattern) }}){% endmacro %}
{% macro snowflake__regex_first(expr, pattern) %}regexp_substr({{ expr }}, {{ regex(pattern) }}){% endmacro %}

{# Text to a date in a given layout. The two databases spell layouts differently, so a
   model passes both. Snowflake's try_to_date gives null instead of failing. #}
{% macro parse_date(expr, postgres_format, snowflake_format) %}{{ return(adapter.dispatch('parse_date')(expr, postgres_format, snowflake_format)) }}{% endmacro %}
{% macro default__parse_date(expr, postgres_format, snowflake_format) %}to_date({{ expr }}, '{{ postgres_format }}'){% endmacro %}
{% macro snowflake__parse_date(expr, postgres_format, snowflake_format) %}try_to_date({{ expr }}, '{{ snowflake_format }}'){% endmacro %}

{# Milliseconds since 1970 (as text) to the UTC date. #}
{% macro epoch_ms_to_date(expr) %}{{ return(adapter.dispatch('epoch_ms_to_date')(expr)) }}{% endmacro %}
{% macro default__epoch_ms_to_date(expr) %}to_timestamp({{ expr }}::bigint / 1000.0)::date{% endmacro %}
{% macro snowflake__epoch_ms_to_date(expr) %}to_timestamp({{ expr }}::bigint, 3)::date{% endmacro %}

{# The calendar day a moment falls on in a time zone ('UTC', 'America/Vancouver'). #}
{% macro date_in_zone(ts, zone) %}{{ return(adapter.dispatch('date_in_zone')(ts, zone)) }}{% endmacro %}
{% macro default__date_in_zone(ts, zone) %}({{ ts }} at time zone '{{ zone }}')::date{% endmacro %}
{% macro snowflake__date_in_zone(ts, zone) %}convert_timezone('{{ zone }}', {{ ts }})::date{% endmacro %}

{# Days between two moments, with the fraction of a day (1.5 = a day and a half). #}
{% macro days_between(start_ts, end_ts) %}{{ return(adapter.dispatch('days_between')(start_ts, end_ts)) }}{% endmacro %}
{% macro default__days_between(start_ts, end_ts) %}extract(epoch from ({{ end_ts }} - {{ start_ts }})) / 86400.0{% endmacro %}
{% macro snowflake__days_between(start_ts, end_ts) %}datediff(millisecond, {{ start_ts }}, {{ end_ts }}) / 86400000.0{% endmacro %}

{# The distinct values joined into one text, sorted ("indeed, lever"). #}
{% macro join_distinct(expr, separator) %}{{ return(adapter.dispatch('join_distinct')(expr, separator)) }}{% endmacro %}
{% macro default__join_distinct(expr, separator) %}string_agg(distinct {{ expr }}, '{{ separator }}' order by {{ expr }}){% endmacro %}
{% macro snowflake__join_distinct(expr, separator) %}listagg(distinct {{ expr }}, '{{ separator }}') within group (order by {{ expr }}){% endmacro %}

{# JSON stored as text: read it, then take a field as text or as JSON. #}
{% macro parse_json(expr) %}{{ return(adapter.dispatch('parse_json')(expr)) }}{% endmacro %}
{% macro default__parse_json(expr) %}{{ expr }}::jsonb{% endmacro %}
{% macro snowflake__parse_json(expr) %}try_parse_json({{ expr }}){% endmacro %}

{% macro json_text(json, key) %}{{ return(adapter.dispatch('json_text')(json, key)) }}{% endmacro %}
{% macro default__json_text(json, key) %}({{ json }} ->> '{{ key }}'){% endmacro %}
{% macro snowflake__json_text(json, key) %}({{ json }}['{{ key }}']::varchar){% endmacro %}

{% macro json_field(json, key) %}{{ return(adapter.dispatch('json_field')(json, key)) }}{% endmacro %}
{% macro default__json_field(json, key) %}({{ json }} -> '{{ key }}'){% endmacro %}
{% macro snowflake__json_field(json, key) %}({{ json }}['{{ key }}']){% endmacro %}

{# One row per day from first_day to last_day, both included, in a column named d. #}
{% macro day_rows(first_day, last_day) %}{{ return(adapter.dispatch('day_rows')(first_day, last_day)) }}{% endmacro %}
{% macro default__day_rows(first_day, last_day) %}
    select d::date as d
    from generate_series({{ first_day }}, {{ last_day }}, interval '1 day') as d
{% endmacro %}
{% macro snowflake__day_rows(first_day, last_day) %}
    {# generator needs a fixed row count; 20,000 days is about 55 years #}
    select dateadd(day, row_number() over (order by seq4()) - 1, {{ first_day }})::date as d
    from table(generator(rowcount => 20000))
    qualify d <= {{ last_day }}
{% endmacro %}

{# Weekday 1 (Monday) to 7 (Sunday), its short name (Mon), and the month as "Oct 2026". #}
{% macro iso_weekday(d) %}{{ return(adapter.dispatch('iso_weekday')(d)) }}{% endmacro %}
{% macro default__iso_weekday(d) %}extract(isodow from {{ d }})::int{% endmacro %}
{% macro snowflake__iso_weekday(d) %}dayofweekiso({{ d }}){% endmacro %}

{% macro weekday_name(d) %}{{ return(adapter.dispatch('weekday_name')(d)) }}{% endmacro %}
{% macro default__weekday_name(d) %}to_char({{ d }}, 'Dy'){% endmacro %}
{% macro snowflake__weekday_name(d) %}dayname({{ d }}){% endmacro %}

{% macro month_name(d) %}{{ return(adapter.dispatch('month_name')(d)) }}{% endmacro %}
{% macro default__month_name(d) %}to_char({{ d }}, 'Mon YYYY'){% endmacro %}
{% macro snowflake__month_name(d) %}monthname({{ d }}) || ' ' || year({{ d }}){% endmacro %}
