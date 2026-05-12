#!/bin/bash
# Fetch weather data cron script
cd /home/projects/irrigation/internal_server
/home/projects/irrigation/.venv/bin/python3 manage.py fetch_weather --lat 31.1515 --lon 121.6651 --days 7 >> /var/log/fetch_weather.log 2>&1
