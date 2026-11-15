alter table auth_users add column email_verified_at timestamptz;

create table auth_tokens (
  token_hash char(64) primary key,
  user_id uuid not null references auth_users(id) on delete cascade,
  purpose text not null check (purpose in ('verify_email', 'reset_password')),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now()
);
create index on auth_tokens (user_id, purpose, expires_at desc);

grant select, insert, update on auth_users to tradeos_app;
grant select, insert, update on auth_tokens to tradeos_app;
