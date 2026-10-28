-- One row per calendar day, for every date axis in Power BI. Runs from just before
-- the earliest posting to 90 days ahead (deadlines can be in the future).
with bounds as (
    select least(min(first_seen_on), date '2026-09-01') as first_day
    from {{ ref('fct_posting_life') }}
),

days as (
    {{ day_rows('(select first_day from bounds)', dbt.dateadd('day', 90, 'current_date')) }}
)

select
    d                                                   as day,
    {{ iso_weekday('d') }}                              as weekday_number,
    {{ weekday_name('d') }}                             as weekday,
    ({{ iso_weekday('d') }} >= 6)                       as is_weekend,
    date_trunc('week', d)::date                         as week_start,
    date_trunc('month', d)::date                        as month_start,
    {{ month_name('d') }}                               as month
from days
