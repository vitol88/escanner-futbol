-- Durable raw analysis history. Separate from prediction_ledger by design.
-- Run once in Supabase SQL Editor; does not alter or delete existing data.
create table if not exists public.analysis_snapshots (
    snapshot_id text primary key,
    fixture_id text not null,
    recorded_at timestamptz not null,
    analysis_type text not null check (analysis_type in ('goals', 'corners', 'h2h')),
    snapshot_json jsonb not null,
    created_at timestamptz not null default now()
);
create index if not exists analysis_snapshots_recorded_at_idx
    on public.analysis_snapshots (recorded_at, snapshot_id);
create index if not exists analysis_snapshots_fixture_id_idx
    on public.analysis_snapshots (fixture_id);
create index if not exists analysis_snapshots_type_idx
    on public.analysis_snapshots (analysis_type, recorded_at);
alter table public.analysis_snapshots enable row level security;
