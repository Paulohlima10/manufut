create extension if not exists "pgcrypto";
create table profiles(id uuid primary key references auth.users on delete cascade, display_name text not null check(char_length(display_name) between 2 and 24), created_at timestamptz default now());
create table teams(id uuid primary key default gen_random_uuid(), owner_id uuid not null references profiles on delete cascade, name text not null, short_name varchar(3) not null, crest_path text, primary_color varchar(7) not null, secondary_color varchar(7) not null, created_at timestamptz default now());
create table players(id uuid primary key default gen_random_uuid(), team_id uuid not null references teams on delete cascade, name text not null, role text not null check(role in('line','goalkeeper')), photo_path text, crop jsonb default '{}', captain boolean default false, position smallint not null);
create table matches(id uuid primary key default gen_random_uuid(), room_code varchar(6) not null, status text not null, score jsonb default '{}', winner_id uuid references profiles, started_at timestamptz, ended_at timestamptz, duration_seconds integer);
create table match_participants(match_id uuid references matches on delete cascade, user_id uuid references profiles, team_id uuid references teams, forfeited boolean default false, primary key(match_id,user_id));
create table moves(id bigint generated always as identity primary key, match_id uuid references matches on delete cascade, user_id uuid references profiles, sequence integer not null, command jsonb not null, created_at timestamptz default now(), unique(match_id,user_id,sequence));
create table snapshots(id bigint generated always as identity primary key, match_id uuid references matches on delete cascade, reason text not null, state jsonb not null, created_at timestamptz default now());
alter table profiles enable row level security; alter table teams enable row level security; alter table players enable row level security; alter table matches enable row level security; alter table match_participants enable row level security; alter table moves enable row level security; alter table snapshots enable row level security;
create policy "own profile" on profiles for all using(auth.uid()=id) with check(auth.uid()=id);
create policy "own teams" on teams for all using(auth.uid()=owner_id) with check(auth.uid()=owner_id);
create policy "own players" on players for all using(exists(select 1 from teams t where t.id=team_id and t.owner_id=auth.uid())) with check(exists(select 1 from teams t where t.id=team_id and t.owner_id=auth.uid()));
create policy "participant matches" on matches for select using(exists(select 1 from match_participants p where p.match_id=id and p.user_id=auth.uid()));
create policy "participant rows" on match_participants for select using(user_id=auth.uid());
create policy "participant moves" on moves for select using(exists(select 1 from match_participants p where p.match_id=moves.match_id and p.user_id=auth.uid()));
create policy "participant snapshots" on snapshots for select using(exists(select 1 from match_participants p where p.match_id=snapshots.match_id and p.user_id=auth.uid()));
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values('team-media','team-media',false,5242880,array['image/jpeg','image/png','image/webp']) on conflict do nothing;
create policy "team media owner" on storage.objects for all using(bucket_id='team-media' and (storage.foldername(name))[1]=auth.uid()::text) with check(bucket_id='team-media' and (storage.foldername(name))[1]=auth.uid()::text);

