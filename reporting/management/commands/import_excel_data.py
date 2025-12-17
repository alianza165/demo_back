"""
Management command to import data from Excel files into the reporting database.
Handles both Master DND- Dashboard.xlsx and DND Nov Master Format Final.xlsx files.

This script imports:
- Devices (ModbusDevice) with process_area, floor, load_type
- Daily aggregates with meter readings and overtime data
- Monthly aggregates
- Engineering dashboard data
- Capacity load data
- Production data
- Target and benchmark data
"""
import os
import sys
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
import pandas as pd
import numpy as np
from pathlib import Path

from modbus.models import ModbusDevice
from reporting.models import (
    DailyAggregate, MonthlyAggregate, ProductionData,
    EngineeringDashboard, CapacityLoad, Target, EfficiencyBenchmark
)


class Command(BaseCommand):
    help = 'Import data from Excel files (Master DND- Dashboard.xlsx and DND Nov Master Format Final.xlsx)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--master-file',
            type=str,
            default='Master DND- Dashboard.xlsx',
            help='Path to Master DND- Dashboard.xlsx file'
        )
        parser.add_argument(
            '--nov-file',
            type=str,
            default='DND Nov Master Format Final.xlsx',
            help='Path to DND Nov Master Format Final.xlsx file'
        )
        parser.add_argument(
            '--base-dir',
            type=str,
            default=None,
            help='Base directory for Excel files (default: project root)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Perform a dry run without saving data'
        )
        parser.add_argument(
            '--skip-devices',
            action='store_true',
            help='Skip device creation/updates'
        )
        parser.add_argument(
            '--skip-aggregates',
            action='store_true',
            help='Skip daily/monthly aggregates'
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.skip_devices = options['skip_devices']
        self.skip_aggregates = options['skip_aggregates']
        
        # Determine base directory
        if options['base_dir']:
            base_dir = Path(options['base_dir'])
        else:
            # Default to project root (one level up from demo_back)
            base_dir = Path(__file__).parent.parent.parent.parent
        
        master_file = base_dir / options['master_file']
        nov_file = base_dir / options['nov_file']
        
        self.stdout.write(f'Base directory: {base_dir}')
        self.stdout.write(f'Master file: {master_file}')
        self.stdout.write(f'Nov file: {nov_file}')
        
        if not master_file.exists():
            self.stdout.write(self.style.ERROR(f'Master file not found: {master_file}'))
            return
        
        if not nov_file.exists():
            self.stdout.write(self.style.ERROR(f'Nov file not found: {nov_file}'))
            return
        
        stats = {
            'devices_created': 0,
            'devices_updated': 0,
            'daily_aggregates': 0,
            'monthly_aggregates': 0,
            'engineering_dashboards': 0,
            'capacity_loads': 0,
            'production_data': 0,
            'targets': 0,
            'benchmarks': 0,
        }
        
        try:
            # Import from Nov file first (device-level data)
            self.stdout.write(self.style.SUCCESS('\n=== Importing from DND Nov Master Format Final.xlsx ==='))
            self._import_nov_file(nov_file, stats)
            
            # Import from Master file (aggregates and dashboards)
            self.stdout.write(self.style.SUCCESS('\n=== Importing from Master DND- Dashboard.xlsx ==='))
            self._import_master_file(master_file, stats)
            
            # Print summary
            self.stdout.write(self.style.SUCCESS('\n=== Import Summary ==='))
            for key, value in stats.items():
                self.stdout.write(f'{key}: {value}')
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error during import: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())
            raise

    def _import_nov_file(self, file_path, stats):
        """Import data from DND Nov Master Format Final.xlsx"""
        excel_file = pd.ExcelFile(file_path)
        
        # Import device-level data from LT sheets
        for sheet_name in ['LT GF', 'LT FF', 'LT 2F', 'LT-Wshng']:
            if sheet_name in excel_file.sheet_names:
                self.stdout.write(f'Processing {sheet_name}...')
                self._import_lt_sheet(excel_file, sheet_name, stats)
        
        # Import capacity load data
        if 'Capacity load' in excel_file.sheet_names:
            self.stdout.write('Processing Capacity load...')
            self._import_capacity_load(excel_file, 'Capacity load', stats)
        
        # Import overtime data
        if 'Overtime' in excel_file.sheet_names:
            self.stdout.write('Processing Overtime...')
            self._import_overtime_sheet(excel_file, 'Overtime', stats)

    def _import_master_file(self, file_path, stats):
        """Import data from Master DND- Dashboard.xlsx"""
        excel_file = pd.ExcelFile(file_path)
        
        # Import daily dashboard
        if 'Daily Dashboard' in excel_file.sheet_names:
            self.stdout.write('Processing Daily Dashboard...')
            self._import_daily_dashboard(excel_file, 'Daily Dashboard', stats)
        
        # Import monthly dashboard
        if 'Monthly Dashboard' in excel_file.sheet_names:
            self.stdout.write('Processing Monthly Dashboard...')
            self._import_monthly_dashboard(excel_file, 'Monthly Dashboard', stats)
        
        # Import engineering dashboard
        if 'Dashboard' in excel_file.sheet_names:
            self.stdout.write('Processing Dashboard (Engineering)...')
            self._import_engineering_dashboard(excel_file, 'Dashboard', stats)
        
        # Import target setting
        if 'Target setting' in excel_file.sheet_names:
            self.stdout.write('Processing Target setting...')
            self._import_target_setting(excel_file, 'Target setting', stats)
        
        # Import monthly average
        if 'Monthly Avg.' in excel_file.sheet_names:
            self.stdout.write('Processing Monthly Avg....')
            self._import_monthly_avg(excel_file, 'Monthly Avg.', stats)

    def _import_lt_sheet(self, excel_file, sheet_name, stats):
        """Import device-level data from LT sheets (LT GF, LT FF, LT 2F, LT-Wshng)"""
        # Read without header first to inspect structure
        df_raw = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
        
        # Determine process area and floor from sheet name
        process_area = 'washing' if 'Wshng' in sheet_name else 'denim'
        floor_map = {
            'LT GF': 'GF',
            'LT FF': 'FF',
            'LT 2F': 'SF',
            'LT-Wshng': 'GF',  # Washing has both GF and FF, will be handled separately
        }
        floor = floor_map.get(sheet_name, 'none')
        
        self.stdout.write(f'  Found {len(df_raw)} rows in {sheet_name}')
        
        # Excel structure:
        # Row 0: Main header "DENIM Ground Floor LT's ENERGY ANALYZER READINGS"
        # Row 1: Header row with "DAY", "DATE", "MAIN", "LT 01 GF", etc.
        # Row 2: Numbers (0, 1, 2, 3, 4) - column group indices
        # Row 3: Device names (MPB-1-GF, DB-EW-GF-M2, etc.)
        # Row 4: "Meter Reading" and "Daily Units (kWh)" labels
        # Row 5+: Actual data
        
        # Find date column (usually column 1 or 2, row 1 has "DATE")
        date_col_idx = None
        if len(df_raw) > 1:
            for idx, val in enumerate(df_raw.iloc[1]):
                if pd.notna(val) and ('date' in str(val).lower()):
                    date_col_idx = idx
                    break
        
        if date_col_idx is None:
            date_col_idx = 1  # Default to column 1
        
        # Verify date column by checking if row 5 has a valid date
        # Sometimes the date is in the next column (e.g., col 2 for washing sheet where col 1 has day name)
        if len(df_raw) > 5:
            # First, try to find a column with actual datetime/Timestamp in row 5
            for idx in range(min(5, len(df_raw.columns))):
                test_val = df_raw.iloc[5, idx]
                if isinstance(test_val, pd.Timestamp):
                    date_col_idx = idx
                    break
                try:
                    if pd.notna(test_val) and not isinstance(test_val, str):
                        pd.to_datetime(test_val)
                        date_col_idx = idx
                        break
                except:
                    continue
            
            # If still not found, check the detected column
            if date_col_idx is not None and date_col_idx < len(df_raw.columns):
                test_date = df_raw.iloc[5, date_col_idx]
                # Check if it's a day name (TUE, WED, etc.) instead of a date
                if pd.notna(test_date) and isinstance(test_date, str) and len(test_date) <= 4:
                    # Likely a day name, check next column
                    if date_col_idx + 1 < len(df_raw.columns):
                        next_test = df_raw.iloc[5, date_col_idx + 1]
                        if isinstance(next_test, pd.Timestamp) or (pd.notna(next_test) and not isinstance(next_test, str)):
                            date_col_idx = date_col_idx + 1
        
        # Find device names from row 3 (index 3)
        device_map = {}  # {col_idx: (device_name, load_type)}
        row3 = df_raw.iloc[3] if len(df_raw) > 3 else None
        row1 = df_raw.iloc[1] if len(df_raw) > 1 else None
        
        if row3 is None:
            self.stdout.write(self.style.WARNING(f'  Cannot find device names row (row 3) in {sheet_name}'))
            return
        
        # Scan row 3 for device names
        for col_idx in range(len(row3)):
            device_name = row3.iloc[col_idx] if hasattr(row3, 'iloc') else row3[col_idx]
            if pd.notna(device_name):
                device_str = str(device_name).strip()
                # Check if it's a device name (contains MPB-, DB-, MCC-, BTD, LASER)
                if any(prefix in device_str.upper() for prefix in ['MPB-', 'DB-', 'MCC-', 'BTD', 'LASER']):
                    # Determine load type from row 1 header
                    load_type = 'none'
                    if row1 is not None and col_idx < len(row1):
                        header_val = row1.iloc[col_idx] if hasattr(row1, 'iloc') else row1[col_idx]
                        if pd.notna(header_val):
                            header_str = str(header_val).upper()
                            if 'LT01' in header_str or 'LT-01' in header_str or 'LT 01' in header_str:
                                load_type = 'LT01'
                            elif 'LT02' in header_str or 'LT-02' in header_str or 'LT 02' in header_str:
                                load_type = 'LT02'
                            elif 'MAIN' in header_str:
                                load_type = 'MAIN'
                    
                    device_map[col_idx] = (device_str, load_type)
        
        if not device_map:
            self.stdout.write(self.style.WARNING(f'  No device names found in row 2 of {sheet_name}'))
            return
        
        self.stdout.write(f'  Found {len(device_map)} devices in {sheet_name}')
        
        # Process data rows (starting from row 5, index 5)
        data_start_row = 5
        if len(df_raw) <= data_start_row:
            self.stdout.write(self.style.WARNING(f'  No data rows found in {sheet_name}'))
            return
        
        # Process each device
        for col_idx, (device_name, load_type) in device_map.items():
            # In Excel structure: device name is in col_idx, meter reading is in col_idx, daily units is in col_idx+1
            # Row 3 has labels: "Meter Reading" and "Daily Units (kWh)"
            meter_col_idx = col_idx
            daily_units_col_idx = col_idx + 1
            
            # For washing sheet, determine floor from device name
            device_floor = floor
            if 'Wshng' in sheet_name:
                device_name_upper = device_name.upper()
                if 'GF' in device_name_upper or 'GROUND' in device_name_upper:
                    device_floor = 'GF'
                elif 'FF' in device_name_upper or 'FIRST' in device_name_upper:
                    device_floor = 'FF'
            
            # Create or update device
            if not self.skip_devices:
                device, created = self._get_or_create_device(
                    device_name, process_area, device_floor, stats, load_type=load_type
                )
                if device is None:  # dry_run
                    continue
            
            # Process data rows
            rows_processed = 0
            for row_idx in range(data_start_row, len(df_raw)):
                try:
                    # Get date from date column
                    date_val = df_raw.iloc[row_idx, date_col_idx]
                    if pd.isna(date_val):
                        continue
                    
                    # Parse date
                    try:
                        if isinstance(date_val, pd.Timestamp):
                            date_obj = date_val.date()
                        else:
                            date_obj = pd.to_datetime(date_val).date()
                    except Exception as e:
                        if rows_processed < 3:
                            self.stdout.write(f'    Date parse error row {row_idx}: {e}')
                        continue
                    
                    # Get meter reading and daily units
                    meter_reading = self._safe_float(df_raw.iloc[row_idx, meter_col_idx])
                    daily_units = self._safe_float(df_raw.iloc[row_idx, daily_units_col_idx])
                    
                    if daily_units is None or daily_units == 0:
                        if rows_processed < 3:
                            self.stdout.write(f'    Skipping row {row_idx}: daily_units is {daily_units}')
                        continue
                    
                    rows_processed += 1
                    
                    # Create daily aggregate
                    if not self.skip_aggregates:
                        # Debug: log first few imports
                        if stats['daily_aggregates'] < 5:
                            self.stdout.write(f'    Creating aggregate for {device_name} on {date_obj}: {daily_units} kWh')
                        # Get or create device
                        device_result = self._get_or_create_device(device_name, process_area, device_floor, stats, load_type=load_type)
                        device = device_result[0]
                        
                        if device is None:
                            # Device not found and we can't create it
                            continue
                            
                        daily_agg, created = DailyAggregate.objects.get_or_create(
                            device=device,
                            date=date_obj,
                            is_overtime=False,
                            defaults={
                                'total_energy_kwh': daily_units,
                                'meter_reading': meter_reading,
                                'daily_units_kwh': daily_units,
                                'avg_power_kw': daily_units / 24 if daily_units else 0,
                            }
                        )
                        if created:
                            stats['daily_aggregates'] += 1
                        else:
                            # Update existing
                            daily_agg.meter_reading = meter_reading
                            daily_agg.daily_units_kwh = daily_units
                            daily_agg.total_energy_kwh = daily_units
                            if not self.dry_run:
                                daily_agg.save()
                            
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  Error processing row {row_idx} for device {device_name}: {e}'))
                    continue

    def _import_overtime_sheet(self, excel_file, sheet_name, stats):
        """Import overtime data from Overtime sheet"""
        # Similar structure to LT sheets but marked as overtime
        df_raw = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
        
        # Find date column (similar to LT sheets)
        date_col_idx = None
        for idx, val in enumerate(df_raw.iloc[0] if len(df_raw) > 0 else []):
            if pd.notna(val) and ('date' in str(val).lower() or 'day' in str(val).lower()):
                date_col_idx = idx
                break
        
        if date_col_idx is None:
            date_col_idx = 1  # Default to column 1
        
        # Find device names from row 3 (similar to LT sheets)
        device_map = {}
        row3 = df_raw.iloc[3] if len(df_raw) > 3 else None
        
        if row3 is not None:
            for col_idx in range(len(row3)):
                device_name = row3.iloc[col_idx] if hasattr(row3, 'iloc') else row3[col_idx]
                if pd.notna(device_name):
                    device_str = str(device_name).strip()
                    if any(prefix in device_str.upper() for prefix in ['MPB-', 'DB-', 'MCC-', 'BTD', 'LASER']):
                        device_map[col_idx] = device_str
        
        if not device_map:
            self.stdout.write(self.style.WARNING(f'  No device names found in row 3 of {sheet_name}'))
            return
        
        data_start_row = 5
        
        # Process each device
        for col_idx, device_name in device_map.items():
            meter_col_idx = col_idx
            daily_units_col_idx = col_idx + 1
            
            # Determine process area and floor from device name
            process_area = 'washing' if 'WASHING' in device_name.upper() else 'denim'
            floor = 'GF' if 'GF' in device_name.upper() else ('FF' if 'FF' in device_name.upper() else 'SF' if 'SF' in device_name.upper() else 'none')
            
            # Process data rows
            for row_idx in range(data_start_row, len(df_raw)):
                try:
                    date_val = df_raw.iloc[row_idx, date_col_idx]
                    if pd.isna(date_val):
                        continue
                    
                    try:
                        if isinstance(date_val, pd.Timestamp):
                            date_obj = date_val.date()
                        else:
                            date_obj = pd.to_datetime(date_val).date()
                    except:
                        continue
                    
                    daily_units = self._safe_float(df_raw.iloc[row_idx, daily_units_col_idx])
                    
                    if daily_units is None or daily_units == 0:
                        continue
                    
                    if not self.skip_aggregates:
                        # Get or create device
                        device_result = self._get_or_create_device(device_name, process_area, floor, stats)
                        device = device_result[0]
                        
                        if device is None:
                            # Device not found and we can't create it
                            continue
                            
                        daily_agg, created = DailyAggregate.objects.get_or_create(
                            device=device,
                            date=date_obj,
                            is_overtime=True,
                            defaults={
                                'total_energy_kwh': daily_units,
                                'daily_units_kwh': daily_units,
                                'avg_power_kw': daily_units / 24 if daily_units else 0,
                            }
                        )
                        if created:
                            stats['daily_aggregates'] += 1
                            
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  Error processing overtime row {row_idx}: {e}'))
                    continue

    def _import_capacity_load(self, excel_file, sheet_name, stats):
        """Import capacity load data from Capacity load sheet"""
        df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
        
        # Parse capacity load data
        # Structure from inspection:
        # Row 1: "Production Lines BBT Lights DND..." and "Exhaust Fans DND..."
        # Row 2: Headers for Exhaust Fans: "Exhaust Fans", "kW", "QTY", "Load", "Daily", "monthly"
        # Row 3+: Exhaust fan data: GF, 1.8, 12, 21.6, 172.8, 4492.8
        
        # Find exhaust fans section (starts around column 12)
        exhaust_fan_start_col = None
        for col_idx in range(len(df.columns)):
            val = df.iloc[1, col_idx] if len(df) > 1 else None
            if pd.notna(val) and 'EXHAUST FAN' in str(val).upper():
                exhaust_fan_start_col = col_idx
                break
        
        if exhaust_fan_start_col is None:
            self.stdout.write(self.style.WARNING(f'  Could not find Exhaust Fans section in {sheet_name}'))
            return
        
        # Process exhaust fans (starting from row 3, which has GF data)
        # Row 2 has headers: "Exhaust Fans", "kW", "QTY", "Load", "Daily", "monthly"
        # Row 3+: Data rows with location, kW, QTY, Load, Daily, monthly
        for row_idx in range(3, min(len(df), 10)):  # Process first few rows
            try:
                if row_idx >= len(df):
                    break
                row = df.iloc[row_idx]
                if exhaust_fan_start_col >= len(row):
                    continue
                location_name = row.iloc[exhaust_fan_start_col] if hasattr(row, 'iloc') else row[exhaust_fan_start_col]
                
                if pd.isna(location_name):
                    continue
                
                location_name_str = str(location_name).strip().upper()
                if location_name_str in ['NAN', 'NONE', 'TTL', '']:
                    continue
                
                # Extract values (columns: location, kW, QTY, Load, Daily, monthly)
                power_kw = self._safe_float(row.iloc[exhaust_fan_start_col + 1])
                qty = self._safe_int(row.iloc[exhaust_fan_start_col + 2])
                total_load = self._safe_float(row.iloc[exhaust_fan_start_col + 3])
                daily_kwh = self._safe_float(row.iloc[exhaust_fan_start_col + 4])
                monthly_kwh = self._safe_float(row.iloc[exhaust_fan_start_col + 5])
                
                if not power_kw or not qty:
                    continue
                
                # Determine location and process area
                location = 'GF'
                process_area = 'general'
                if 'GF' in location_name_str or 'GROUND' in location_name_str:
                    location = 'GF'
                elif 'FF' in location_name_str or 'FIRST' in location_name_str:
                    location = 'FF'
                elif 'SF' in location_name_str or 'SECOND' in location_name_str:
                    location = 'SF'
                elif 'WASHING' in location_name_str:
                    location = 'GF'
                    process_area = 'washing'
                
                name = f"Exhaust Fans {location_name_str}"
                
                if not self.dry_run:
                    capacity_load, created = CapacityLoad.objects.get_or_create(
                        name=name,
                        equipment_type='exhaust_fan',
                        defaults={
                            'process_area': process_area,
                            'location': location,
                            'quantity': qty,
                            'power_per_unit_kw': power_kw,
                            'total_load_kw': total_load or (power_kw * qty),
                            'daily_kwh': daily_kwh,
                            'monthly_kwh': monthly_kwh,
                            'shift_hours': 8.0,
                        }
                    )
                    if created:
                        stats['capacity_loads'] += 1
                        
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Error processing capacity load row {row_idx}: {e}'))
                continue
        
        # Process production lines (columns 0-10, rows 3+)
        # Row 2 has process names: Finishing, Packing, Sewing 1F, Sewing 2F, Cutting Highbay, GF Highbay
        # Row 3+ has line names and quantities
        for row_idx in range(3, min(len(df), 15)):
            try:
                row = df.iloc[row_idx]
                
                # Check each process column (0, 2, 4, 6, 8)
                for col_offset in [0, 2, 4, 6, 8]:
                    if col_offset >= len(row):
                        break
                    
                    line_name = row.iloc[col_offset]
                    qty = self._safe_int(row.iloc[col_offset + 1] if col_offset + 1 < len(row) else None)
                    
                    if pd.notna(line_name) and qty and qty > 0:
                        line_name_str = str(line_name).strip()
                        if line_name_str.upper() in ['NAN', 'NONE', ''] or 'line' not in line_name_str.lower():
                            continue
                        
                        # Determine process area and location from column position
                        process_area = 'general'
                        location = 'GF'
                        
                        if col_offset == 0:
                            process_area = 'finishing'
                            location = 'GF'
                        elif col_offset == 2:
                            process_area = 'packing'
                            location = 'FF'
                        elif col_offset == 4:
                            process_area = 'sewing'
                            location = 'SF'
                        elif col_offset == 6:
                            process_area = 'sewing'
                            location = 'SF'
                        elif col_offset == 8:
                            process_area = 'cutting'
                            location = 'GF'
                        
                        # Estimate power (typical line power)
                        power_kw = 2.0  # Default estimate
                        total_load = power_kw * qty
                        
                        if not self.dry_run:
                            capacity_load, created = CapacityLoad.objects.get_or_create(
                                name=line_name_str,
                                equipment_type='production_line',
                                defaults={
                                    'process_area': process_area,
                                    'location': location,
                                    'quantity': qty,
                                    'power_per_unit_kw': power_kw,
                                    'total_load_kw': total_load,
                                    'shift_hours': 8.0,
                                }
                            )
                            if created:
                                stats['capacity_loads'] += 1
                                
            except Exception as e:
                continue

    def _import_daily_dashboard(self, excel_file, sheet_name, stats):
        """Import daily dashboard aggregates from Summary sheet"""
        # The Summary sheet has process-wise aggregates
        df = pd.read_excel(excel_file, sheet_name='Summary ', header=None)
        
        # Find date column (usually column 1, row 3+)
        # Structure: Row 2 has headers, Row 3 has sub-headers, Row 4+ has data
        date_col_idx = 1  # Column 1 typically has dates
        
        # Process rows starting from row 4 (index 4)
        for row_idx in range(4, len(df)):
            try:
                date_val = df.iloc[row_idx, date_col_idx]
                if pd.isna(date_val):
                    continue
                
                # Parse date
                try:
                    if isinstance(date_val, pd.Timestamp):
                        date_obj = date_val.date()
                    else:
                        date_obj = pd.to_datetime(date_val).date()
                except:
                    continue
                
                # Get component values from the row
                # Structure: Description, GF LT1, GF LT2, GF Total, FF LT1, FF LT2, FF Total, etc.
                description = df.iloc[row_idx, 2] if len(df.columns) > 2 else None
                if pd.isna(description):
                    continue
                
                component_name = str(description).strip().lower()
                
                # Map component names
                component_map = {
                    'lights': 'lights',
                    'exhaust fan': 'exhaust_fan',
                    'hvac': 'hvac',
                    'machines': 'machines',
                    'office': 'office',
                    'laser': 'laser',
                }
                
                component = None
                for key, value in component_map.items():
                    if key in component_name:
                        component = value
                        break
                
                if not component:
                    continue
                
                # Extract values for different floors and load types
                # GF LT1 (col 3), GF LT2 (col 4), GF Total (col 5)
                # FF LT1 (col 7), FF LT2 (col 8), FF Total (col 9)
                # SF LT1 (col 10), SF LT2 (col 11), SF Total (col 12)
                # Sewing (col 13)
                # Washing GF (col 17), Washing FF (col 18)
                
                # For now, we'll aggregate these into device-level daily aggregates
                # This is complex, so we'll focus on creating process-level aggregates
                # The daily aggregates from LT sheets are more accurate
                
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Error processing daily dashboard row {row_idx}: {e}'))
                continue

    def _import_monthly_dashboard(self, excel_file, sheet_name, stats):
        """Import monthly dashboard aggregates from Summary sheet"""
        # Use Summary sheet which has monthly process-wise data
        df = pd.read_excel(excel_file, sheet_name='Summary ', header=None)
        
        # Find date column (column 1)
        date_col_idx = 1
        
        # Process rows starting from row 4
        current_month = None
        monthly_data = {}  # {month: {process: {component: value}}}
        
        for row_idx in range(4, len(df)):
            try:
                date_val = df.iloc[row_idx, date_col_idx]
                if pd.isna(date_val):
                    continue
                
                # Parse date to get month
                try:
                    if isinstance(date_val, pd.Timestamp):
                        date_obj = date_val.date()
                    else:
                        date_obj = pd.to_datetime(date_val).date()
                    
                    month_key = date_obj.replace(day=1)
                    if month_key != current_month:
                        current_month = month_key
                        if month_key not in monthly_data:
                            monthly_data[month_key] = {}
                    
                except:
                    continue
                
                # Get component description
                description = df.iloc[row_idx, 2] if len(df.columns) > 2 else None
                if pd.isna(description):
                    continue
                
                component_name = str(description).strip().lower()
                
                # Map component
                component_map = {
                    'lights': 'lights',
                    'exhaust fan': 'exhaust_fan',
                    'hvac': 'hvac',
                    'machines': 'machines',
                    'office': 'office',
                    'laser': 'laser',
                }
                
                component = None
                for key, value in component_map.items():
                    if key in component_name:
                        component = value
                        break
                
                if not component:
                    continue
                
                # Extract process totals from columns
                # Denim GF Total (col 5), Denim FF Total (col 9), Denim SF Total (col 12)
                # Sewing (col 13)
                # Washing Total (col 20)
                
                denim_gf_total = self._safe_float(df.iloc[row_idx, 5]) or 0
                denim_ff_total = self._safe_float(df.iloc[row_idx, 9]) or 0
                denim_sf_total = self._safe_float(df.iloc[row_idx, 12]) or 0
                sewing_total = self._safe_float(df.iloc[row_idx, 13]) or 0
                washing_total = self._safe_float(df.iloc[row_idx, 20]) or 0
                
                # Aggregate by process
                processes = {
                    'denim': denim_gf_total + denim_ff_total + denim_sf_total,
                    'sewing': sewing_total,
                    'washing': washing_total,
                }
                
                for process, total in processes.items():
                    if total > 0:
                        if process not in monthly_data[month_key]:
                            monthly_data[month_key][process] = {}
                        monthly_data[month_key][process][component] = (
                            monthly_data[month_key][process].get(component, 0) + total
                        )
                
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Error processing monthly dashboard row {row_idx}: {e}'))
                continue
        
        # Create monthly aggregates for each process
        # Note: These are process-level aggregates, not device-level
        # We'll create them as device=None (overall) aggregates
        for month_key, process_data in monthly_data.items():
            for process, components in process_data.items():
                total_energy = sum(components.values())
                if total_energy > 0:
                    # Create or update monthly aggregate for this process
                    # Since we don't have a specific device, we'll aggregate by process_area
                    # Find devices for this process area
                    devices = ModbusDevice.objects.filter(
                        process_area=process,
                        is_active=True
                    )
                    
                    if devices.exists():
                        # Create monthly aggregate for each device or aggregate all
                        # For now, we'll update existing monthly aggregates with component breakdown
                        monthly_aggs = MonthlyAggregate.objects.filter(
                            month=month_key,
                            device__process_area=process
                        )
                        
                        for monthly_agg in monthly_aggs:
                            # Update component breakdown if it's empty or merge with existing
                            if not monthly_agg.component_breakdown:
                                monthly_agg.component_breakdown = components
                            else:
                                # Merge component breakdowns
                                for comp, value in components.items():
                                    monthly_agg.component_breakdown[comp] = (
                                        monthly_agg.component_breakdown.get(comp, 0) + value
                                    )
                            monthly_agg.save()
                            stats['monthly_aggregates'] += 1

    def _import_engineering_dashboard(self, excel_file, sheet_name, stats):
        """Import engineering dashboard data from Dashboard sheet"""
        df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
        
        # The Dashboard sheet has a complex structure with merged cells
        # Row 0: "ENGINEERING DEPARTMENT DASHBOARD"
        # Row 3: Section headers (Load shedding, Utilities Production Rate, Resource Group Status, Gen-Sets)
        # Row 5: Column headers
        # Row 6+: Data rows
        
        # For now, we'll use today's date since the sheet doesn't have explicit dates
        # In a real scenario, you'd need to parse dates from another source or use the date from Summary sheet
        from datetime import date as date_class
        today = date_class.today()
        
        # Look for data in row 6 (index 6)
        if len(df) > 6:
            row6 = df.iloc[6]
            
            defaults = {}
            
            # Utilities Production Rate (columns around 8-10)
            # KW (Avg) might be in column 9, KW (Peak) in column 10
            if len(row6) > 9:
                kw_avg = self._safe_float(row6.iloc[9])
                kw_peak = self._safe_float(row6.iloc[10]) if len(row6) > 10 else None
                
                if kw_avg:
                    defaults['kw_avg'] = kw_avg
                if kw_peak:
                    defaults['kw_peak'] = kw_peak
            
            # Resource Group Status (columns around 11-15)
            # Avg.Flow, Husk Kgs, Steam Tons, Wastage Kg, Gas Availability
            if len(row6) > 15:
                avg_flow = self._safe_float(row6.iloc[13])
                husk_kgs = self._safe_float(row6.iloc[14])
                steam_tons = self._safe_float(row6.iloc[15])
                wastage_kg = self._safe_float(row6.iloc[16])
                gas_avail = row6.iloc[17] if len(row6) > 17 else None
                
                if avg_flow:
                    defaults['avg_flow_tons_per_hr'] = avg_flow
                if husk_kgs:
                    defaults['husk_kgs'] = husk_kgs
                if steam_tons:
                    defaults['steam_tons'] = steam_tons
                if wastage_kg:
                    defaults['wastage_kg'] = wastage_kg
                if pd.notna(gas_avail):
                    gas_str = str(gas_avail).upper()
                    defaults['gas_availability'] = 'YES' in gas_str or 'AVAILABLE' in gas_str
            
            # Gen-Sets (columns around 18-22)
            # From, To, Hrs, DG Engine, Downtime
            if len(row6) > 22:
                gen_from = row6.iloc[19]
                gen_to = row6.iloc[20]
                gen_hours = self._safe_float(row6.iloc[21])
                dg_engine = row6.iloc[18] if len(row6) > 18 else None
                downtime = self._safe_float(row6.iloc[22]) if len(row6) > 22 else None
                
                if pd.notna(gen_from):
                    try:
                        # Parse time string like "00:00:00" or "06:00:00"
                        from_str = str(gen_from).strip()
                        if ':' in from_str:
                            time_parts = from_str.split(':')
                            if len(time_parts) >= 2:
                                from_dt = pd.to_datetime(f"{today} {from_str}", errors='coerce')
                                if pd.notna(from_dt):
                                    defaults['gen_set_from'] = from_dt
                    except:
                        pass
                
                if pd.notna(gen_to):
                    try:
                        to_str = str(gen_to).strip()
                        if ':' in to_str:
                            to_dt = pd.to_datetime(f"{today} {to_str}", errors='coerce')
                            if pd.notna(to_dt):
                                defaults['gen_set_to'] = to_dt
                    except:
                        pass
                
                if gen_hours:
                    defaults['gen_set_hours'] = gen_hours
                if pd.notna(dg_engine):
                    defaults['dg_engine'] = str(dg_engine).strip()
                if downtime:
                    defaults['downtime'] = downtime
            
            # KWH Generated might be calculated or in a different location
            # For now, we'll calculate it from kw_avg if available
            if 'kw_avg' in defaults and defaults['kw_avg']:
                # Rough estimate: kw_avg * 24 hours
                defaults['kwh_generated'] = defaults['kw_avg'] * 24
            
            if defaults:
                eng_dash, created = EngineeringDashboard.objects.get_or_create(
                    date=today,
                    defaults=defaults
                )
                if created:
                    stats['engineering_dashboards'] += 1
                elif not self.dry_run:
                    # Update existing
                    for key, value in defaults.items():
                        setattr(eng_dash, key, value)
                    eng_dash.save()

    def _import_target_setting(self, excel_file, sheet_name, stats):
        """Import target and benchmark data from Target setting sheet"""
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        
        # Parse target setting data
        # Structure: Month, Benchmark, Actual, Variance, etc.
        date_col = None
        for col in df.columns:
            if 'month' in str(col).lower() or 'date' in str(col).lower():
                date_col = col
                break
        
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.dropna(subset=[date_col])
            
            # Process target data
            # This would need customization based on exact structure
            pass

    def _import_monthly_avg(self, excel_file, sheet_name, stats):
        """Import monthly average data"""
        # Parse monthly average consumption and efficiency metrics
        pass

    def _get_or_create_device(self, device_name, process_area, floor, stats, load_type=None):
        """Get or create a ModbusDevice with proper categorization"""
        if self.dry_run:
            return (None, True)
        
        # Normalize device name
        device_name = str(device_name).strip()
        
        # If skip_devices, just try to get existing device
        if self.skip_devices:
            try:
                device = ModbusDevice.objects.get(name=device_name)
                return (device, False)
            except ModbusDevice.DoesNotExist:
                # Device doesn't exist and we're skipping creation
                return (None, False)
        
        # Determine load_type from device name if not provided
        if load_type is None:
            load_type = 'none'
            if 'LT01' in device_name.upper() or 'LT-01' in device_name.upper() or 'LT 01' in device_name.upper():
                load_type = 'LT01'
            elif 'LT02' in device_name.upper() or 'LT-02' in device_name.upper() or 'LT 02' in device_name.upper():
                load_type = 'LT02'
            elif 'MAIN' in device_name.upper():
                load_type = 'MAIN'
        
        device, created = ModbusDevice.objects.get_or_create(
            name=device_name,
            defaults={
                'process_area': process_area,
                'floor': floor,
                'load_type': load_type,
                'application_type': 'process',
                'device_type': 'electricity',
                'is_active': True,
            }
        )
        
        if created:
            stats['devices_created'] += 1
        else:
            # Update existing device with new fields if they're not set
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
            
            if updated and not self.dry_run:
                device.save()
                stats['devices_updated'] += 1
        
        return (device, created)

    def _safe_float(self, value):
        """Safely convert value to float"""
        if pd.isna(value) or value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(',', '').strip()
            return float(value)
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value):
        """Safely convert value to int"""
        if pd.isna(value) or value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(',', '').strip()
            return int(float(value))
        except (ValueError, TypeError):
            return None

