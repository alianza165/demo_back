# Generated migration for safe field migration
# This migration safely adds new fields and migrates data from old fields

from django.db import migrations, models

def migrate_existing_devices(apps, schema_editor):
    """
    Safely migrate existing ModbusDevice records to use new fields.
    This function preserves existing data and sets sensible defaults.
    """
    ModbusDevice = apps.get_model('modbus', 'ModbusDevice')
    
    # Set defaults for any devices that might not have the new fields set
    # (This should not be needed if migration 0014 ran correctly, but safety first)
    for device in ModbusDevice.objects.all():
        if not device.process_area or device.process_area == '':
            device.process_area = 'general'
        if not device.floor or device.floor == '':
            device.floor = 'none'
        if not device.load_type or device.load_type == '':
            device.load_type = 'none'
        device.save(update_fields=['process_area', 'floor', 'load_type'])

def reverse_migration(apps, schema_editor):
    """
    Reverse migration - set fields back to defaults if needed.
    Note: We cannot restore old 'department'/'machine_type' fields as they were removed.
    """
    ModbusDevice = apps.get_model('modbus', 'ModbusDevice')
    # Just reset to defaults - old fields cannot be restored
    ModbusDevice.objects.all().update(
        process_area='general',
        floor='none',
        load_type='none'
    )

class Migration(migrations.Migration):

    dependencies = [
        ('modbus', '0014_remove_modbusdevice_department_and_more'),
    ]

    operations = [
        migrations.RunPython(
            migrate_existing_devices,
            reverse_migration,
        ),
    ]
