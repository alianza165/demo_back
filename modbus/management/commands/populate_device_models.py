# management/commands/populate_device_models.py
from django.core.management.base import BaseCommand
from modbus.models import DeviceModel, ModbusRegister

class Command(BaseCommand):
    help = 'Populate device models with standard registers'
    
    def handle(self, *args, **options):
        self.stdout.write('Populating device models with registers...')
        
        # Standard Energy Meter Registers
        standard_meter, created = DeviceModel.objects.get_or_create(
            name="Standard Energy Meter",
            defaults={
                'manufacturer': 'Generic',
                'description': 'Standard three-phase energy meter with basic measurements'
            }
        )
        
        standard_registers = [
            # Voltage
            (768, "Voltage L1-N", "uint16", 10.0, "V", "voltage", "voltage_l1_n"),
            (770, "Voltage L2-N", "uint16", 10.0, "V", "voltage", "voltage_l2_n"),
            (772, "Voltage L3-N", "uint16", 10.0, "V", "voltage", "voltage_l3_n"),
            (774, "Voltage L1-L2", "uint16", 10.0, "V", "voltage", "voltage_l1_l2"),
            (776, "Voltage L2-L3", "uint16", 10.0, "V", "voltage", "voltage_l2_l3"),
            (778, "Voltage L3-L1", "uint16", 10.0, "V", "voltage", "voltage_l3_l1"),
            
            # Current
            (780, "Current L1", "uint16", 100.0, "A", "current", "current_l1"),
            (782, "Current L2", "uint16", 100.0, "A", "current", "current_l2"),
            (784, "Current L3", "uint16", 100.0, "A", "current", "current_l3"),
            (786, "Current Neutral", "uint16", 100.0, "A", "current", "current_neutral"),
            
            # Power
            (788, "Active Power Total", "int32", 1000.0, "kW", "power", "active_power_total"),
            (790, "Active Power L1", "int32", 1000.0, "kW", "power", "active_power_l1"),
            (792, "Active Power L2", "int32", 1000.0, "kW", "power", "active_power_l2"),
            (794, "Active Power L3", "int32", 1000.0, "kW", "power", "active_power_l3"),
            (796, "Reactive Power Total", "int32", 1000.0, "kVAR", "power", "reactive_power_total"),
            (798, "Apparent Power Total", "int32", 1000.0, "kVA", "power", "apparent_power_total"),
            
            # Power Factor
            (800, "Power Factor Total", "int16", 1000.0, "", "power_quality", "power_factor_total"),
            (801, "Power Factor L1", "int16", 1000.0, "", "power_quality", "power_factor_l1"),
            (802, "Power Factor L2", "int16", 1000.0, "", "power_quality", "power_factor_l2"),
            (803, "Power Factor L3", "int16", 1000.0, "", "power_quality", "power_factor_l3"),
            
            # Frequency
            (804, "Frequency", "uint16", 10.0, "Hz", "frequency", "frequency"),
            
            # Energy
            (1536, "Active Energy Import", "uint32", 1.0, "kWh", "energy", "energy_active"),
            (1538, "Active Energy Export", "uint32", 1.0, "kWh", "energy", "energy_reactive"),
        ]
        
        self._create_registers(standard_meter, standard_registers, "Standard Energy Meter")
        
        # ABB Power Meter Registers (different register map)
        abb_meter, created = DeviceModel.objects.get_or_create(
            name="ABB Power Meter",
            defaults={
                'manufacturer': 'ABB',
                'model_number': 'ABC123',
                'description': 'Three-phase power meter with advanced measurements'
            }
        )
        
        abb_registers = [
            # ABB typically uses different register addresses
            (30001, "Voltage L1-N", "uint16", 10.0, "V", "voltage", "voltage_l1_n"),
            (30003, "Voltage L2-N", "uint16", 10.0, "V", "voltage", "voltage_l2_n"),
            (30005, "Voltage L3-N", "uint16", 10.0, "V", "voltage", "voltage_l3_n"),
            (30007, "Current L1", "uint16", 100.0, "A", "current", "current_l1"),
            (30009, "Current L2", "uint16", 100.0, "A", "current", "current_l2"),
            (30011, "Current L3", "uint16", 100.0, "A", "current", "current_l3"),
            (30013, "Active Power Total", "int32", 1000.0, "kW", "power", "active_power_total"),
            (30017, "Reactive Power Total", "int32", 1000.0, "kVAR", "power", "reactive_power_total"),
            (30021, "Apparent Power Total", "int32", 1000.0, "kVA", "power", "apparent_power_total"),
            (30025, "Power Factor Total", "int16", 1000.0, "", "power_quality", "power_factor_total"),
            (30027, "Frequency", "uint16", 10.0, "Hz", "frequency", "frequency"),
            (30029, "Active Energy Import", "uint32", 1.0, "kWh", "energy", "energy_active"),
        ]
        
        self._create_registers(abb_meter, abb_registers, "ABB Power Meter")
        
        # Circutor Energy Analyzer (based on provided register map)
        circutor_meter, _ = DeviceModel.objects.get_or_create(
            name="Circutor Energy Analyzer",
            defaults={
                'manufacturer': 'Circutor',
                'model_number': 'CVM-series',
                'description': 'Three-phase energy analyzer with extensive instantaneous measurements'
            }
        )
        
        def hex_addr(value):
            return int(value, 16)
        
        circutor_registers = [
            # Phase voltages
            (hex_addr('00'), "L1 Phase Voltage", "uint32", 10.0, "V", "voltage", "voltage_l1"),
            (hex_addr('10'), "L2 Phase Voltage", "uint32", 10.0, "V", "voltage", "voltage_l2"),
            (hex_addr('20'), "L3 Phase Voltage", "uint32", 10.0, "V", "voltage", "voltage_l3"),
            
            # Phase currents (doc reports mA; convert to amps dividing by 1000)
            (hex_addr('02'), "L1 Current", "uint32", 1000.0, "A", "current", "current_l1"),
            (hex_addr('12'), "L2 Current", "uint32", 1000.0, "A", "current", "current_l2"),
            (hex_addr('22'), "L3 Current", "uint32", 1000.0, "A", "current", "current_l3"),
            
            # Active power per phase
            (hex_addr('04'), "L1 Active Power", "int32", 1.0, "W", "power", "active_power_l1"),
            (hex_addr('14'), "L2 Active Power", "int32", 1.0, "W", "power", "active_power_l2"),
            (hex_addr('24'), "L3 Active Power", "int32", 1.0, "W", "power", "active_power_l3"),
            
            # Apparent power per phase
            (hex_addr('0A'), "L1 Apparent Power", "int32", 1.0, "VA", "power", "apparent_power_l1"),
            (hex_addr('1A'), "L2 Apparent Power", "int32", 1.0, "VA", "power", "apparent_power_l2"),
            (hex_addr('2A'), "L3 Apparent Power", "int32", 1.0, "VA", "power", "apparent_power_l3"),
            
            # Power factor per phase
            (hex_addr('0C'), "L1 Power Factor", "int16", 1000.0, "", "power_quality", "power_factor_l1"),
            (hex_addr('1C'), "L2 Power Factor", "int16", 1000.0, "", "power_quality", "power_factor_l2"),
            (hex_addr('2C'), "L3 Power Factor", "int16", 1000.0, "", "power_quality", "power_factor_l3"),
            
            # Cos φ per phase
            (hex_addr('0E'), "Cos Phi L1", "int16", 1000.0, "", "power_quality", "phase_angle_l1"),
            (hex_addr('1E'), "Cos Phi L2", "int16", 1000.0, "", "power_quality", "phase_angle_l2"),
            (hex_addr('2E'), "Cos Phi L3", "int16", 1000.0, "", "power_quality", "phase_angle_l3"),
            
            # Three-phase totals
            (hex_addr('30'), "Active Three-phase Power", "int32", 1.0, "W", "power", "active_power_total"),
            (hex_addr('32'), "Inductive Three-phase Power", "int32", 1.0, "VAR", "power", "reactive_power_total"),
            (hex_addr('34'), "Capacitive Three-phase Power", "int32", 1.0, "VAR", "power", "capacitive_power_total"),
            (hex_addr('36'), "Apparent Three-phase Power", "int32", 1.0, "VA", "power", "apparent_power_total"),
            (hex_addr('38'), "Three-phase Power Factor", "int16", 1000.0, "", "power_quality", "power_factor_total"),
        ]
        
        self._create_registers(circutor_meter, circutor_registers, "Circutor Energy Analyzer")
        
        # Thermal Flow Meter registers (instantaneous + totals)
        flow_meter, _ = DeviceModel.objects.get_or_create(
            name="Thermal Flow Meter",
            defaults={
                'manufacturer': 'Generic',
                'model_number': 'Heat-Flow-400',
                'description': 'Heat/flow meter with Modbus holding registers starting at 40001'
            }
        )
        
        flow_registers = [
            (40001, "Instantaneous Flow", "float32", 1.0, "m3/h", "other", "instantaneous_flow"),
            (40003, "Differential Pressure/Frequency", "float32", 1.0, "kPa", "other", "differential_pressure"),
            (40005, "Temperature", "float32", 1.0, "°C", "temperature", "temperature"),
            (40007, "Pressure", "float32", 1.0, "kPa", "other", "pressure"),
            (40009, "Total Amount of Flow", "uint32", 1.0, "m3", "other", "total_flow"),
            (40011, "Instantaneous Heat", "float32", 1.0, "kW", "power", "instantaneous_heat"),
            (40013, "Total Amount of Heat", "uint32", 1.0, "kWh", "energy", "total_heat"),
            (40015, "Density", "float32", 1.0, "kg/m3", "other", "density"),
            (40017, "Last Power-down Time", "uint32", 1.0, "s", "status", "last_power_down"),
            (40019, "Last Power-on Time", "uint32", 1.0, "s", "status", "last_power_on"),
            (40021, "Total Power-down Time", "uint32", 1.0, "s", "status", "total_power_down_seconds"),
            (40023, "Number of Power-down Events", "uint16", 1.0, "count", "status", "power_down_events"),
            (40024, "Differential Pressure Disconnect", "uint16", 1.0, "", "status", "dp_disconnect_flag"),
            (40025, "Temperature Disconnect", "uint16", 1.0, "", "status", "temp_disconnect_flag"),
            (40026, "Pressure Disconnect", "uint16", 1.0, "", "status", "pressure_disconnect_flag"),
            (40031, "System Time (seconds)", "uint32", 1.0, "s", "status", "system_time_seconds"),
            (40033, "Switching Value", "uint16", 1.0, "", "status", "switching_value"),
        ]
        
        self._create_registers(flow_meter, flow_registers, "Thermal Flow Meter")
        
        self.stdout.write(
            self.style.SUCCESS('Successfully populated device models with registers!')
        )
    
    def _create_registers(self, device_model, registers, model_name):
        created_count = 0
        for order, (address, name, data_type, scale, unit, category, em_field) in enumerate(registers):
            _, created = ModbusRegister.objects.get_or_create(
                device_model=device_model,
                address=address,
                defaults={
                    'name': name,
                    'data_type': data_type,
                    'scale_factor': scale,
                    'unit': unit,
                    'category': category,
                    'order': order,
                    'energy_measurement_field': em_field,
                    'visualization_type': 'timeseries'
                }
            )
            if created:
                created_count += 1
        
        self.stdout.write(
            f"Created {created_count} registers for {model_name}"
        )
