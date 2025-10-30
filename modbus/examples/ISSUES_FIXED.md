# Modbus Monitor - Issues Found and Fixed

## 🚨 Critical Issues

### 1. **Data Type Handling Bug** ⚠️ CRITICAL
**Problem**: Your original script only reads `count=1` for ALL registers, ignoring the `data_type` field.

**Impact**:
- ✅ uint16/int16: Works correctly
- ❌ uint32/int32: Reads only half the data (garbled values)
- ❌ float32: Completely broken (produces meaningless numbers)

**Example from your config**:
```json
"1538": ["Active Energy Export", 100.0, "kWh", "uint32"]  // ❌ BROKEN
"788":  ["Active Power Total", 1000.0, "kW", "int32"]     // ❌ BROKEN
```

**Fix**: Added `RegisterReader` class that:
- Determines register count based on `data_type`
- Properly decodes 16-bit and 32-bit values
- Handles signed/unsigned values correctly
- Supports IEEE 754 float32 decoding

### 2. **Config Format Mismatch**
**Problem**: Django generates 4-tuple `(name, scale, unit, data_type)`, but your script only used 3 values.

**Impact**: The `data_type` field was stored but never used.

**Fix**: Updated `DeviceMonitor.__init__()` to handle both formats:
```python
if len(param_data) == 4:
    field_name, scaling, units, data_type = param_data
elif len(param_data) == 3:
    field_name, scaling, units = param_data
    data_type = 'uint16'  # Default assumption
```

### 3. **Duplicate Slave IDs** ⚠️ POTENTIAL CONFLICT
**Problem**: Multiple devices sharing the same `slave_id` on the same bus.

**Your config shows**:
- Device 7: slave_id = 2
- Device 12: slave_id = 2  ❌ CONFLICT
- Device 14: slave_id = 2  ❌ CONFLICT
- Device 15: slave_id = 2  ❌ CONFLICT

**Impact**: Only one device can be read correctly, others will fail or return wrong data.

**Solution Required**: Each device on the same RS485 bus MUST have a unique slave_id. Update your Django device configurations.

## 🔍 Improvements Made

### 1. **Proper Data Type Decoding**
```python
class RegisterReader:
    @staticmethod
    def decode_value(raw_registers, data_type, scale_factor):
        """Handles all data types correctly"""
        if data_type == 'uint32':
            # Combine high and low registers
            value = (raw_registers[0] << 16) | raw_registers[1]
        elif data_type == 'int32':
            # Handle sign extension
            raw_value = (raw_registers[0] << 16) | raw_registers[1]
            if raw_value & 0x80000000:
                raw_value = raw_value - 0x100000000
        elif data_type == 'float32':
            # IEEE 754 decoding
            high, low = raw_registers[0], raw_registers[1]
            float_bytes = pack('>HH', high, low)
            value = unpack('>f', float_bytes)[0]
```

### 2. **Dynamic Register Counting**
```python
# Old (BROKEN):
response = self.modbus_client.read_holding_registers(
    address=address, count=1, slave=device.slave_id  # Always 1
)

# New (FIXED):
register_count = self.register_reader.get_register_count(data_type)
response = self.modbus_client.read_holding_registers(
    address=address, count=register_count, slave=device.slave_id
)
```

### 3. **Enhanced Logging**
- Shows which data type was read
- Reports success/failure counts per device
- Better error messages for troubleshooting

### 4. **Better Error Handling**
- Validates register count before decoding
- Handles missing registers gracefully
- More informative exception messages

## 📋 Field Naming Consistency Issues

**Problem**: Inconsistent field naming in your config makes Grafana panels unreliable.

**Examples**:
```json
"778": ["voltage_v12", 10.0, "V", "uint16"]        // lowercase with underscore
"770": ["Voltage L2-N", 10.0, "V", "uint16"]       // Mixed case with spaces
"780": ["Current L1", 100.0, "A", "uint16"]        // Spaces instead of underscores
```

**Recommendation**: Standardize on one naming convention:

✅ **Best Practice**: Use lowercase with underscores, matching Django register names
```json
"voltage_l1_l2", "current_phase_1", "active_power_total"
```

**To Fix**: Update all your Django ModbusRegister entries to use consistent naming, then regenerate the config.

## 🎯 Required Actions

### 1. **Immediate**: Fix Duplicate Slave IDs
Update your Django database to assign unique slave IDs:

```python
# In Django shell:
from modbus.models import ModbusDevice

# Check current slave IDs
for device in ModbusDevice.objects.all():
    print(f"{device.name}: slave_id={device.address}")

# Fix duplicates (assign unique IDs 1, 2, 3, 4, 5)
devices = ModbusDevice.objects.filter(is_active=True)
for idx, device in enumerate(devices, start=1):
    device.address = idx
    device.save()
    print(f"Set {device.name} to slave_id={idx}")

# Regenerate config
# Use Django API: POST /api/modbus/devices/apply_all_configurations/
```

### 2. **Immediate**: Deploy Fixed Script
Replace your current `modbus_monitor.py` with the fixed version:

```bash
# On BeagleBone:
cd /opt/modbus_monitor
cp modbus_monitor.py modbus_monitor_backup.py
# Copy the new version from examples/modbus_monitor_fixed.py
# Restart PM2
pm2 restart modbus_monitor
```

### 3. **Recommended**: Standardize Field Names
Review and update all register names in Django to use consistent naming.

### 4. **Test**: Verify Data Integrity
After deploying the fix:

```bash
# Check logs for successful reads
tail -f /var/log/modbus_monitor/modbus_monitor.log

# Query InfluxDB to verify 32-bit values are correct
influx query 'from(bucket:"databridge") |> range(start: -1h) |> filter(fn: (r) => r._field == "active_energy_import")'
```

## 📊 Expected Improvements

After applying these fixes, you should see:

1. ✅ Correct energy values (uint32 registers working)
2. ✅ Accurate power readings (int32 registers working)  
3. ✅ All devices reading successfully (unique slave IDs)
4. ✅ No data corruption from wrong register counts
5. ✅ Better error diagnostics from enhanced logging

## 🔗 Integration Flow (Updated)

```
Django Admin
    ↓
generate_multi_device_config()  // Generates 4-tuple params
    ↓
write_configuration_file()  // Writes to /etc/modbus_monitor/config.json
    ↓
modbus_monitor_fixed.py  // Now reads data_type correctly ✅
    ↓
RegisterReader.decode_value()  // Properly handles all types
    ↓
InfluxDB (correct values)  // No more garbage data ✅
    ↓
Grafana (accurate dashboards)  // All metrics showing correctly
```

## 🧪 Testing Checklist

- [ ] Deploy fixed modbus_monitor.py script
- [ ] Fix duplicate slave IDs in Django
- [ ] Regenerate config.json
- [ ] Restart PM2 service
- [ ] Verify uint32 energy registers show correct values
- [ ] Verify int32 power registers show correct values
- [ ] Check all devices reading successfully
- [ ] Validate Grafana dashboards showing correct data

