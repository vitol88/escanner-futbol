-- Verified final match results, stored separately from immutable analysis snapshots.
-- Run once in Supabase SQL Editor. Existing snapshots are not modified or deleted.

create table if not exists public.match_outcome_events (
    event_id bigint generated always as identity primary key,
    fixture_id text not null,
    final_home_score integer not null check (final_home_score >= 0),
    final_away_score integer not null check (final_away_score >= 0),
    final_total_corners integer check (final_total_corners is null or final_total_corners >= 0),
    final_total_yellow_cards integer check (final_total_yellow_cards is null or final_total_yellow_cards >= 0),
    source text not null,
    verified_by text not null,
    verified_at timestamptz not null default now(),
    correction_reason text,
    created_at timestamptz not null default now(),
    check (length(trim(source)) > 0),
    check (length(trim(verified_by)) > 0)
);

create index if not exists match_outcome_events_fixture_idx
    on public.match_outcome_events (fixture_id, event_id desc);

alter table public.match_outcome_events enable row level security;

-- Latest verified result per fixture. Earlier verifications remain auditable.
create or replace view public.latest_match_outcomes as
select distinct on (fixture_id)
    event_id,
    fixture_id,
    final_home_score,
    final_away_score,
    final_total_corners,
    final_total_yellow_cards,
    source,
    verified_by,
    verified_at,
    correction_reason
from public.match_outcome_events
order by fixture_id, event_id desc;

-- Compare saved live projections with verified final results.
-- Goal projection is current score + expected goals remaining.
create or replace view public.analysis_snapshot_evaluation as
select
    s.snapshot_id,
    s.fixture_id,
    s.analysis_type,
    s.recorded_at,
    s.snapshot_json->'match'->>'home' as home_team,
    s.snapshot_json->'match'->>'away' as away_team,
    nullif(s.snapshot_json->'match'->>'minute', '')::integer as minute_at_capture,
    nullif(s.snapshot_json->'match'->>'home_score', '')::integer as home_score_at_capture,
    nullif(s.snapshot_json->'match'->>'away_score', '')::integer as away_score_at_capture,
    o.final_home_score,
    o.final_away_score,
    (o.final_home_score + o.final_away_score) as actual_final_goals,
    case
        when s.analysis_type = 'goals'
         and nullif(s.snapshot_json->'outputs'->>'expected_total_goals_remaining', '') is not null
         and nullif(s.snapshot_json->'match'->>'home_score', '') is not null
         and nullif(s.snapshot_json->'match'->>'away_score', '') is not null
        then
            (nullif(s.snapshot_json->'match'->>'home_score', '')::numeric
             + nullif(s.snapshot_json->'match'->>'away_score', '')::numeric
             + nullif(s.snapshot_json->'outputs'->>'expected_total_goals_remaining', '')::numeric)
        else null
    end as projected_final_goals,
    case
        when s.analysis_type = 'goals'
         and o.fixture_id is not null
         and nullif(s.snapshot_json->'outputs'->>'expected_total_goals_remaining', '') is not null
         and nullif(s.snapshot_json->'match'->>'home_score', '') is not null
         and nullif(s.snapshot_json->'match'->>'away_score', '') is not null
        then abs(
            (nullif(s.snapshot_json->'match'->>'home_score', '')::numeric
             + nullif(s.snapshot_json->'match'->>'away_score', '')::numeric
             + nullif(s.snapshot_json->'outputs'->>'expected_total_goals_remaining', '')::numeric)
            - (o.final_home_score + o.final_away_score)::numeric
        )
        else null
    end as goals_absolute_error,
    nullif(s.snapshot_json->'outputs'->>'projected_total_corners', '')::numeric
        as projected_final_corners,
    o.final_total_corners,
    case
        when s.analysis_type = 'corners'
         and o.final_total_corners is not null
         and nullif(s.snapshot_json->'outputs'->>'projected_total_corners', '') is not null
        then abs(
            nullif(s.snapshot_json->'outputs'->>'projected_total_corners', '')::numeric
            - o.final_total_corners::numeric
        )
        else null
    end as corners_absolute_error,
    o.final_total_yellow_cards,
    o.source as result_source,
    o.verified_at as result_verified_at
from public.analysis_snapshots s
left join public.latest_match_outcomes o
    on o.fixture_id = s.fixture_id
where s.analysis_type in ('goals', 'corners');

-- RLS is enabled intentionally. Access is expected through the server-side
-- Supabase secret/service-role key; do not expose that key in client code.
