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
