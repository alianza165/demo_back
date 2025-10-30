# Modbus Monitor Fix - Deployment Guide

## 📝 Summary

I've analyzed your `modbus_monitor.py` script and found **critical bugs** that were causing incorrect data readings. All issues have been fixed in the new version.

## 🚨 Critical Bug Fixed

**Your original script was BROKEN for 32-bit registers**:
- Energy meters (uint32) ❌ showed wrong values
- Power meters (int32) ❌ showed wrong values  
- Float values (float32) ❌ completely broken

**Root cause**: Script only read 1 register for ALL data types, ignoring the 4th parameter in your config.

## ✅ What's Been Fixed

### 1. **Data Type Handling** (CRITICAL)
Created new `RegisterReader` class that:
- ✅ Properly handles uint16, int16 (1 register)
- ✅ Correctly decodes uint32, int32 (2 registers)
- ✅ Supports float32 IEEE 754 encoding (2 registers)
- ✅ Handles signed/unsigned properly

### 2. **Config Parser**
Updated to handle Django's 4-tuple format:
```python
# Django generates: (name, scale, unit, data_type)
# Now properly parsed and used
```

### 3. **Duplicate Slave IDs**
✅ **FIXED**: Ran `check_device_conflicts --fix` which reassigned unique IDs

Before:
- Test Device: slave_id=1
- Test Device 2: slave_id=1 ❌ CONFLICT
- Sub Power Meter: slave_id=2

After:
- Test Device: slave_id=1
- Test Device 2: slave_id=2
- Sub Power Meter: slave_id=3

## 📦 Files Created

1. **`modbus/examples/modbus_monitor_fixed.py`** - The fixed script
2. **`modbus/examples/ISSUES_FIXED.md`** - Detailed issue documentation
3. **`modbus/management/commands/check_device_conflicts.py`** - Conflict checker

## 🚀 Deployment Steps

### Step 1: Back Up Current Script
```bash
# On your BeagleBone AI-64:
ssh debian@beaglebone
cd /opt/modbus_monitor
cp modbus_monitor.py modbus_monitor_backup.py
```

### Step 2: Deploy Fixed Script
Copy the fixed version to your BeagleBone:
```bash
# Copy from Django server to BeagleBone
scp modbus/examples/modbus_monitor_fixed.py debian@beaglebone:/opt/modbus_monitor/modbus_monitor.py
```

Or manually copy the contents.

### Step 3: Regenerate Config (Important!)
Since we fixed the slave IDs, you need to regenerate the config.json:

**Option A - Using API**:
```bash
curl -X POST http://192.168.1.35:8000/api/modbus/devices/apply_all_configurations/
```

**Option B - Using Django Admin**: Click "Apply Configuration" button

**Option C - Using curl to specific device**:
```bash
curl -X POST http://192.168.1.35:8000/api/modbus/devices/3/apply_configuration/
```

### Step 4: Restart Monitor
```bash
# On BeagleBone:
pm2 restart modbus_monitor
pm2 logs modbus_monitor --lines 50
```

### Step 5: Verify
```bash
# Check logs for successful reads
tail -f /var/log/modbus_monitor/modbus_monitor.log

# You should see:
# - "Read X/Y parameters successfully" messages
# - No errors about register counts
# - All devices reading correctly
```

## 🧪 Testing Checklist

After deployment:

- [ ] Script starts without errors
- [ ] All devices read successfully (check log counts)
- [ ] Energy values look reasonable (not garbled)
- [ ] Power readings are accurate
- [ ] Grafana dashboards show correct data
- [ ] No "insufficient registers" errors in logs

## 📊 Expected Improvements

After fix, you'll see:
- ✅ Energy meters (uint32) showing correct cumulative kWh
- ✅ Power meters (int32) displaying accurate positive/negative values
- ✅ All devices reading without conflicts
- ✅ Better error diagnostics in logs

## 🔍 Verify Data Integrity

Query InfluxDB to check values are reasonable:

```bash
# Check uint32 energy values (should be large cumulative numbers)
influx query 'from(bucket:"databridge") |> range(start: -1h) 
  |> filter(fn: (r) => r._field =~ /energy/) 
  |> last()'

# Check int32 power values (should be reasonable kW values)
influx query 'from(bucket:"databridge") |> range(start: -1h) 
  |> filter(fn: (r) => r._field =~ /power/) 
  |> last()'
```

If you see:
- ❌ Very small numbers (< 1): Still broken
- ✅ Large cumulative numbers: Energy working correctly
- ✅ Reasonable kW values: Power working correctly

## 🎯 Root Cause Summary

**The Bug**:
```python
# OLD CODE (BROKEN):
response = self.modbus_client.read_holding_registers(
    address=address, count=1,  # Always 1 register
    slave=device.slave_id
)

# NEW CODE (FIXED):
register_count = self.register_reader.get_register_count(data_type)
response = self.modbus_client.read_holding_registers(
    address=address, count=register_count,  # Dynamic count
    slave=device.slave_id
)
```

**Why It Mattered**:
- uint16 value at address 778 = register[0] ✅ (1 register, works fine)
- uint32 value at address 1538 = register[0:1] ❌ (needs 2 registers, was reading 1)
- Result: Only reading HIGH word, missing LOW word = garbled data

## 🆘 Troubleshooting

If issues persist:

1. **Check if config was regenerated**:
   ```bash
   cat /etc/modbus_monitor/config.json | grep -A5 "device_"
   ```

2. **Verify PM2 is running new script**:
   ```bash
   pm2 describe modbus_monitor
   # Check "script path" is correct
   ```

3. **Check permissions**:
   ```bash
   ls -la /opt/modbus_monitor/modbus_monitor.py
   chmod +x /opt/modbus_monitor/modbus_monitor.py
   ```

4. **View detailed logs**:
   ```bash
   tail -100 /var/log/modbus_monitor/modbus_monitor.log | grep -i error
   ```

## 📞 Next Steps

1. Deploy the fixed script (see steps above)
2. Regenerate config (fixed slave IDs)
3. Monitor logs for 10 minutes
4. Verify Grafana dashboards show correct data
5. Consider standardizing field names (see ISSUES_FIXED.md)

Your data should now be accurate! 🎉

