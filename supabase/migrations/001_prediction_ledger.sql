-- Durable append-only prediction history for Football Lab.
-- Run once in Supabase SQL Editor. Do not drop or truncate existing tables.
create table if not exists public.prediction_ledger (
    prediction_id text primary key,
    fixture_id text not null,
    recorded_at timestamptz not null,
    record_json jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists prediction_ledger_recorded_at_idx
    on public.prediction_ledger (recorded_at, prediction_id);

create index if not exists prediction_ledger_fixture_id_idx
    on public.prediction_ledger (fixture_id);

alter table public.prediction_ledger enable row level security;
