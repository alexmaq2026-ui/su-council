"""
fast_migrate.py
سكريبت ترحيل ومزامنة فوري (UPSERT) لنظام مجلس الجامعة (su-council)
من قاعدة البيانات المحلية SQLite إلى قاعدة بيانات Supabase PostgreSQL المستقلة
"""
import os
import sqlite3
import psycopg2
from psycopg2.extras import execute_values

from dotenv import load_dotenv
load_dotenv()

SQLITE_PATH = "db.sqlite3"
SUPABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.hhqrohrclfekmjqhlaet:Esk777513858@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?sslmode=require"
)
if "sslmode=require" not in SUPABASE_URL:
    sep = "&" if "?" in SUPABASE_URL else "?"
    SUPABASE_URL = f"{SUPABASE_URL}{sep}sslmode=require"

def log(msg):
    print(msg, flush=True)

log("=" * 65)
log("  بدء المزامنة الفورية لبيانات مجلس الجامعة إلى Supabase (su-council)")
log("=" * 65)

sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()

PRIORITY_TABLES = [
    'django_content_type',
    'auth_permission',
    'auth_group',
    'auth_group_permissions',
    'accounts_user',
    'accounts_user_groups',
    'accounts_user_user_permissions',
    'accounts_councilpermission',
    'council_entityseat',
    'council_councilsession',
    'council_sessionstagelog',
    'council_newsessionrequest',
    'council_sessionreadreceipt',
    'council_attendance',
    'council_topic',
    'council_topic_target_seats',
    'council_topicattachment',
    'council_topicrecording',
    'council_vote',
    'council_decision',
    'council_topictable',
    'council_topicdisplaystate',
    'council_speakrequest',
    'council_sessionrecording',
    'council_exitpermit',
    'council_signeddecisionattachment',
    'council_signeddecisiondispatch',
    'council_smstemplate',
    'council_inappnotification',
    'council_notificationlog',
    'council_smartreadersetting',
    'council_smartreaderlog',
    'council_auditlog',
    'council_backuplog',
    'django_admin_log',
]

sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
all_sqlite_tables = {row[0] for row in sqlite_cur.fetchall()} - {'django_session', 'django_migrations'}

ordered_tables = [t for t in PRIORITY_TABLES if t in all_sqlite_tables]
for t in sorted(all_sqlite_tables):
    if t not in ordered_tables:
        ordered_tables.append(t)

pg_conn = psycopg2.connect(SUPABASE_URL, connect_timeout=35)
pg_conn.autocommit = False
pg_cur = pg_conn.cursor()

# Get all boolean columns in one single query
pg_cur.execute("""
    SELECT table_name, column_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND data_type = 'boolean'
""")
bool_cols_by_table = {}
for tname, cname in pg_cur.fetchall():
    bool_cols_by_table.setdefault(tname, set()).add(cname)

total_synced = 0
errors = []

for table in ordered_tables:
    try:
        sqlite_cur.execute(f'SELECT * FROM "{table}"')
        rows = sqlite_cur.fetchall()
        if not rows:
            continue

        columns = [desc[0] for desc in sqlite_cur.description]
        col_list = ", ".join([f'"{c}"' for c in columns])
        bool_cols = bool_cols_by_table.get(table, set())
        bool_indices = {i for i, c in enumerate(columns) if c in bool_cols}

        manager_idx = columns.index('manager_id') if (table == 'accounts_user' and 'manager_id' in columns) else None
        id_idx = columns.index('id') if 'id' in columns else None
        deferred_managers = []

        def convert_row(row):
            result = []
            for i, val in enumerate(row):
                if manager_idx is not None and i == manager_idx and val is not None:
                    deferred_managers.append((row[id_idx], val))
                    result.append(None)
                elif i in bool_indices:
                    result.append(bool(val) if val is not None else None)
                else:
                    result.append(val)
            return tuple(result)

        data = [convert_row(row) for row in rows]

        if 'id' in columns:
            update_cols = [f'"{c}" = EXCLUDED."{c}"' for c in columns if c != 'id']
            conflict_clause = f'ON CONFLICT ("id") DO UPDATE SET {", ".join(update_cols)}' if update_cols else 'ON CONFLICT DO NOTHING'
        else:
            conflict_clause = 'ON CONFLICT DO NOTHING'

        execute_values(
            pg_cur,
            f'INSERT INTO "{table}" ({col_list}) VALUES %s {conflict_clause}',
            data,
            page_size=200
        )

        if deferred_managers:
            for uid, mid in deferred_managers:
                pg_cur.execute('UPDATE "accounts_user" SET "manager_id" = %s WHERE "id" = %s', (mid, uid))

        pg_conn.commit()
        total_synced += len(rows)
        log(f"  ✅ {table}: تمت مزامنة {len(rows):,} سجل")

    except Exception as e:
        pg_conn.rollback()
        err_msg = str(e).strip().splitlines()[0]
        errors.append((table, err_msg))
        log(f"  ❌ {table}: {err_msg}")

sqlite_conn.close()
pg_cur.close()
pg_conn.close()

import reset_sequences

log("=" * 65)
log(f"  اكتملت المزامنة بنجاح! إجمالي السجلات المتزامنة: {total_synced:,} سجل")
if errors:
    log(f"  ⚠️ تنبيهات ({len(errors)}): {errors}")
log("=" * 65)
