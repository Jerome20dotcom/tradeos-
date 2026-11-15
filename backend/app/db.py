import psycopg
from psycopg.rows import dict_row

from app.config import app_dsn


def connect() -> psycopg.Connection:
    """Open a connection as the restricted app role. Rows come back as dicts."""
    return psycopg.connect(app_dsn(), row_factory=dict_row)
