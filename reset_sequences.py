"""
reset_sequences.py
إعادة ضبط تسلسلات PostgreSQL في قاعدة بيانات مجلس الجامعة (su-council) على Supabase
يدعم SERIAL و IDENTITY في PostgreSQL 10+
"""
import os
import psycopg2

SUPABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.hhqrohrclfekmjqhlaet:Esk777513858@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?sslmode=require"
)

print("=" * 55)
print("  إعادة ضبط تسلسلات PostgreSQL لمشروع مجلس الجامعة...")
print("=" * 55)

try:
    conn = psycopg2.connect(SUPABASE_URL, connect_timeout=15)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        SELECT
            n.nspname AS schemaname,
            c.relname  AS tablename,
            a.attname  AS colname,
            s.relname  AS seqname
        FROM pg_class c
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        JOIN pg_depend d ON d.refobjid = c.oid AND d.refobjsubid = a.attnum
        JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r'
          AND n.nspname = 'public'
          AND a.attname = 'id'
        ORDER BY c.relname
    """)
    rows = cur.fetchall()

    reset_count = 0
    for schemaname, tablename, colname, seqname in rows:
        try:
            full_seq = f'"{schemaname}"."{seqname}"'
            cur.execute(
                f'SELECT setval(%s, COALESCE((SELECT MAX("{colname}") FROM "{tablename}"), 1))',
                (full_seq,)
            )
            reset_count += 1
        except Exception as e:
            print(f"  ⚠️  {tablename}.{seqname}: {str(e)[:80]}")

    # Also check IDENTITY columns
    cur.execute("""
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND EXISTS (
            SELECT 1 FROM information_schema.columns c
            WHERE c.table_name = t.table_name
              AND c.column_name = 'id'
              AND c.table_schema = 'public'
              AND c.identity_generation IS NOT NULL
          )
        ORDER BY t.table_name
    """)
    identity_tables = [r[0] for r in cur.fetchall()]
    for tbl in identity_tables:
        try:
            cur.execute(f'SELECT MAX(id) FROM "{tbl}"')
            max_id = cur.fetchone()[0] or 1
            cur.execute(f'ALTER TABLE "{tbl}" ALTER COLUMN id RESTART WITH {max_id + 1}')
            reset_count += 1
        except Exception as e:
            print(f"  ⚠️  IDENTITY {tbl}: {str(e)[:80]}")

    print(f"  ✅ تم ضبط {reset_count} تسلسل بنجاح")
    cur.close()
    conn.close()
    print("=" * 55)

except Exception as e:
    print(f"  ⚠️  خطأ عام: {e}")
    print("=" * 55)
