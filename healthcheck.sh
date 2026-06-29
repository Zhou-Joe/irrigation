#!/bin/bash
# Health check for gunicorn + cloudflared tunnel

# Check and restart gunicorn if needed
if ! curl -s -o /dev/null -w '' http://localhost:8000/ 2>/dev/null; then
    echo "$(date): Gunicorn down, restarting..."
    pkill -f "gunicorn.*config.wsgi" 2>/dev/null
    sleep 2
    /home/projects/irrigation/.venv/bin/gunicorn config.wsgi:application \
        --chdir /home/projects/irrigation/internal_server \
        --bind 0.0.0.0:8000 --workers 4 --timeout 600 \
        --error-logfile /tmp/gunicorn_error.log \
        --access-logfile - --daemon
    echo "$(date): Gunicorn restarted"
fi

# Check and restart frpc if needed
if ! pgrep -f "frpc -c /opt/frp/frpc.toml" > /dev/null 2>&1; then
    echo "$(date): FRP client down, restarting..."
    nohup /opt/frp/frpc -c /opt/frp/frpc.toml > /tmp/frpc.log 2>&1 &
    echo "$(date): FRP client restarted"
fi
