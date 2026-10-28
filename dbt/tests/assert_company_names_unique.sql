-- Pairs of company names that look like the same employer and aren't mapped
-- in seeds/company_aliases.csv yet. Fix a real pair by adding a seed row;
-- a false match means the rules below need tightening.
{{ config(severity='warn') }}

with names as (
    -- Each company once, after applying the seed's mapping.
    select distinct coalesce(a.canonical, j.company) as company
    from {{ ref('stg_app__jobs') }} as j
    left join {{ ref('company_aliases') }} as a on a.alias = j.company
    where j.company is not null and j.company <> ''
),

normalized as (
    -- Lowercase, punctuation to spaces, company-type endings dropped.
    select
        company,
        trim(regexp_replace(
            regexp_replace(
                regexp_replace(lower(company), '[^a-z0-9]+', ' ', 'g'),
                '\m(inc|ltd|limited|corp|corporation|llc|ulc|lp|plc|co|company)\M', ' ', 'g'),
            '\s+', ' ', 'g')) as norm
    from names
),

words as (
    select company, word, ord
    from normalized,
        unnest(string_to_array(norm, ' ')) with ordinality as w(word, ord)
    where word <> ''
),

initials as (
    -- "university of british columbia" -> "ubc" (small words skipped).
    select company, string_agg(left(word, 1), '' order by ord) as initials, count(*) as n_words
    from words
    where word not in ('of', 'the', 'and', 'for', 'at', 'de', 'du', 'des', 'la', 'le')
    group by company
),

profiled as (
    select n.company, n.norm, replace(n.norm, ' ', '') as squashed, i.initials, i.n_words
    from normalized as n
    left join initials as i using (company)
)

select
    a.company as company_a,
    b.company as company_b,
    case
        when a.norm = b.norm then 'same after cleanup'
        when a.n_words >= 2 and a.initials = b.squashed then 'b is the initials of a'
        when b.n_words >= 2 and b.initials = a.squashed then 'a is the initials of b'
        else 'one contains the other'
    end as why
from profiled as a
join profiled as b on a.company < b.company
where a.norm = b.norm
    or (a.n_words >= 2 and length(b.squashed) between 2 and 6 and a.initials = b.squashed)
    or (b.n_words >= 2 and length(a.squashed) between 2 and 6 and b.initials = a.squashed)
    -- whole words only, so "meta" doesn't match "metabase"
    or (length(b.norm) >= 4 and ' ' || a.norm || ' ' like '% ' || b.norm || ' %')
    or (length(a.norm) >= 4 and ' ' || b.norm || ' ' like '% ' || a.norm || ' %')
