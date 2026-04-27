#!/bin/bash
# Fetch weather data cron script

cd /home/projects/irrigation/internal_server
source .venv/bin/activate
python manage.py fetch_weather --lat 31.1515 --lon 121.6651 --days 7