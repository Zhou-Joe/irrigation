#!/bin/bash
# Health check for gunicorn + cloudflared tunnel

# Load SECRET_KEY / SYNC_API_KEY before any gunicorn restart. Without these,
# Django refuses to start (SECRET_KEY) or sync 403s (SYNC_API_KEY). The file is
# chmod 600, gitignored, and not committed.
if [ -f /home/projects/irrigation/.env.production ]; then
    set -a
    . /home/projects/irrigation/.env.production
    set +a
fi

# Check and restart gunicorn if needed
if ! curl -s -o /dev/null -w '' http://localhost:8000/ 2>/dev/null; then
    echo "$(date): Gunicorn down, restarting..."
    pkill -f "gunicorn.*config.wsgi" 2>/dev/null
    sleep 2
    # Bind to loopback only — the cloud tunnel (frpc) is the sole public ingress,
    # so the app must not be reachable on other interfaces. Timeout kept at 600s
    # (overriding SECURITY_AUDIT_FIXES.md's 120s) because large photo/video uploads
    # over the FRP tunnel can take >2min; --graceful-timeout + limit-request-line
    # come from the audit doc.
    /home/projects/irrigation/.venv/bin/gunicorn config.wsgi:application \
        --chdir /home/projects/irrigation/internal_server \
        --bind 127.0.0.1:8000 --workers 4 --timeout 600 --graceful-timeout 30 \
        --limit-request-line 8190 \
        --error-logfile /home/projects/irrigation/gunicorn_error.log \
        --access-logfile - --daemon
    echo "$(date): Gunicorn restarted"
fi

# Check and restart frpc if needed
if ! pgrep -f "frpc -c /opt/frp/frpc.toml" > /dev/null 2>&1; then
    echo "$(date): FRP client down, restarting..."
    nohup /opt/frp/frpc -c /opt/frp/frpc.toml > /tmp/frpc.log 2>&1 &
    echo "$(date): FRP client restarted"
fi
