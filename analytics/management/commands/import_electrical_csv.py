"""
Django management command to import electrical device data from CSV file.

CSV Structure:
- Row 0: Major department
- Row 1: Sub Department  
- Row 2: Sub Process
- Row 3: Floor/LT#
- Row 4: Serial Number
- Row 5: Device Name
- Row 6: Headers (DAY, DATE, Daily Units (kWh))
- Row 7+: Data rows
"""

import csv
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from modbus.models import ModbusDevice
from analytics.models import EnergySummary


class Command(BaseCommand):
    help = 'Import electrical device data from CSV file'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to the CSV file'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing'
        )

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        dry_run = options['dry_run']

        if not os.path.exists(csv_file):
            self.stdout.write(self.style.ERROR(f'CSV file not found: {csv_file}'))
            return

        self.stdout.write(f'Reading CSV file: {csv_file}')
        
        # Read CSV
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        if len(rows) < 8:
            self.stdout.write(self.style.ERROR('CSV file does not have enough rows'))
            return

        # Parse device metadata (rows 0-5)
        # Row 0: Major department
        # Row 1: Sub Department
        # Row 2: Sub Process
        # Row 3: Floor/LT#
        # Row 4: Serial Number
        # Row 5: Device Name
        
        major_dept_row = rows[0]
        sub_dept_row = rows[1]
        sub_process_row = rows[2]
        floor_row = rows[3]
        serial_row = rows[4]
        device_name_row = rows[5]

        # Find all device columns (starting from column C, index 2)
        devices_info = []
        for col_idx in range(2, len(device_name_row)):
            device_name = device_name_row[col_idx].strip() if col_idx < len(device_name_row) else ''
            
            # Skip empty columns
            if not device_name:
                continue
            
            # Get metadata for this device
            major_dept = major_dept_row[col_idx].strip() if col_idx < len(major_dept_row) else ''
            sub_dept = sub_dept_row[col_idx].strip() if col_idx < len(sub_dept_row) else ''
            sub_process = sub_process_row[col_idx].strip() if col_idx < len(sub_process_row) else ''
            floor = floor_row[col_idx].strip() if col_idx < len(floor_row) else ''
            serial = serial_row[col_idx].strip() if col_idx < len(serial_row) else ''

            devices_info.append({
                'col_idx': col_idx,
                'name': device_name,
                'major_dept': major_dept,
                'sub_dept': sub_dept,
                'sub_process': sub_process,
                'floor': floor,
                'serial': serial,
            })

        self.stdout.write(f'Found {len(devices_info)} devices')

        # Parse data rows (starting from row 7)
        data_rows = rows[7:]
        
        stats = {
            'devices_created': 0,
            'devices_updated': 0,
            'daily_records_created': 0,
            'daily_records_updated': 0,
            'errors': 0,
        }

        if not dry_run:
            with transaction.atomic():
                # Process each device
                for device_info in devices_info:
                    device = self.get_or_create_device(device_info, stats)
                    if not device:
                        continue

                    # Process data rows for this device
                    col_idx = device_info['col_idx']
                    for row_idx, data_row in enumerate(data_rows):
                        if col_idx >= len(data_row):
                            continue
                        
                        # Parse date (column B, index 1)
                        if len(data_row) < 2:
                            continue
                        
                        date_str = data_row[1].strip() if len(data_row) > 1 else ''
                        if not date_str:
                            continue

                        # Parse date - try multiple formats
                        date_obj = None
                        date_formats = [
                            '%m/%d/%Y',      # 7/1/2025
                            '%Y-%m-%d',      # 2025-07-01
                            '%d-%b-%y',      # 1-Aug-25
                            '%d-%b-%Y',      # 1-Aug-2025
                            '%b %d, %Y',     # Aug 1, 2025
                        ]
                        
                        for fmt in date_formats:
                            try:
                                date_obj = datetime.strptime(date_str, fmt).date()
                                break
                            except ValueError:
                                continue
                        
                        if not date_obj:
                            # Skip this row if date can't be parsed
                            continue

                        # Get kWh value
                        kwh_str = data_row[col_idx].strip() if col_idx < len(data_row) else ''
                        
                        # Skip empty values, "-", or invalid
                        if not kwh_str or kwh_str == '-' or kwh_str == '':
                            continue

                        try:
                            kwh_value = float(kwh_str)
                            if kwh_value < 0:
                                continue
                        except (ValueError, TypeError):
                            continue

                        # Create or update daily summary
                        timestamp = timezone.make_aware(
                            datetime.combine(date_obj, datetime.min.time())
                        )

                        daily_summary, created = EnergySummary.objects.get_or_create(
                            device=device,
                            timestamp=timestamp,
                            interval_type='daily',
                            defaults={
                                'total_energy_kwh': kwh_value,
                                'avg_power_kw': kwh_value / 24.0,  # Approximate
                                'max_power_kw': kwh_value / 24.0,
                                'min_power_kw': 0,
                                'tariff_rate': 0.15,
                            }
                        )

                        if created:
                            stats['daily_records_created'] += 1
                        else:
                            # Update existing
                            daily_summary.total_energy_kwh = kwh_value
                            daily_summary.avg_power_kw = kwh_value / 24.0
                            daily_summary.save()
                            stats['daily_records_updated'] += 1

        else:
            # Dry run - just count
            total_records = 0
            for device_info in devices_info:
                col_idx = device_info['col_idx']
                for data_row in data_rows:
                    if col_idx < len(data_row) and len(data_row) > 1:
                        date_str = data_row[1].strip() if len(data_row) > 1 else ''
                        kwh_str = data_row[col_idx].strip() if col_idx < len(data_row) else ''
                        if date_str and kwh_str and kwh_str != '-' and kwh_str != '':
                            try:
                                float(kwh_str)
                                total_records += 1
                            except:
                                pass
            
            self.stdout.write(self.style.WARNING(f'\nDRY RUN - Would import:'))
            self.stdout.write(f'  Devices: {len(devices_info)}')
            self.stdout.write(f'  Daily records: ~{total_records}')
            return

        # Print summary
        self.stdout.write(self.style.SUCCESS('\n=== Import Summary ==='))
        self.stdout.write(f'Devices created: {stats["devices_created"]}')
        self.stdout.write(f'Devices updated: {stats["devices_updated"]}')
        self.stdout.write(f'Daily records created: {stats["daily_records_created"]}')
        self.stdout.write(f'Daily records updated: {stats["daily_records_updated"]}')
        if stats['errors'] > 0:
            self.stdout.write(self.style.WARNING(f'Errors: {stats["errors"]}'))

    def get_or_create_device(self, device_info, stats):
        """Get or create ModbusDevice from device info"""
        name = device_info['name']
        major_dept = device_info['major_dept']
        floor_str = device_info['floor']
        sub_dept = device_info['sub_dept']
        
        # Check if this is a Main device (incoming feeder)
        is_main_feeder = sub_dept and 'main' in str(sub_dept).lower()

        # Map major department to process_area
        process_area = 'general'
        if 'washing' in major_dept.lower():
            process_area = 'washing'
        elif 'denim' in major_dept.lower():
            process_area = 'denim'
        elif 'finishing' in major_dept.lower():
            process_area = 'finishing'
        elif 'sewing' in major_dept.lower():
            process_area = 'sewing'

        # Map floor
        floor = 'none'
        if 'ground' in floor_str.lower() or 'gf' in floor_str.lower():
            floor = 'GF'
        elif 'first' in floor_str.lower() or 'ff' in floor_str.lower():
            floor = 'FF'
        elif 'second' in floor_str.lower() or '2f' in floor_str.lower() or 'sf' in floor_str.lower():
            floor = 'SF'

        # Determine load_type from floor_str and sub_dept
        load_type = 'none'
        if is_main_feeder:
            # Main devices are incoming feeders
            load_type = 'MAIN'
        elif 'LT 01' in floor_str or 'LT01' in floor_str:
            load_type = 'LT01'
        elif 'LT 02' in floor_str or 'LT02' in floor_str:
            load_type = 'LT02'
        elif 'main' in floor_str.lower():
            load_type = 'MAIN'

        # Determine device_type
        device_type = 'electricity'
        if 'flow' in name.lower() or 'steam' in name.lower():
            device_type = 'flowmeter'

        try:
            device, created = ModbusDevice.objects.get_or_create(
                name=name,
                defaults={
                    'process_area': process_area,
                    'floor': floor,
                    'load_type': load_type,
                    'device_type': device_type,
                    'application_type': 'process',
                    'is_active': True,
                }
            )

            if created:
                stats['devices_created'] += 1
            else:
                # Update existing device
                updated = False
                if not device.process_area or device.process_area == 'general':
                    device.process_area = process_area
                    updated = True
                if not device.floor or device.floor == 'none':
                    device.floor = floor
                    updated = True
                if not device.load_type or device.load_type == 'none':
                    device.load_type = load_type
                    updated = True
                
                if updated:
                    device.save()
                    stats['devices_updated'] += 1

            return device
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Error creating device {name}: {e}'))
            stats['errors'] += 1
            return None
