create extension if not exists "pgcrypto";

create table if not exists public.manufut_profiles (
  user_id text primary key,
  display_name text not null check (char_length(display_name) between 2 and 24),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.manufut_teams (
  id uuid primary key,
  owner_id text not null references public.manufut_profiles(user_id) on delete cascade,
  name text not null check (char_length(name) between 2 and 28),
  short_name varchar(3) not null,
  primary_color varchar(7) not null,
  secondary_color varchar(7) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id)
);

create table if not exists public.manufut_players (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.manufut_teams(id) on delete cascade,
  position smallint not null check (position between 0 and 3),
  name text not null check (char_length(name) between 2 and 20),
  role text not null check (role in ('line', 'goalkeeper')),
  photo_path text,
  unique (team_id, position)
);

create table if not exists public.manufut_rooms (
  code varchar(6) primary key check (code ~ '^[A-F0-9]{6}$'),
  host_id text not null references public.manufut_profiles(user_id),
  status text not null,
  participant_ids text[] not null default '{}',
  state jsonb not null,
  created_at timestamptz not null default now(),
  last_activity timestamptz not null default now()
);

create table if not exists public.manufut_matches (
  room_code varchar(6) primary key references public.manufut_rooms(code) on delete cascade,
  status text not null,
  participant_ids text[] not null,
  score jsonb not null default '{}',
  winner_id text,
  state jsonb not null,
  started_at timestamptz,
  ended_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.manufut_snapshots (
  room_code varchar(6) not null references public.manufut_rooms(code) on delete cascade,
  snapshot_index integer not null,
  reason text not null,
  state jsonb,
  created_at timestamptz not null,
  primary key (room_code, snapshot_index)
);

create table if not exists public.manufut_moves (
  room_code varchar(6) not null references public.manufut_rooms(code) on delete cascade,
  user_id text not null,
  sequence integer not null,
  command jsonb not null,
  created_at timestamptz not null default now(),
  primary key (room_code, user_id, sequence)
);

create index if not exists manufut_rooms_participants_idx
  on public.manufut_rooms using gin (participant_ids);
create index if not exists manufut_matches_participants_idx
  on public.manufut_matches using gin (participant_ids);
create index if not exists manufut_matches_status_updated_idx
  on public.manufut_matches (status, updated_at desc);
create index if not exists manufut_players_team_idx
  on public.manufut_players (team_id);
create index if not exists manufut_moves_room_created_idx
  on public.manufut_moves (room_code, created_at);

alter table public.manufut_profiles enable row level security;
alter table public.manufut_teams enable row level security;
alter table public.manufut_players enable row level security;
alter table public.manufut_rooms enable row level security;
alter table public.manufut_matches enable row level security;
alter table public.manufut_snapshots enable row level security;
alter table public.manufut_moves enable row level security;

revoke all on table public.manufut_profiles from anon, authenticated;
revoke all on table public.manufut_teams from anon, authenticated;
revoke all on table public.manufut_players from anon, authenticated;
revoke all on table public.manufut_rooms from anon, authenticated;
revoke all on table public.manufut_matches from anon, authenticated;
revoke all on table public.manufut_snapshots from anon, authenticated;
revoke all on table public.manufut_moves from anon, authenticated;

grant all on table public.manufut_profiles to service_role;
grant all on table public.manufut_teams to service_role;
grant all on table public.manufut_players to service_role;
grant all on table public.manufut_rooms to service_role;
grant all on table public.manufut_matches to service_role;
grant all on table public.manufut_snapshots to service_role;
grant all on table public.manufut_moves to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('team-media', 'team-media', true, 5242880, array['image/jpeg'])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
