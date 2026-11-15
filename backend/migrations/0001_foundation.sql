-- Phase 1 foundation: tenancy, memberships, audit log, and one example tenant table (products).
-- Money is stored as integer minor units (cents). Every tenant table carries workspace_id.
-- Applied by scripts/setup_db.py as the database owner, never by the API.

create type member_role as enum ('owner', 'admin', 'staff', 'driver', 'accountant');

create table workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(name) between 1 and 200),
  base_currency char(3) not null check (base_currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default now()
);

create table memberships (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id uuid not null,
  role member_role not null,
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);
create index on memberships (user_id);

create table products (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name text not null check (length(name) between 1 and 200),
  unit text not null default 'pcs',
  price_minor bigint not null check (price_minor >= 0),
  cost_minor bigint not null check (cost_minor >= 0),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, id)
);
create index on products (workspace_id, created_at desc);

create table audit_log (
  id bigint generated always as identity primary key,
  workspace_id uuid not null references workspaces(id),
  actor_id uuid,
  action text not null,
  entity text not null,
  entity_id uuid,
  after jsonb,
  at timestamptz not null default now()
);
create index on audit_log (workspace_id, id desc);

-- The audit log can never be changed or deleted, even by the owner role.
create function audit_log_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'audit_log is append-only';
end $$;
create trigger audit_log_no_change before update or delete on audit_log
  for each row execute function audit_log_immutable();

-- Per-request context, set by the API inside each transaction.
create function app_user() returns uuid language sql stable as
  $$ select nullif(current_setting('app.user_id', true), '')::uuid $$;
create function app_workspace() returns uuid language sql stable as
  $$ select nullif(current_setting('app.workspace_id', true), '')::uuid $$;

-- Row-level security. FORCE applies it to the table owner too.
alter table workspaces enable row level security;
alter table memberships enable row level security;
alter table products enable row level security;
alter table audit_log enable row level security;
alter table workspaces force row level security;
alter table memberships force row level security;
alter table products force row level security;
alter table audit_log force row level security;

create policy memberships_select on memberships for select
  using (workspace_id = app_workspace() or user_id = app_user());

create policy workspaces_select on workspaces for select
  using (exists (select 1 from memberships m where m.workspace_id = workspaces.id and m.user_id = app_user()));

-- A row is visible only when the request names its workspace AND the user is a member of it.
create policy products_all on products for all
  using (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = products.workspace_id and m.user_id = app_user()))
  with check (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = products.workspace_id and m.user_id = app_user()));

create policy audit_select on audit_log for select
  using (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = audit_log.workspace_id and m.user_id = app_user()));
create policy audit_insert on audit_log for insert
  with check (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = audit_log.workspace_id and m.user_id = app_user()));

-- Creating a workspace happens before the user is a member, so it runs as a controlled function.
create function create_workspace(p_name text, p_currency text) returns uuid
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  ws uuid;
  uid uuid := app_user();
begin
  if uid is null then
    raise exception 'no user context';
  end if;
  insert into workspaces (name, base_currency) values (p_name, p_currency) returning id into ws;
  insert into memberships (workspace_id, user_id, role) values (ws, uid, 'owner');
  insert into audit_log (workspace_id, actor_id, action, entity, entity_id) values (ws, uid, 'create', 'workspace', ws);
  return ws;
end $$;
revoke all on function create_workspace(text, text) from public;

-- Least privilege for the application role. No update or delete on the audit log, no ownership of anything.
grant usage on schema public to tradeos_app;
grant select on workspaces, memberships to tradeos_app;
grant select, insert, update, delete on products to tradeos_app;
grant select, insert on audit_log to tradeos_app;
grant usage on all sequences in schema public to tradeos_app;
grant execute on function create_workspace(text, text) to tradeos_app;
