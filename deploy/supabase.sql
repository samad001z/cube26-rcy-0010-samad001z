-- Alibi on Supabase Postgres: roles and schema. Run once, as the `postgres` user, with psql
-- (the new passwords are read from the environment with \getenv, never typed as a command-
-- line argument, so they never land in the shell's history or another user's `ps` output):
--
--   ALIBI_OWNER_PASSWORD="$ALIBI_OWNER_PASSWORD" ALIBI_APP_PASSWORD="$ALIBI_APP_PASSWORD" \
--     psql "$SUPABASE_ADMIN_URL" -v ON_ERROR_STOP=1 -f deploy/supabase.sql
--
-- alibi_owner owns the schema and runs the migrations. alibi_app is what the API connects
-- as. Neither is a superuser and neither can bypass row-level security, so the forced RLS
-- policies apply to both. The tables live in their own schema `alibi`, not `public`:
-- Supabase publishes `public` through its Data API (PostgREST) to the anon and
-- authenticated roles; `alibi` is not in the exposed schemas and those roles get nothing.

\getenv owner_pw ALIBI_OWNER_PASSWORD
\getenv app_pw ALIBI_APP_PASSWORD
-- If either is not set, ":'owner_pw'" / ":'app_pw'" below is left unexpanded, which is a
-- syntax error: with -v ON_ERROR_STOP=1 (required, see the header) psql stops with a
-- non-zero exit status rather than creating a role with no password or the literal text.

CREATE ROLE alibi_owner LOGIN PASSWORD :'owner_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE alibi_app LOGIN PASSWORD :'app_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

-- To hand the schema to alibi_owner and set its grants, the creating role must briefly be a
-- member of alibi_owner (Supabase's `postgres` is not a superuser). The membership is
-- dropped at the end, after every grant that needs it.
GRANT alibi_owner TO CURRENT_USER;
CREATE SCHEMA alibi AUTHORIZATION alibi_owner;
REVOKE ALL ON SCHEMA alibi FROM PUBLIC;
GRANT USAGE ON SCHEMA alibi TO alibi_app;

-- Belt and braces: the Data API roles, where they exist, get nothing in `alibi`.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA alibi FROM %I', r);
    END IF;
  END LOOP;
END $$;

REVOKE alibi_owner FROM CURRENT_USER;

-- Every connection of these roles resolves unqualified names in `alibi` only.
ALTER ROLE alibi_owner SET search_path = alibi;
ALTER ROLE alibi_app SET search_path = alibi;
