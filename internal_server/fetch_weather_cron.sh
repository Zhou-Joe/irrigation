#!/bin/bash
# Fetch weather data cron script

# Load SECRET_KEY etc. before any manage.py command — Django refuses to start
# in production without it (chmod 600, gitignored, never committed).
if [ -f /home/projects/irrigation/.env.production ]; then
    set -a
    . /home/projects/irrigation/.env.production
    set +a
fi

cd /home/projects/irrigation/internal_server
/home/projects/irrigation/.venv/bin/python3 manage.py fetch_weather --lat 31.1515 --lon 121.6651 --days 7 >> /var/log/fetch_weather.log 2>&1
