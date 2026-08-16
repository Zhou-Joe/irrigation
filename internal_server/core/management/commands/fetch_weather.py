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
            help='Number of forecast days to fetch (default: 7)',
        )
        parser.add_argument(
            '--past-days',
            type=int,
            default=0,
            help='Also fetch N past days (max 92) to backfill missed runs (default: 0)',
        )
        parser.add_argument(
            '--archive-days',
            type=int,
            default=10,
            help='Re-backfill past days with ERA5 reanalysis (实际分析值), overwriting the '
                 'forecast values stored by earlier runs. 0 disables. ERA5 lags ~5 days so '
                 'the window is [today-N, today-5] (default: 10)',
        )

    def handle(self, *args, **options):
        lat = options['lat']
        lon = options['lon']

        # If no coordinates provided, try to get from first zone
        if lat is None or lon is None:
            zone = Zone.objects.filter(boundary_points__isnull=False).exclude(boundary_points=[]).first()
            if zone and zone.boundary_points:
                points = zone.boundary_points
                # boundary_points is a list of polygons, each polygon is a list of {lat, lng} dicts
                all_coords = []
                for polygon in points:
                    if isinstance(polygon, list):
                        for coord in polygon:
                            if isinstance(coord, dict):
                                all_coords.append(coord)
                if all_coords:
                    lats = [c.get('lat', 0) for c in all_coords]
                    lons = [c.get('lng', 0) for c in all_coords]
                    lat = sum(lats) / len(lats)
                    lon = sum(lons) / len(lons)
                    self.stdout.write(f"Using zone center: ({lat:.4f}, {lon:.4f})")
                else:
                    lat, lon = 31.2, 121.5
                    self.stdout.write(f"No valid coords in zone, using default: ({lat}, {lon})")
            else:
                # Default to Shanghai area
                lat, lon = 31.2, 121.5
                self.stdout.write(f"No zones found, using default: ({lat}, {lon})")

        self.fetch_weather(lat, lon, options['days'], options['past_days'])
        if options['archive_days'] > 0:
            self.fetch_archive(lat, lon, options['archive_days'])

    def _save_hourly_payload(self, lat, lon, data):
        """Parse an Open-Meteo hourly payload and upsert one WeatherData per day.

        Returns (days_upserted, days_created). update_or_create overwrites any
        existing record for the same (lat, lon, date) — used by both the
        forecast fetch and the ERA5 archive re-backfill.
        """
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
                daily_data[dt.date()].append({
                    'hour': dt.hour,
                    'temp': temperatures[i] if i < len(temperatures) else None,
                    'humidity': humidity[i] if i < len(humidity) else None,
                    'precip': precipitation[i] if i < len(precipitation) else None,
                    'wind': wind_speeds[i] if i < len(wind_speeds) else None,
                    'code': weather_codes[i] if i < len(weather_codes) else None,
                })
            except Exception as e:
                self.stderr.write(f"Error parsing time {time_str}: {e}")

        created = 0
        for date, hourly_list in daily_data.items():
            try:
                _, was_created = WeatherData.objects.update_or_create(
                    latitude=round(Decimal(str(lat)), 5),
                    longitude=round(Decimal(str(lon)), 5),
                    date=date,
                    defaults={'hourly_data': hourly_list}
                )
                if was_created:
                    created += 1
            except Exception as e:
                self.stderr.write(f"Error saving weather for {date}: {e}")
        return len(daily_data), created

    def fetch_weather(self, lat, lon, days, past_days=0):
        """Fetch weather data from Open-Meteo API and save as one record per day."""
        url = 'https://api.open-meteo.com/v1/forecast'

        params = {
            'latitude': lat,
            'longitude': lon,
            'hourly': 'temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m',
            'timezone': 'auto',
            'forecast_days': days,
        }
        if past_days > 0:
            # Backfill mode: forecast API serves up to 92 past days (analysis data).
            params['past_days'] = min(past_days, 92)

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            days_upserted, created = self._save_hourly_payload(lat, lon, response.json())
            self.stdout.write(
                self.style.SUCCESS(
                    f"Saved {created} new daily weather records for ({lat:.4f}, {lon:.4f})"
                )
            )

        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"API request failed: {e}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Unexpected error: {e}"))

    def fetch_archive(self, lat, lon, archive_days):
        """Re-backfill past days from the Historical Weather API (ERA5 再分析).

        The forecast API only gives model values — for convective events
        (雷暴) those can over-predict. ERA5 is the analyzed ("actual")
        record, so overwriting past days with it makes the weather stored
        for historical work orders converge to what really happened. ERA5
        lags ~5 days, so the window is [today-N, today-5]; the daily cron
        rolls the window forward and each date gets its analysis version
        once it ages past the lag.
        """
        from datetime import date as _date, timedelta as _td
        end = _date.today() - _td(days=5)
        start = end - _td(days=archive_days - 1)
        url = 'https://archive-api.open-meteo.com/v1/archive'
        params = {
            'latitude': lat,
            'longitude': lon,
            'hourly': 'temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m',
            'timezone': 'auto',
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
        }
        try:
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()
            days_upserted, _ = self._save_hourly_payload(lat, lon, response.json())
            self.stdout.write(
                self.style.SUCCESS(
                    f"Re-backfilled {days_upserted} days of ERA5 analysis "
                    f"({start} → {end}) for ({lat:.4f}, {lon:.4f})"
                )
            )
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Archive API request failed: {e}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Unexpected error: {e}"))