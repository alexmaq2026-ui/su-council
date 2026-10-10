# Gunicorn production configuration for Render & Supabase
import os

port = os.environ.get('PORT', '10000')
bind = f"0.0.0.0:{port}"
workers = int(os.environ.get('WEB_CONCURRENCY', 2))
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = '-'
errorlog = '-'
loglevel = 'info'
