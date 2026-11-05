-- Daily load (phase 9): replace each RAW table with today's file. Run by
-- `uv run python scripts/snowflake_sync.py load` (and `daily`). Written by Jake, lesson 4.
use role jobsearch_pipeline;
use warehouse jobsearch_wh;

begin;

delete from jobsearch.raw.jobs;
copy into jobsearch.raw.jobs from @jobsearch.raw.lake/jobs/latest/
  match_by_column_name = case_insensitive force = true;

delete from jobsearch.raw.applications;
copy into jobsearch.raw.applications from @jobsearch.raw.lake/applications/latest/
  match_by_column_name = case_insensitive force = true;

delete from jobsearch.raw.pruned_jobs;
copy into jobsearch.raw.pruned_jobs from @jobsearch.raw.lake/pruned_jobs/latest/
  match_by_column_name = case_insensitive force = true;

delete from jobsearch.raw.enrich_attempts;
copy into jobsearch.raw.enrich_attempts from @jobsearch.raw.lake/enrich_attempts/latest/
  match_by_column_name = case_insensitive force = true;

delete from jobsearch.raw.source_cursors;
copy into jobsearch.raw.source_cursors from @jobsearch.raw.lake/source_cursors/latest/
  match_by_column_name = case_insensitive force = true;

commit;
