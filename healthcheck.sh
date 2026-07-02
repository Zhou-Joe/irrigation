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
    # Bind to all interfaces — needs to be reachable from the Windows host (which
    # port-forwards to here from its 192.168.137.2 LAN IP for the Maxicom sync
    # agent on 192.168.137.1). The cloud tunnel (frpc) is still the sole public
    # ingress; this only exposes the app on the WSL internal NIC, which the
    # Windows host proxies. Timeout kept at 600s for large photo/video uploads
    # over the FRP tunnel.
    /home/projects/irrigation/.venv/bin/gunicorn config.wsgi:application \
        --chdir /home/projects/irrigation/internal_server \
        --bind 0.0.0.0:8000 --workers 4 --timeout 600 --graceful-timeout 30 \
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
