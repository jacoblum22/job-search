-- One row per employer, with alternate names merged through seeds/company_aliases.csv.
with open_postings as (
    select
        company,
        count(*)                                        as open_postings,
        count(case when tier in ('A', 'B') then 1 end) as open_ab_postings,
        max(score)                                      as best_open_score
    from {{ ref('fct_postings') }}
    group by company
),

ever as (
    select
        company,
        count(distinct posting_id)                      as postings_ever,
        min(first_seen_on)                              as first_seen_on,
        max(last_seen_at)                               as last_seen_at
    from {{ ref('fct_posting_life') }}
    group by company
),

applications as (
    select company, count(*) as applications, count(case when reached_applied then 1 end) as applied
    from {{ ref('fct_applications') }}
    group by company
),

companies as (
    select company from open_postings
    union
    select company from ever
    union
    select company from applications
)

select
    c.company,
    coalesce(o.open_postings, 0)                        as open_postings,
    coalesce(o.open_ab_postings, 0)                     as open_ab_postings,
    o.best_open_score,
    coalesce(e.postings_ever, 0)                        as postings_ever,
    e.first_seen_on,
    e.last_seen_at,
    coalesce(a.applications, 0)                         as applications,
    coalesce(a.applied, 0)                              as applied
from companies as c
left join open_postings as o using (company)
left join ever as e using (company)
left join applications as a using (company)
