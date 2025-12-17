# Generated migration for data migration before schema change
from django.db import migrations

def migrate_device_fields_forward(apps, schema_editor):
    """
    Migrate old fields (department, process, machine_type) to new fields 
    (process_area, floor, load_type) before schema change.
    
    This runs BEFORE the schema migration that removes the old fields.
    """
    ModbusDevice = apps.get_model('modbus', 'ModbusDevice')
    
    migrated_count = 0
    skipped_count = 0
    
    for device in ModbusDevice.objects.all():
        updated = False
        
        # Map department/process to process_area
        if hasattr(device, 'department') and device.department:
            dept_value = str(device.department).lower().strip()
            dept_map = {
                'denim': 'denim',
                'washing': 'washing',
                'finishing': 'finishing',
                'sewing': 'sewing',
            }
            if dept_value in dept_map:
                device.process_area = dept_map[dept_value]
                updated = True
        
        # Also check process field if it exists
        if hasattr(device, 'process') and device.process:
            process_value = str(device.process).lower().strip()
            if process_value in ['denim', 'washing', 'finishing', 'sewing']:
                device.process_area = process_value
                updated = True
        
        # Set defaults for new fields if they don't exist or are empty
        if not hasattr(device, 'process_area') or not device.process_area or device.process_area == '':
            device.process_area = 'general'
            updated = True
        
        if not hasattr(device, 'floor') or not device.floor or device.floor == '':
            device.floor = 'none'
            updated = True
        
        if not hasattr(device, 'load_type') or not device.load_type or device.load_type == '':
            device.load_type = 'none'
            updated = True
        
        if updated:
            device.save(update_fields=['process_area', 'floor', 'load_type'])
            migrated_count += 1
        else:
            skipped_count += 1
    
    print(f"Data migration complete: {migrated_count} devices updated, {skipped_count} skipped")

def migrate_device_fields_reverse(apps, schema_editor):
    """
    Reverse migration - cannot fully restore old fields as they may not exist
    This is a placeholder for rollback capability.
    """
    # Note: Cannot reverse as old fields will be removed
    # This is a one-way migration
    pass

class Migration(migrations.Migration):
    """
    Data migration to populate new fields before schema migration.
    
    This MUST run before 0014_2_remove_modbusdevice_department_and_more.py
    """
    
    dependencies = [
        ('modbus', '0013_add_department_process_machine_type'),
    ]

    operations = [
        migrations.RunPython(
            migrate_device_fields_forward,
            migrate_device_fields_reverse,
        ),
    ]
