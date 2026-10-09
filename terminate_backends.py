import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

print("Terminating other database connections on Supabase to release any locks...")
try:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT pg_terminate_backend(pid) 
            FROM pg_stat_activity 
            WHERE datname = current_database() 
              AND pid <> pg_backend_pid()
              AND usename = current_user;
        """)
        terminated = cursor.fetchall()
        print(f"Successfully terminated {len(terminated)} other connection(s).")
except Exception as e:
    print(f"Error terminating backends: {e}")
