-- One row per day, board and tier: how many postings that board showed for the
-- first time that day. Counts each board's copy separately, so a job on two boards
-- counts on both (fct_postings has the merged view). Built from the snapshot, so
-- postings the cleanup deleted still count once they've been snapshotted.
select
    first_seen_on                                       as day,
    source,
    coalesce(last_tier, 'unscored')                     as tier,
    count(*)                                            as new_postings,
    count(*) filter (where location_category = 'vancouver') as new_vancouver,
    count(*) filter (where location_category = 'remote')    as new_remote
from {{ ref('fct_posting_life') }}
group by 1, 2, 3
