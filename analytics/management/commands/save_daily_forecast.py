"""
Management command: save_daily_forecast
Generates and persists tomorrow's forecast so actuals can be compared later.
Run daily via cron at 17:00 UTC (22:00 PKT):
    0 17 * * * /home/debian/app/demo_back/bin/python /home/debian/app/demo_back/manage.py save_daily_forecast
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from analytics.models import ForecastRecord
from analytics.views import ForecastView
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate and save tomorrow\'s energy forecast (upserts by forecast_date)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help='Override forecast date YYYY-MM-DD (default: next working day)'
        )

    def handle(self, *args, **options):
        from datetime import datetime, timezone as tz, timedelta
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        # Build a fake GET request so ForecastView.get() works normally
        factory = APIRequestFactory()
        fake_request = Request(factory.get('/api/analytics/forecast/'))

        view = ForecastView()
        response = view.get(fake_request)

        if response.status_code != 200:
            self.stderr.write(self.style.ERROR(
                f'ForecastView returned {response.status_code}: {response.data}'
            ))
            return

        payload = response.data
        forecast_date_str = payload.get('forecast_date')
        ref_date_str      = payload.get('ref_date')

        if not forecast_date_str:
            self.stderr.write(self.style.ERROR('No forecast_date in response'))
            return

        from datetime import date
        forecast_date = date.fromisoformat(forecast_date_str)
        ref_date      = date.fromisoformat(ref_date_str) if ref_date_str else None

        # Convert DRF ReturnDict → plain dict so JSONField stores correctly
        import json
        from rest_framework.renderers import JSONRenderer
        plain = json.loads(JSONRenderer().render(payload))

        record, created = ForecastRecord.objects.update_or_create(
            forecast_date=forecast_date,
            defaults={
                'ref_date':      ref_date,
                'forecast_json': plain,
            }
        )

        verb = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} forecast for {forecast_date} (ref: {ref_date})'
        ))
        logger.info('%s forecast record for %s', verb.lower(), forecast_date)
