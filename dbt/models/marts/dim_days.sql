-- One row per calendar day, for every date axis in Power BI. Runs from just before
-- the earliest posting to 90 days ahead (deadlines can be in the future).
with bounds as (
    select least(min(first_seen_on), date '2026-09-01') as first_day
    from {{ ref('fct_posting_life') }}
)

select
    d::date                                             as day,
    extract(isodow from d)::int                         as weekday_number,
    to_char(d, 'Dy')                                    as weekday,
    (extract(isodow from d) >= 6)                       as is_weekend,
    date_trunc('week', d)::date                         as week_start,
    date_trunc('month', d)::date                        as month_start,
    to_char(d, 'Mon YYYY')                              as month
from bounds,
    generate_series(bounds.first_day, current_date + 90, interval '1 day') as d
