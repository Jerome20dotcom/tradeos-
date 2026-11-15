alter table products
  add column stock_quantity integer not null default 0 check (stock_quantity >= 0);

create table customers (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  name text not null check (length(name) between 1 and 200),
  email text not null default '' check (length(email) <= 254),
  phone text not null default '' check (length(phone) <= 40),
  created_at timestamptz not null default now(),
  unique (workspace_id, id)
);
create index on customers (workspace_id, created_at desc);

create table sales (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  customer_id uuid,
  sold_by uuid not null,
  total_minor bigint not null check (total_minor >= 0),
  created_at timestamptz not null default now(),
  unique (workspace_id, id)
);
create index on sales (workspace_id, created_at desc);

create table sale_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null,
  sale_id uuid not null,
  product_name text not null check (length(product_name) between 1 and 200),
  unit text not null,
  quantity integer not null check (quantity > 0),
  unit_price_minor bigint not null check (unit_price_minor >= 0),
  unit_cost_minor bigint not null check (unit_cost_minor >= 0),
  line_total_minor bigint not null check (line_total_minor >= 0),
  foreign key (workspace_id, sale_id) references sales(workspace_id, id) on delete cascade
);
create index on sale_items (workspace_id, sale_id);

alter table customers enable row level security;
alter table sales enable row level security;
alter table sale_items enable row level security;
alter table customers force row level security;
alter table sales force row level security;
alter table sale_items force row level security;

create policy customers_all on customers for all
  using (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = customers.workspace_id and m.user_id = app_user()))
  with check (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = customers.workspace_id and m.user_id = app_user()));

create policy sales_select on sales for select
  using (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = sales.workspace_id and m.user_id = app_user()));
create policy sales_insert on sales for insert
  with check (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = sales.workspace_id and m.user_id = app_user()));

create policy sale_items_select on sale_items for select
  using (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = sale_items.workspace_id and m.user_id = app_user()));
create policy sale_items_insert on sale_items for insert
  with check (workspace_id = app_workspace()
         and exists (select 1 from memberships m where m.workspace_id = sale_items.workspace_id and m.user_id = app_user()));

grant select, insert, update, delete on customers to tradeos_app;
grant select, insert on sales, sale_items to tradeos_app;
