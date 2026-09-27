-- Checks a migrated Alibi database. Run as the owner role (bin/check-db). One row per
-- check; `ok` must be true everywhere. :schema is the schema holding the tables.
WITH tables AS (
  SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = :'schema' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
),
grants AS (
  SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) AS privs
  FROM information_schema.role_table_grants
  WHERE table_schema = :'schema' AND grantee = 'alibi_app'
  GROUP BY table_name
)
SELECT 'rls enabled and forced: ' || relname AS "check",
       relrowsecurity AND relforcerowsecurity AS ok
FROM tables
UNION ALL
SELECT 'alibi_app may only SELECT, INSERT: ' || t.relname,
       coalesce(g.privs, '') = 'INSERT,SELECT'
FROM tables t LEFT JOIN grants g ON g.table_name = t.relname
UNION ALL
SELECT 'role cannot bypass RLS and is not superuser: ' || rolname,
       NOT rolbypassrls AND NOT rolsuper
FROM pg_roles WHERE rolname IN ('alibi_owner', 'alibi_app')
UNION ALL
SELECT 'both roles exist', count(*) = 2
FROM pg_roles WHERE rolname IN ('alibi_owner', 'alibi_app')
UNION ALL
SELECT 'tables migrated (at least 9)', (SELECT count(*) FROM tables) >= 9
UNION ALL
SELECT 'no Data API role can use the schema: ' || r.rolname,
       NOT has_schema_privilege(r.oid, n.oid, 'USAGE')
FROM pg_roles r, pg_namespace n
WHERE n.nspname = :'schema' AND r.rolname IN ('anon', 'authenticated')
UNION ALL
SELECT 'connection uses SSL (required on Supabase; false is normal on localhost)',
       coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false)
ORDER BY 1;
