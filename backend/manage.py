import argparse
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from .db import engine_for, initialize, Store
from . import vectors, local_rag
from dotenv import load_dotenv
from .db import ROOT
from .account_db import account_engine_for, account_tables_ready, initialize_account_tables, AccountDatabaseError
from .auth import account_metadata
from .migrate_users import migrate_users, MigrationError

def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-db", "reload-corpus", "setup-rag", "embed", "embed-remote", "check-rag", "check-user-db", "init-user-db", "migrate-users"])
    parser.add_argument('--sqlite', type=Path, help='Existing SQLite database to read for migrate-users')
    parser.add_argument('--apply', action='store_true', help='Copy accounts after reviewing a migration preview')
    args = parser.parse_args()
    if (args.sqlite or args.apply) and args.command != 'migrate-users':parser.error('--sqlite and --apply are only for migrate-users')
    if args.command=='setup-rag':
        from .setup_rag import prepare
        try:prepare()
        except (OSError,ValueError,RuntimeError) as error:parser.exit(1,str(error)+'\n')
        return
    if args.command in {'check-user-db', 'init-user-db', 'migrate-users'}:
        engine = None
        try:
            engine = account_engine_for()
            if args.command == 'check-user-db':
                ready = account_tables_ready(engine, account_metadata)
                print('Supabase PostgreSQL connection succeeded. ' + ('Private account tables are ready.' if ready else 'Private account tables will be created when you start the app or migrate users.'))
            elif args.command == 'init-user-db':
                initialize_account_tables(engine, account_metadata)
                print('Private account tables are ready in Supabase PostgreSQL.')
            else:
                if not args.sqlite:parser.error('migrate-users requires --sqlite PATH')
                result = migrate_users(args.sqlite, engine, apply=args.apply)
                print(f"{'Copied' if result['applied'] else 'Preview'}: {result['users']} users, {result['notebooks']} notebooks.")
                print('Password hashes and notebook revisions are preserved; old sessions are not copied.')
                print('Sign in again after starting the app.' if result['applied'] else 'No data was copied. Back up SQLite and stop old app instances, then rerun with --apply.')
        except (AccountDatabaseError, MigrationError) as error:
            parser.exit(1, str(error) + '\n')
        except (SQLAlchemyError, OSError):
            parser.exit(1, 'Database operation failed. Check the source path, Supabase connection, network and database permissions. See docs/SUPABASE.md. No credentials are printed.\n')
        finally:
            if engine is not None:engine.dispose()
        return
    engine = engine_for()
    initialize(engine, replace=args.command == "reload-corpus")
    store = Store(engine)
    if args.command == "embed":
        local_rag.build(store)
    elif args.command=='embed-remote':
        vectors.index(store)
    elif args.command=='check-rag':
        import json
        print(json.dumps(local_rag.RagIndex(store).status(),indent=2))
    print(f"{len(store.books)} books, {len(store.passages)} PDF pages.")

if __name__ == "__main__":
    main()
