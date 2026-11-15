"""Create the app role and databases, then apply any new migrations.

Run from the backend folder:  python scripts/setup_db.py
Safe to run again: already-applied migrations are skipped.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from app.config import admin_dsn, app_dsn, get_settings  # noqa: E402

MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    s = get_settings()
    role = sql.Identifier(s.pg_app_user)

    if s.database_url:
        with psycopg.connect(app_dsn(), autocommit=True) as c:
            row = c.execute(
                "select current_user, r.rolsuper, r.rolbypassrls "
                "from pg_roles r where r.rolname = current_user"
            ).fetchone()
            if row is None or row[1] or row[2]:
                raise RuntimeError("The application database role must not be superuser or bypass row security")
            apply_migrations(c, db_label=c.info.dbname)
        print("Database migrations complete.")
        return

    with psycopg.connect(admin_dsn("postgres"), autocommit=True) as c:
        exists = c.execute("select 1 from pg_roles where rolname = %s", (s.pg_app_user,)).fetchone()
        verb = "alter" if exists else "create"
        c.execute(sql.SQL(verb + " role {} login password {} nosuperuser nocreatedb nocreaterole nobypassrls")
                  .format(role, sql.Literal(s.pg_app_password)))
        for db in (s.db_name, s.test_db_name):
            if not c.execute("select 1 from pg_database where datname = %s", (db,)).fetchone():
                c.execute(sql.SQL("create database {}").format(sql.Identifier(db)))
                print("created database", db)

    for db in (s.db_name, s.test_db_name):
        with psycopg.connect(admin_dsn(db), autocommit=True) as c:
            apply_migrations(c, db_label=db)
            c.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(db), role))
    print("Database setup complete.")


def apply_migrations(c: psycopg.Connection, db_label: str) -> None:
    c.execute("create table if not exists schema_migrations "
              "(version text primary key, applied_at timestamptz not null default now())")
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if c.execute("select 1 from schema_migrations where version = %s", (migration.name,)).fetchone():
            continue
        with c.transaction():
            c.execute(migration.read_text(encoding="utf-8"))
            c.execute("insert into schema_migrations (version) values (%s)", (migration.name,))
        print("applied", migration.name, "to", db_label)


if __name__ == "__main__":
    main()
