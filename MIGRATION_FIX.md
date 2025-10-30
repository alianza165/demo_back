# Migration Fix for Production

## Issue
When running migration `0008_modbusregister_unique_address_per_device_and_more.py` in production, got error:
```
TypeError: __init__() got an unexpected keyword argument 'condition'
```

## Root Cause
Django's migration auto-generator used `condition=` parameter for `CheckConstraint`, but the correct parameter is `check=`.

## Fix Applied
Changed line 19 in the migration from:
```python
constraint=models.CheckConstraint(condition=models.Q(...), ...)
```

To:
```python
constraint=models.CheckConstraint(check=models.Q(...), ...)
```

## Verification
✅ Migration tested and works correctly in local environment

## Production Deployment
The fixed migration file is ready. Simply deploy and run:
```bash
python manage.py migrate modbus
```

The migration will:
1. Add unique constraint on `(device, address)` when device is set
2. Add check constraint ensuring register belongs to exactly one parent

---

**File Location**: `modbus/migrations/0008_modbusregister_unique_address_per_device_and_more.py`
**Status**: ✅ Fixed and verified

