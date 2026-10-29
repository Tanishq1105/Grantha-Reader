"""Server-only Supabase PostgreSQL storage for accounts and notebooks."""
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.schema import CreateSchema
from sqlalchemy.pool import NullPool

ACCOUNT_SCHEMA = 'grantha_private'


class AccountDatabaseError(ValueError):
    """Safe configuration error which never includes connection credentials."""


def account_engine_for(url=None):
    explicit = url is not None
    raw = url if explicit else os.getenv('SUPABASE_DB_URL', '').strip()
    if not raw:
        raise AccountDatabaseError('Set SUPABASE_DB_URL in .env. See docs/SUPABASE.md, then run python -m backend.manage check-user-db.')
    try:
        parsed = make_url(raw)
        host = parsed.host
        parsed.port  # Validate a supplied port without echoing the URI on error.
    except (ArgumentError, ValueError, TypeError):
        raise AccountDatabaseError('SUPABASE_DB_URL must be a PostgreSQL URI from Supabase Connect, not a project URL or API key.') from None
    # Explicit Python injection is reserved for automated tests, not runtime fallback.
    if explicit and parsed.get_backend_name() == 'sqlite':
        return create_engine(parsed, poolclass=NullPool, connect_args={'timeout': 30}, hide_parameters=True)
    if parsed.drivername not in {'postgres', 'postgresql', 'postgresql+psycopg'}:
        raise AccountDatabaseError('SUPABASE_DB_URL must use postgresql:// or postgresql+psycopg://.')
    if not host or not parsed.username or not parsed.password or not parsed.database:
        raise AccountDatabaseError('The database URI needs a host, username, database password and database name. Copy it from Supabase Connect.')
    if any(marker in raw for marker in ('[YOUR-PASSWORD]', '[PROJECT-REF]', '[POOLER-HOST]')):
        raise AccountDatabaseError('Replace the placeholders in SUPABASE_DB_URL with your own Supabase connection details.')
    local = host in {'127.0.0.1', 'localhost', '::1'}
    sslmode = parsed.query.get('sslmode', 'disable' if explicit and local else 'require')
    if (not local or not explicit) and sslmode not in {'require', 'verify-ca', 'verify-full'}:
        raise AccountDatabaseError('Cloud account connections require sslmode=require or certificate verification.')
    parsed = parsed.set(drivername='postgresql+psycopg').update_query_dict({'sslmode': sslmode})
    engine = create_engine(parsed, pool_size=2, max_overflow=0, pool_timeout=15,
        pool_pre_ping=True, pool_recycle=300, hide_parameters=True,
        connect_args={'connect_timeout': 10, 'prepare_threshold': None})
    return engine.execution_options(schema_translate_map={None: ACCOUNT_SCHEMA})


def initialize_account_tables(engine, metadata):
    """Create and secure only this app's private schema in one transaction."""
    with engine.begin() as conn:
        if engine.dialect.name == 'postgresql':
            conn.execute(text('SELECT pg_advisory_xact_lock(774022)'))
            conn.execute(CreateSchema(ACCOUNT_SCHEMA, if_not_exists=True))
        metadata.create_all(conn)
        if engine.dialect.name != 'postgresql':
            return
        roles = ['PUBLIC'] + list(conn.execute(text(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')"
        )).scalars())
        quote = engine.dialect.identifier_preparer.quote
        schema = quote(ACCOUNT_SCHEMA)
        for role in roles:
            grantee = 'PUBLIC' if role == 'PUBLIC' else quote(role)
            conn.execute(text(f'REVOKE ALL ON SCHEMA {schema} FROM {grantee}'))
            conn.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {grantee}'))
            conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {grantee}'))
        for table in metadata.tables.values():
            conn.execute(text(f'ALTER TABLE {schema}.{quote(table.name)} ENABLE ROW LEVEL SECURITY'))
        # The trusted Flask backend connects as table owner; browser roles get no policies.


def account_tables_ready(engine, metadata):
    schema = ACCOUNT_SCHEMA if engine.dialect.name == 'postgresql' else None
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
        names = set(inspect(conn).get_table_names(schema=schema))
    return all(table.name in names for table in metadata.tables.values())
