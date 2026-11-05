-- Snowflake setup (phase 9; docs/snowflake-guide.md). Run once, by hand, in a Snowsight SQL file.
-- Written by Jake following the Snowflake course, lessons 2 to 4.

-- ===== Lesson 2: warehouse, database, role and the scripts' login =====
use role accountadmin;

-- 1. The computer that runs queries
create warehouse if not exists jobsearch_wh
  warehouse_size = 'XSMALL' auto_suspend = 60 auto_resume = true initially_suspended = true;

-- 2. The database, and the folder the loaded tables go in
create database if not exists jobsearch;
create schema if not exists jobsearch.raw;

-- 3. The permissions, gathered into one role
create role if not exists jobsearch_pipeline;
grant usage on warehouse jobsearch_wh to role jobsearch_pipeline;
grant usage, create schema on database jobsearch to role jobsearch_pipeline;
grant all on schema jobsearch.raw to role jobsearch_pipeline;
grant role jobsearch_pipeline to role sysadmin;

-- 4. The login the desktop's scripts use (key file only, no password)
create user if not exists jobsearch_bot
  type = service
  rsa_public_key = '<public key printed by: uv run python scripts/snowflake_sync.py make-key>'
  default_role = jobsearch_pipeline
  default_warehouse = jobsearch_wh
  timezone = 'UTC';

-- 5. Give the login its role
grant role jobsearch_pipeline to user jobsearch_bot;

-- ===== Lesson 3: read the files in Azure storage =====
use role accountadmin;

create storage integration if not exists jobsearch_azure
  type = external_stage
  storage_provider = 'AZURE'
  enabled = true
  azure_tenant_id = '9b99b660-59d1-4485-88bf-95057c35680c'
  storage_allowed_locations = ('azure://jobsearchlakejake.blob.core.windows.net/snowflake/');

grant usage on integration jobsearch_azure to role jobsearch_pipeline;

desc storage integration jobsearch_azure;
-- Then in Azure: open the consent URL from AZURE_CONSENT_URL above, and give the app named in
-- AZURE_MULTI_TENANT_APP_NAME "Storage Blob Data Reader" on the storage account.

use role jobsearch_pipeline;
use warehouse jobsearch_wh;

-- use_logical_type: read the files' own column types (else timestamps load as numbers)
create file format if not exists jobsearch.raw.parquet_files type = parquet use_logical_type = true;

create stage if not exists jobsearch.raw.lake
  storage_integration = jobsearch_azure
  url = 'azure://jobsearchlakejake.blob.core.windows.net/snowflake/'
  file_format = jobsearch.raw.parquet_files;

list @jobsearch.raw.lake;

-- ===== Lesson 4: the RAW tables, shaped from the files =====
use role jobsearch_pipeline;
use warehouse jobsearch_wh;
use schema jobsearch.raw;

create table if not exists jobs using template (
  select array_agg(object_construct(*)) from table(infer_schema(
    location => '@lake/jobs/latest/', file_format => 'parquet_files', ignore_case => true)));

create table if not exists applications using template (
  select array_agg(object_construct(*)) from table(infer_schema(
    location => '@lake/applications/latest/', file_format => 'parquet_files', ignore_case => true)));

create table if not exists pruned_jobs using template (
  select array_agg(object_construct(*)) from table(infer_schema(
    location => '@lake/pruned_jobs/latest/', file_format => 'parquet_files', ignore_case => true)));

create table if not exists enrich_attempts using template (
  select array_agg(object_construct(*)) from table(infer_schema(
    location => '@lake/enrich_attempts/latest/', file_format => 'parquet_files', ignore_case => true)));

create table if not exists source_cursors using template (
  select array_agg(object_construct(*)) from table(infer_schema(
    location => '@lake/source_cursors/latest/', file_format => 'parquet_files', ignore_case => true)));

-- The dbt snapshot's history from Postgres, brought over once before the first sf_prod build.
create schema if not exists jobsearch.analytics;

create table if not exists jobsearch.analytics.jobs_snapshot using template (
  select array_agg(object_construct(*)) from table(infer_schema(
    location => '@jobsearch.raw.lake/jobs_snapshot/latest/',
    file_format => 'jobsearch.raw.parquet_files', ignore_case => true)));

copy into jobsearch.analytics.jobs_snapshot
  from @jobsearch.raw.lake/jobs_snapshot/latest/
  match_by_column_name = case_insensitive;
