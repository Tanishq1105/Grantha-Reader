"""Read-only SQLite snapshot and transactional copy to an empty account database."""
from pathlib import Path
import sqlite3
from sqlalchemy import create_engine, inspect, select, func, text
from sqlalchemy.pool import NullPool
from .account_db import ACCOUNT_SCHEMA, initialize_account_tables
from .auth import account_metadata, users, notebooks, sessions


class MigrationError(ValueError):
    pass


def sqlite_snapshot(path):
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise MigrationError('SQLite source file does not exist. No database was created or changed.')
    uri = source.as_uri() + '?mode=ro'
    def readonly():
        conn = sqlite3.connect(uri, uri=True)
        conn.execute('PRAGMA query_only=ON')
        return conn
    engine = create_engine('sqlite://', creator=readonly, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('BEGIN')
            names = set(inspect(conn).get_table_names())
            if not {'users', 'user_notebooks'} <= names:
                raise MigrationError('This file has no v3 user accounts. If you have not created accounts, start the app to create them in Supabase.')
            accounts = [dict(row) for row in conn.execute(select(users)).mappings()]
            saved = [dict(row) for row in conn.execute(select(notebooks)).mappings()]
            if {row['id'] for row in accounts} != {row['user_id'] for row in saved}:
                raise MigrationError('Source accounts and notebooks are inconsistent. Restore a valid backup before migrating.')
        return accounts, saved
    finally:
        engine.dispose()


def _has_accounts(conn, postgres):
    schema = ACCOUNT_SCHEMA if postgres else None
    names = set(inspect(conn).get_table_names(schema=schema))
    for table in (users, notebooks, sessions):
        if table.name in names and conn.scalar(select(func.count()).select_from(table)):
            return True
    return False


def migrate_users(sqlite_path, target_engine, apply=False):
    accounts, saved = sqlite_snapshot(sqlite_path)
    postgres = target_engine.dialect.name == 'postgresql'
    with target_engine.connect() as conn:
        if _has_accounts(conn, postgres):
            raise MigrationError('The destination already contains accounts or notebooks. Nothing was copied. Existing users are never overwritten.')
    summary = {'users': len(accounts), 'notebooks': len(saved), 'applied': False, 'sessions_copied': 0}
    if not apply:
        return summary
    initialize_account_tables(target_engine, account_metadata)
    with target_engine.begin() as conn:
        if postgres:
            conn.execute(text(f'LOCK TABLE {ACCOUNT_SCHEMA}.users, {ACCOUNT_SCHEMA}.user_notebooks, '
                              f'{ACCOUNT_SCHEMA}.user_sessions IN EXCLUSIVE MODE'))
        else:
            conn.exec_driver_sql('BEGIN IMMEDIATE')
        if _has_accounts(conn, postgres):
            raise MigrationError('Accounts appeared in the destination after the preview. Nothing was copied.')
        if accounts:
            conn.execute(users.insert(), accounts)
            conn.execute(notebooks.insert(), saved)
    return {**summary, 'applied': True}
