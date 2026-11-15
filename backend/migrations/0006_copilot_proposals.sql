create table copilot_proposals (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id uuid not null,
  action_type text not null check (action_type in ('add_product', 'adjust_stock', 'create_customer', 'record_sale')),
  payload jsonb not null,
  status text not null default 'pending' check (status in ('pending', 'confirmed', 'cancelled', 'expired')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  completed_at timestamptz,
  unique (workspace_id, id)
);
create index on copilot_proposals (workspace_id, user_id, status, expires_at);

alter table copilot_proposals enable row level security;
alter table copilot_proposals force row level security;
create policy copilot_proposals_select on copilot_proposals for select
  using (workspace_id = app_workspace() and user_id = app_user()
         and exists (select 1 from memberships m where m.workspace_id = copilot_proposals.workspace_id and m.user_id = app_user()));
create policy copilot_proposals_insert on copilot_proposals for insert
  with check (workspace_id = app_workspace() and user_id = app_user()
         and exists (select 1 from memberships m where m.workspace_id = copilot_proposals.workspace_id and m.user_id = app_user()));
create policy copilot_proposals_update on copilot_proposals for update
  using (workspace_id = app_workspace() and user_id = app_user()
         and exists (select 1 from memberships m where m.workspace_id = copilot_proposals.workspace_id and m.user_id = app_user()))
  with check (workspace_id = app_workspace() and user_id = app_user()
         and exists (select 1 from memberships m where m.workspace_id = copilot_proposals.workspace_id and m.user_id = app_user()));
grant select, insert, update on copilot_proposals to tradeos_app;
