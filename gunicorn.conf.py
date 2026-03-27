# gunicorn.conf.py
# 2 workers: one free to handle incoming webhooks while broadcast runs in background
# timeout 120s: safety net for any slow individual requests (broadcast itself is non-blocking)
workers = 2
timeout = 120
graceful_timeout = 30
