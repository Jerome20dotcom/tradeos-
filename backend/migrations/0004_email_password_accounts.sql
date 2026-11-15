create table auth_users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique check (email = lower(email) and length(email) <= 254),
  password_hash text not null,
  created_at timestamptz not null default now()
);

grant select, insert on auth_users to tradeos_app;
