-- Pairs of company names that look like the same employer and aren't mapped
-- in seeds/company_aliases.csv yet. Fix a real pair by adding a row to that
-- seed; a pair that really is two employers goes in company_not_duplicates.csv.
{{ config(severity='warn') }}
{#- Whole-word edges: Postgres writes them \m and \M, Snowflake \b for both. -#}
{%- set word_start, word_end = ('\\b', '\\b') if target.type == 'snowflake' else ('\\m', '\\M') %}

with names as (
    -- Each company once, after applying the seed's mapping.
    select distinct coalesce(a.canonical, j.company) as company
    from {{ ref('stg_app__jobs') }} as j
    left join {{ ref('company_aliases') }} as a on a.alias = j.company
    where j.company is not null and j.company <> ''
),

normalized as (
    -- Lowercase, punctuation to spaces, company-type endings and a leading
    -- "the" dropped: "The Boeing Company" -> "boeing".
    select
        company,
        {{ regex_replace_all(
            'trim(' ~ regex_replace_all(
                regex_replace_all(
                    regex_replace_all('lower(company)', '[^a-z0-9]+', ' '),
                    word_start ~ '(inc|ltd|limited|corp|corporation|llc|ulc|lp|plc|co|company)' ~ word_end, ' '),
                '\s+', ' ') ~ ')',
            '^the ', '') }} as norm
    from names
),

words as (
    {% if target.type == 'snowflake' %}
    select company, w.value::varchar as word, w.index as ord
    from normalized,
        lateral split_to_table(norm, ' ') as w
    where w.value <> ''
    {% else %}
    select company, word, ord
    from normalized,
        unnest(string_to_array(norm, ' ')) with ordinality as w(word, ord)
    where word <> ''
    {% endif %}
),

initials as (
    -- "university of british columbia" -> "ubc" (small words skipped).
    select company, {{ dbt.listagg('left(word, 1)', "''", 'order by ord') }} as initials, count(*) as n_words
    from words
    where word not in ('of', 'the', 'and', 'for', 'at', 'de', 'du', 'des', 'la', 'le')
    group by company
),

profiled as (
    select n.company, n.norm, replace(n.norm, ' ', '') as squashed, i.initials, i.n_words
    from normalized as n
    left join initials as i using (company)
),

pairs as (
    select
        a.company as company_a,
        b.company as company_b,
        case
            when a.norm = b.norm then 'same after cleanup'
            when a.initials = b.squashed then 'b is the initials of a'
            when b.initials = a.squashed then 'a is the initials of b'
            else 'one starts with the other'
        end as why
    from profiled as a
    join profiled as b on a.company < b.company
    where a.norm = b.norm
        -- initials of 3 to 6 letters ("TD" matches too many names)
        or (a.n_words >= 2 and length(b.squashed) between 3 and 6 and a.initials = b.squashed)
        or (b.n_words >= 2 and length(a.squashed) between 3 and 6 and b.initials = a.squashed)
        -- the shorter name is the first whole words of the longer one
        -- ("Amazon" / "Amazon Science"), and doesn't end on a small word
        -- (a stray "City of" would match every city)
        or (length(b.norm) >= 4 and not {{ regex_found('b.norm', ' (of|and|the|for)$') }} and a.norm like b.norm || ' %')
        or (length(a.norm) >= 4 and not {{ regex_found('a.norm', ' (of|and|the|for)$') }} and b.norm like a.norm || ' %')
)

select p.*
from pairs as p
left join {{ ref('company_not_duplicates') }} as nd
    on (nd.company_a = p.company_a and nd.company_b = p.company_b)
    or (nd.company_a = p.company_b and nd.company_b = p.company_a)
where nd.company_a is null
