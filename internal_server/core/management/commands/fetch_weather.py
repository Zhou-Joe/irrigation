"""
Django management command to fetch weather data from Open-Meteo API.
Open-Meteo is free and requires no API key.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from core.models import WeatherData, Zone
import requests
from datetime import datetime
from decimal import Decimal
from collections import defaultdict


class Command(BaseCommand):
    help = 'Fetch weather data from Open-Meteo API and save to database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lat',
            type=float,
            default=None,
            help='Latitude for weather data (default: uses center of first zone)',
        )
        parser.add_argument(
            '--lon',
            type=float,
            default=None,
            help='Longitude for weather data (default: uses center of first zone)',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days to fetch (default: 7)',
        )

    def handle(self, *args, **options):
        lat = options['lat']
        lon = options['lon']

        # If no coordinates provided, try to get from first zone
        if lat is None or lon is None:
            zone = Zone.objects.filter(boundary_points__isnull=False).exclude(boundary_points=[]).first()
            if zone and zone.boundary_points:
                points = zone.boundary_points
                lats = [p.get('lat', p[0] if isinstance(p, list) else 0) for p in points]
                lons = [p.get('lng', p[1] if isinstance(p, list) else 0) for p in points]
                lat = sum(lats) / len(lats)
                lon = sum(lons) / len(lons)
                self.stdout.write(f"Using zone center: ({lat:.4f}, {lon:.4f})")
            else:
                # Default to Shanghai area
                lat, lon = 31.2, 121.5
                self.stdout.write(f"No zones found, using default: ({lat}, {lon})")

        self.fetch_weather(lat, lon, options['days'])

    def fetch_weather(self, lat, lon, days):
        """Fetch weather data from Open-Meteo API and save as one record per day."""
        url = 'https://api.open-meteo.com/v1/forecast'

        params = {
            'latitude': lat,
            'longitude': lon,
            'hourly': 'temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m',
            'timezone': 'auto',
            'forecast_days': days,
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            hourly = data.get('hourly', {})
            times = hourly.get('time', [])
            temperatures = hourly.get('temperature_2m', [])
            humidity = hourly.get('relative_humidity_2m', [])
            precipitation = hourly.get('precipitation', [])
            weather_codes = hourly.get('weather_code', [])
            wind_speeds = hourly.get('wind_speed_10m', [])

            # Group hourly data by date
            daily_data = defaultdict(list)
            for i, time_str in enumerate(times):
                try:
                    dt = datetime.fromisoformat(time_str)
                    date = dt.date()
                    hour = dt.hour

                    daily_data[date].append({
                        'hour': hour,
                        'temp': temperatures[i] if i < len(temperatures) else None,
                        'humidity': humidity[i] if i < len(humidity) else None,
                        'precip': precipitation[i] if i < len(precipitation) else None,
                        'wind': wind_speeds[i] if i < len(wind_speeds) else None,
                        'code': weather_codes[i] if i < len(weather_codes) else None,
                    })
                except Exception as e:
                    self.stderr.write(f"Error parsing time {time_str}: {e}")

            # Save one record per day
            saved_count = 0
            for date, hourly_list in daily_data.items():
                try:
                    weather, created = WeatherData.objects.update_or_create(
                        latitude=round(Decimal(str(lat)), 5),
                        longitude=round(Decimal(str(lon)), 5),
                        date=date,
                        defaults={'hourly_data': hourly_list}
                    )
                    if created:
                        saved_count += 1
                except Exception as e:
                    self.stderr.write(f"Error saving weather for {date}: {e}")

            self.stdout.write(
                self.style.SUCCESS(
                    f"Saved {saved_count} new daily weather records for ({lat:.4f}, {lon:.4f})"
                )
            )

        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"API request failed: {e}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Unexpected error: {e}"))