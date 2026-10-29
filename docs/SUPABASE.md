# Supabase user database — Grantha 3.1

Accounts, scrypt password hashes, sessions, login limits, notes, bookmarks and reading progress now use **Supabase PostgreSQL**. They live in the private `grantha_private` schema. A missing connection stops startup; new accounts never fall back to local SQLite.

Flask continues to handle signup/login and connects to PostgreSQL from the server. This release uses Supabase Database; the separate Supabase Auth service is not enabled. Look for your users in **Table Editor → grantha_private → users**, rather than Authentication → Users. Email verification, reset emails and social login remain outside this release.

The actual PDFs and a rebuildable SQLite book index live with the app. This cache contains the scripture index, not new user records. Internet access to Supabase is required for signing in and saving progress.

## Set up your Supabase project

1. Open [Supabase Dashboard](https://supabase.com/dashboard), create a project, and save its database password. Choose a region near your app server and review the plan before creating paid resources.
2. Choose **Connect → Session pooler → URI**. This works on IPv4-only networks, including many local Windows setups. Copy the exact host and username provided by your project.
3. Replace `[YOUR-PASSWORD]` in the copied URI with your **database password**. Percent-encode reserved password characters such as `@`, `#`, `/`, `%`, `?` and spaces. This is not your Supabase website login password or an API key.
4. Keep your existing `.env`. For a new installation only, copy `.env.example` to `.env`. Add this setting locally, using your actual connection URI:

```dotenv
SUPABASE_DB_URL=postgresql://postgres.YOUR_PROJECT:ENCODED_PASSWORD@YOUR_ACTUAL_POOLER_HOST:5432/postgres?sslmode=require
```

The example is only the URI shape: copy the real value from your project's Connect dialog. `postgres://`, `postgresql://` and `postgresql+psycopg://` are accepted. The app selects Psycopg 3, requires encrypted cloud connections and disables automatic prepared statements for pooler compatibility. A direct connection can also be used where IPv6 is available.

Keep the URI in the backend environment. Do not put it in React, a `VITE_` variable, Git, screenshots or chat. No Supabase publishable/anon/service-role API key is needed for this implementation.

## Install and start

In the `grantha` folder, with your Python virtual environment activated:

```bash
python -m pip install -r requirements.txt
npm ci
python -m backend.manage check-user-db
npm run dev
```

The connection check is read-only: it reports whether the private tables exist. The app creates and protects them on first start. Use a fresh Supabase project, or one where `grantha_private` is reserved for Grantha and your database role owns its tables.

Open `http://127.0.0.1:3000` and create an account. That new account is written to Supabase. Existing SQLite users need the following migration first.

## Move existing users from SQLite

Stop the old app and back up the entire `instance/` folder. Keep `.env`, `instance/session-secret` and your PDFs when copying the updated code. Add `SUPABASE_DB_URL`, then preview **before creating accounts in Supabase**:

```bash
python -m backend.manage migrate-users --sqlite instance/grantha-books.db
```

After checking the counts, apply the copy:

```bash
python -m backend.manage migrate-users --sqlite instance/grantha-books.db --apply
python -m backend.manage reload-corpus
npm run dev
```

The preview does not create tables or copy data. Applying preserves IDs, names, emails, password hashes, notes, bookmarks, reading progress and notebook revisions. Users keep their passwords and sign in again. Old sessions and login-attempt records are not copied. The SQLite source is opened read-only and is never deleted or altered. The destination copy is transactional and refuses a destination that already contains accounts: it never merges or overwrites existing users. Keep old app instances stopped while migrating.

Run this locally on the computer holding the old database; the ZIP cannot access it for you. If you have never created users, skip the migration and create your first account in the updated app.

## Access controls and deployment

The backend qualifies account queries with `grantha_private`, revokes schema/table privileges from `PUBLIC` and Supabase's `anon`, `authenticated` and `service_role` roles when present, and enables Row Level Security before the creation transaction commits. It creates no browser-role policies. The trusted Flask connection uses the table owner; signed sessions and per-user query filters enforce notebook ownership.

Keep `grantha_private` out of the Data API's exposed schemas. For a dedicated Grantha project, turn **Enable Data API** off in the Data API integration settings because this app does not use those endpoints. Do not disable APIs used by other applications in a shared project.

TLS uses `sslmode=require`. For server identity verification too, follow Supabase's SSL instructions to set `sslmode=verify-full` with the appropriate `sslrootcert`. App and management-command errors do not print the connection URI or notebook values.

For HTTPS hosting, set `SUPABASE_DB_URL`, `APP_ENV=production`, `SESSION_COOKIE_SECURE=true` and a stable random `SECRET_KEY` of at least 32 characters. Share the same key across replicas. For a private collection, set `SIGNUP_ENABLED=false` after creating intended accounts. The Render template starts with signup disabled and now uses Supabase rather than creating a Render user database. Docker Compose also requires Supabase and keeps its local book cache/session secret in a volume. No deployment has been performed for you.

All app instances that should share accounts must use the same Supabase project and book collection. If saving fails, keep the page open and retry or export the draft before refreshing. There is no offline queued account synchronization.

Optional Gemini vector search concerns the **book index** and still requires a separate PostgreSQL/pgvector connection in `DATABASE_URL`, with appropriate access controls. Leave it disabled for the normal Supabase user setup.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Set SUPABASE_DB_URL` | Add the database URI to the project's `.env` and restart. |
| Connection fails | Use the Session pooler URI, replace its password placeholder, check password encoding and project availability. |
| Private tables cannot be initialized | Check database role permissions/ownership. Reserve `grantha_private` for this app. |
| Destination already contains accounts | Migration will not overwrite them. Use an empty destination or retain its users. |
| No users in Supabase Authentication | This release uses Flask login. Look in Table Editor under `grantha_private`. |
| The old login is missing | Migrate the old SQLite database before creating destination accounts. |

Official references: [connection methods and SSL](https://supabase.com/docs/guides/database/connecting-to-postgres), [Data API security](https://supabase.com/docs/guides/api/securing-your-api), [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security).
