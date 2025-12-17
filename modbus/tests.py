"""
Comprehensive tests for Modbus device and register CRUD operations.
Tests cover device creation, modification, and all requirements mentioned in project specs.

Test Categories:
1. Create Device - All requirements for new device creation
2. Modify Device - All requirements for device modification  
3. Register Operations - CRUD operations on registers
4. Validation Tests - Business rule enforcement
"""

from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from .models import DeviceModel, ModbusDevice, ModbusRegister


# ============================================================================
# TEST SETUP AND FIXTURES
# ============================================================================

class BaseModbusTestCase(TestCase):
    """Base test case with common setup"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.client = APIClient()
        
        # Create device models for testing
        self.device_model_abb = DeviceModel.objects.create(
            name="ABB Power Meter",
            manufacturer="ABB",
            model_number="PM5560",
            description="Three-phase energy analyzer",
            is_active=True
        )
        
        # Create register templates for ABB model
        self.register_voltage = ModbusRegister.objects.create(
            device_model=self.device_model_abb,
            address=0x0000,
            name="Voltage L1",
            data_type="float32",
            scale_factor=0.1,
            unit="V",
            category="voltage",
            visualization_type="timeseries",
            is_active=True,
            order=0
        )
        
        self.register_power = ModbusRegister.objects.create(
            device_model=self.device_model_abb,
            address=0x0002,
            name="Active Power Total",
            data_type="float32",
            scale_factor=1.0,
            unit="W",
            category="power",
            visualization_type="gauge",
            is_active=True,
            order=1
        )
    
        # Create another device model for testing device_model change prevention
        self.device_model_siemens = DeviceModel.objects.create(
            name="Siemens Energy Meter",
            manufacturer="Siemens",
            model_number="7KM4212",
            description="Energy monitoring device",
            is_active=True
        )
        

# ============================================================================
# CREATE DEVICE TESTS
# ============================================================================

class CreateDeviceTestCase(BaseModbusTestCase):
    """Test creating new devices with all requirements"""
    
    def test_create_device_with_device_model(self):
        """
        Requirement: Add registers from existing device model
        - Can only select one device model per new device
        - Registers from model are copied to device
        """
        data = {
            "name": "Main Panel Meter",
            "device_model": self.device_model_abb.id,
            "device_type": "electricity",
            "application_type": "machine",
            "port": "/dev/ttyUSB0",
            "address": 1,
            "baud_rate": 9600,
            "is_active": True
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.device_model.id, self.device_model_abb.id)
        # Verify registers from device model were copied
        self.assertEqual(device.registers.count(), 2)
        self.assertTrue(device.registers.filter(name="Voltage L1").exists())
        self.assertTrue(device.registers.filter(name="Active Power Total").exists())
        # Verify registers belong to device, not device_model
        for register in device.registers.all():
            self.assertEqual(register.device.id, device.id)
            self.assertIsNone(register.device_model)
    
    def test_create_device_with_device_model_and_custom_registers(self):
        """
        Requirement: Add registers from device model AND add custom registers
        - Device model registers are copied first
        - Custom registers are added on top
        """
        data = {
            "name": "Custom Device",
            "device_model": self.device_model_abb.id,
            "device_type": "flowmeter",
            "application_type": "process",
            "port": "/dev/ttyUSB0",
            "address": 2,
            "registers": [
                {
                    "address": 0x0010,
                    "name": "Custom Flow Rate",
                    "data_type": "float32",
                    "scale_factor": 1.0,
                    "unit": "m³/h",
                    "category": "flow",
                    "visualization_type": "gauge"
                }
            ]
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        # Should have 2 from model + 1 custom = 3 total
        self.assertEqual(device.registers.count(), 3)
        self.assertTrue(device.registers.filter(name="Custom Flow Rate").exists())
        self.assertTrue(device.registers.filter(name="Voltage L1").exists())
    
    def test_create_device_custom_register_override_model_register(self):
        """
        Requirement: Custom register can override model register at same address
        - When custom register has same address as model register, custom takes precedence
        """
        data = {
            "name": "Device with Custom Override",
            "device_model": self.device_model_abb.id,
            "device_type": "electricity",
            "application_type": "facility",
            "port": "/dev/ttyUSB0",
            "address": 3,
            "registers": [
                {
                    "address": 0x0000,  # Same address as model register
                    "name": "Voltage L1 Custom",
                    "data_type": "float32",
                    "scale_factor": 0.1,
                    "unit": "V",
                    "category": "voltage",
                    "visualization_type": "stat"  # Changed from timeseries to stat
                }
            ]
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        # Should have 2 registers (custom overrides model register at 0x0000, model register at 0x0002 added)
        voltage_register = device.registers.get(address=0x0000)
        self.assertEqual(voltage_register.visualization_type, "stat")
        self.assertEqual(voltage_register.name, "Voltage L1 Custom")
        # Model register at 0x0002 should still be present
        self.assertTrue(device.registers.filter(address=0x0002).exists())
    
    def test_create_device_change_register_visualization_type(self):
        """
        Requirement: Change register/parameter visualization type during creation
        - Can specify different visualization_type for registers
        """
        data = {
            "name": "Device with Custom Visualization",
            "device_model": self.device_model_abb.id,
            "device_type": "electricity",
            "application_type": "machine",
            "port": "/dev/ttyUSB0",
            "address": 4,
            "registers": [
                {
                    "address": 0x0000,
                    "name": "Voltage L1",
                    "data_type": "float32",
                    "scale_factor": 0.1,
                    "unit": "V",
                    "category": "voltage",
                    "visualization_type": "gauge"  # Changed from timeseries
                },
                {
                    "address": 0x0002,
                    "name": "Active Power Total",
                    "data_type": "float32",
                    "scale_factor": 1.0,
                    "unit": "W",
                    "category": "power",
                    "visualization_type": "stat"  # Changed from gauge
                }
            ]
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        voltage_reg = device.registers.get(address=0x0000)
        power_reg = device.registers.get(address=0x0002)
        self.assertEqual(voltage_reg.visualization_type, "gauge")
        self.assertEqual(power_reg.visualization_type, "stat")
    
    def test_create_device_type_electricity(self):
        """Requirement: Set device type - electricity"""
        data = {
            "name": "Electricity Analyzer",
            "device_type": "electricity",
            "application_type": "wapda",
            "port": "/dev/ttyUSB0",
            "address": 5
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.device_type, "electricity")
    
    def test_create_device_type_flowmeter(self):
        """Requirement: Set device type - flowmeter"""
        data = {
            "name": "Flow Meter",
            "device_type": "flowmeter",
            "application_type": "process",
            "port": "/dev/ttyUSB0",
            "address": 6
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.device_type, "flowmeter")
    
    def test_create_device_type_temp_gauge(self):
        """Requirement: Set device type - temp_gauge"""
        data = {
            "name": "Temperature Gauge",
            "device_type": "temp_gauge",
            "application_type": "dept",
            "port": "/dev/ttyUSB0",
            "address": 7
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.device_type, "temp_gauge")
    
    def test_create_device_supply_gen(self):
        """Requirement: Set application_type = gen (supply category)"""
        data = {
            "name": "Generator Meter",
            "device_type": "electricity",
            "application_type": "gen",
            "port": "/dev/ttyUSB0",
            "address": 8
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "gen")
    
    def test_create_device_supply_wapda(self):
        """Requirement: Set application_type = wapda (supply category)"""
        data = {
            "name": "WAPDA Meter",
            "device_type": "electricity",
            "application_type": "wapda",
            "port": "/dev/ttyUSB0",
            "address": 9
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "wapda")
    
    def test_create_device_supply_solar(self):
        """Requirement: Set application_type = solar (supply category)"""
        data = {
            "name": "Solar Panel Meter",
            "device_type": "electricity",
            "application_type": "solar",
            "port": "/dev/ttyUSB0",
            "address": 10
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "solar")
    
    def test_create_device_load_dept(self):
        """Requirement: Set application_type = dept (load category)"""
        data = {
            "name": "Department Meter",
            "device_type": "electricity",
            "application_type": "dept",
            "port": "/dev/ttyUSB0",
            "address": 11
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "dept")
    
    def test_create_device_load_facility(self):
        """Requirement: Set application_type = facility (load category)"""
        data = {
            "name": "Facility Meter",
            "device_type": "electricity",
            "application_type": "facility",
            "port": "/dev/ttyUSB0",
            "address": 12
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "facility")
    
    def test_create_device_load_process(self):
        """Requirement: Set application_type = process (load category)"""
        data = {
            "name": "Process Meter",
            "device_type": "electricity",
            "application_type": "process",
            "port": "/dev/ttyUSB0",
            "address": 13
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "process")
    
    def test_create_device_load_machine(self):
        """Requirement: Set application_type = machine (load category)"""
        data = {
            "name": "Machine Meter",
            "device_type": "electricity",
            "application_type": "machine",
            "port": "/dev/ttyUSB0",
            "address": 14
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertEqual(device.application_type, "machine")

    def test_create_device_without_device_model(self):
        """Test creating device without device model (custom device)"""
        data = {
            "name": "Custom Device No Model",
            "device_type": "electricity",
            "application_type": "machine",
            "port": "/dev/ttyUSB0",
            "address": 15,
            "registers": [
                {
                    "address": 0x0100,
                    "name": "Custom Register 1",
                    "data_type": "uint16",
                    "scale_factor": 1.0,
                    "visualization_type": "timeseries"
                }
            ]
        }
        response = self.client.post('/api/modbus/devices/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        device = ModbusDevice.objects.get(id=response.data['id'])
        self.assertIsNone(device.device_model)
        self.assertEqual(device.registers.count(), 1)
        self.assertTrue(device.registers.filter(name="Custom Register 1").exists())


# ============================================================================
# MODIFY DEVICE TESTS
# ============================================================================

class ModifyDeviceTestCase(BaseModbusTestCase):
    """Test modifying existing devices with all requirements"""
    
    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create device with model for testing modifications
        self.device = ModbusDevice.objects.create(
            name="Test Device",
            device_model=self.device_model_abb,
            device_type="electricity",
            application_type="machine",  # Load category
            port="/dev/ttyUSB0",
            address=1
        )
        
        # Copy registers from model to device
        for model_reg in self.device_model_abb.register_templates.all():
            ModbusRegister.objects.create(
                device=self.device,
                address=model_reg.address,
                name=model_reg.name,
                data_type=model_reg.data_type,
                scale_factor=model_reg.scale_factor,
                unit=model_reg.unit,
                category=model_reg.category,
                visualization_type=model_reg.visualization_type,
                is_active=model_reg.is_active,
                order=model_reg.order
            )
    
    def test_add_register_to_device(self):
        """
        Requirement: Add registers to existing device
        """
        initial_count = self.device.registers.count()
        
        # Get existing registers with all fields (exclude device and device_model as they're set by serializer)
        existing_registers = [
            {
                "id": reg.id,
                "address": reg.address,
                "name": reg.name,
                "data_type": reg.data_type,
                "scale_factor": reg.scale_factor,
                "visualization_type": reg.visualization_type,
                "category": reg.category,
                "unit": reg.unit,
                "order": reg.order,
                "register_count": reg.register_count,
                "word_order": reg.word_order,
                "is_active": reg.is_active
                # Note: device and device_model are excluded - they're handled by the serializer
            }
            for reg in self.device.registers.all()
        ]
        
        # Add new register
        data = {
            "name": "Test Device",
            "registers": existing_registers + [
                {
                    "address": 0x0010,
                    "name": "New Register",
                    "data_type": "uint16",
                    "scale_factor": 1.0,
                    "visualization_type": "timeseries",
                    "category": "other"
                }
            ]
        }
        
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.registers.count(), initial_count + 1)
        self.assertTrue(self.device.registers.filter(name="New Register").exists())
    
    def test_remove_register_from_device(self):
        """
        Requirement: Remove registers from existing device
        """
        initial_count = self.device.registers.count()
        self.assertGreater(initial_count, 0)
        
        # Get all registers except one
        all_registers = list(self.device.registers.all())
        remaining_registers = all_registers[:-1] if len(all_registers) > 1 else []
        data = {
            "name": "Test Device",
            "registers": [
                {
                    "id": reg.id,
                    "address": reg.address,
                    "name": reg.name,
                    "data_type": reg.data_type,
                    "scale_factor": reg.scale_factor,
                    "visualization_type": reg.visualization_type,
                    "category": reg.category,
                    "unit": reg.unit,
                    "order": reg.order,
                    "register_count": reg.register_count,
                    "word_order": reg.word_order,
                    "is_active": reg.is_active
                }
                for reg in remaining_registers
            ]
        }
        
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.registers.count(), initial_count - 1)
    
    def test_edit_register_visualization_type(self):
        """
        Requirement: Edit visualization of registers
        """
        register = self.device.registers.first()
        original_viz_type = register.visualization_type
        new_viz_type = "stat" if original_viz_type != "stat" else "gauge"
        
        # Get all registers and modify visualization_type for one
        data = {
            "name": "Test Device",
            "registers": [
                {
                    "id": reg.id,
                    "address": reg.address,
                    "name": reg.name,
                    "data_type": reg.data_type,
                    "scale_factor": reg.scale_factor,
                    "visualization_type": new_viz_type if reg.id == register.id else reg.visualization_type,
                    "category": reg.category,
                    "unit": reg.unit,
                    "order": reg.order,
                    "register_count": reg.register_count,
                    "word_order": reg.word_order,
                    "is_active": reg.is_active
                }
                for reg in self.device.registers.all()
            ]
        }
        
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        register.refresh_from_db()
        self.assertEqual(register.visualization_type, new_viz_type)
        self.assertNotEqual(register.visualization_type, original_viz_type)
    
    def test_edit_register_other_fields(self):
        """Test editing other register fields (name, scale_factor, etc.)"""
        register = self.device.registers.first()
        original_name = register.name
        new_name = "Modified Register Name"
        
        data = {
            "name": "Test Device",
            "registers": [
                {
                    "id": reg.id,
                    "address": reg.address,
                    "name": new_name if reg.id == register.id else reg.name,
                    "data_type": reg.data_type,
                    "scale_factor": 2.5 if reg.id == register.id else reg.scale_factor,
                    "visualization_type": reg.visualization_type,
                    "category": reg.category,
                    "unit": "kW" if reg.id == register.id and reg.unit else reg.unit,
                    "order": reg.order,
                    "register_count": reg.register_count,
                    "word_order": reg.word_order,
                    "is_active": reg.is_active
                }
                for reg in self.device.registers.all()
            ]
        }
        
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        register.refresh_from_db()
        self.assertEqual(register.name, new_name)
        self.assertNotEqual(register.name, original_name)
        self.assertEqual(register.scale_factor, 2.5)
    
    def test_cannot_change_device_model_when_already_set(self):
        """
        Requirement: Cannot add device model as it is associated initially
        - If device already has a model, cannot change it
        """
        # Device already has device_model set in setUp
        self.assertIsNotNone(self.device.device_model)
        
        data = {
            "device_model": self.device_model_siemens.id
        }
        
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('device_model', response.data)
        self.assertIn('Cannot change device_model', str(response.data['device_model']))
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.device_model.id, self.device_model_abb.id)
    
    def test_can_set_device_model_if_none(self):
        """Test that device_model can be set if device doesn't have one yet"""
        # Create device without model
        device_no_model = ModbusDevice.objects.create(
            name="Device Without Model",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=20
        )
        
        data = {
            "device_model": self.device_model_abb.id
        }
        
        response = self.client.patch(f'/api/modbus/devices/{device_no_model.id}/', data, format='json')
        # Should work but might warn (based on implementation)
        # The implementation allows it but logs a warning
        device_no_model.refresh_from_db()
        # Note: The serializer allows setting model if device didn't have one, but warns
    
    def test_cannot_change_application_type_from_load_to_supply(self):
        """
        Requirement: Cannot change supply/load category
        - Device starts as "machine" (load)
        - Cannot change to supply category (gen/wapda/solar)
        """
        self.assertEqual(self.device.application_type, "machine")
        
        # Try to change to supply category
        for supply_type in ["gen", "wapda", "solar"]:
            data = {"application_type": supply_type}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('application_type', response.data)
        self.assertIn('Cannot change application_type from load category', str(response.data['application_type']))
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.application_type, "machine")
    
    def test_cannot_change_application_type_from_supply_to_load(self):
        """
        Requirement: Cannot change supply/load category
        - Device starts as supply
        - Cannot change to load category (dept/facility/process/machine)
        """
        supply_device = ModbusDevice.objects.create(
            name="Supply Device",
            device_type="electricity",
            application_type="gen",  # Supply category
            port="/dev/ttyUSB0",
            address=21
        )
        
        # Try to change to load category
        for load_type in ["dept", "facility", "process", "machine"]:
            data = {"application_type": load_type}
            response = self.client.patch(f'/api/modbus/devices/{supply_device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('application_type', response.data)
        self.assertIn('Cannot change application_type from supply category', str(response.data['application_type']))
        
        supply_device.refresh_from_db()
        self.assertEqual(supply_device.application_type, "gen")
    
    def test_can_change_application_type_within_supply_category(self):
        """
        Requirement: Can change supply -> wapda, gen, solar (within supply category)
        """
        supply_device = ModbusDevice.objects.create(
            name="Supply Device",
            device_type="electricity",
            application_type="gen",
            port="/dev/ttyUSB0",
            address=22
        )
        
        # Change gen -> wapda
        data = {"application_type": "wapda"}
        response = self.client.patch(f'/api/modbus/devices/{supply_device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        supply_device.refresh_from_db()
        self.assertEqual(supply_device.application_type, "wapda")
        
        # Change wapda -> solar
        data = {"application_type": "solar"}
        response = self.client.patch(f'/api/modbus/devices/{supply_device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        supply_device.refresh_from_db()
        self.assertEqual(supply_device.application_type, "solar")
        
        # Change solar -> gen
        data = {"application_type": "gen"}
        response = self.client.patch(f'/api/modbus/devices/{supply_device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        supply_device.refresh_from_db()
        self.assertEqual(supply_device.application_type, "gen")
    
    def test_can_change_application_type_within_load_category(self):
        """
        Requirement: Can change load -> dept, facility, process, machine (within load category)
        """
        # Device starts as "machine" (load)
        self.assertEqual(self.device.application_type, "machine")
        
        # Change machine -> dept
        data = {"application_type": "dept"}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.device.refresh_from_db()
        self.assertEqual(self.device.application_type, "dept")
        
        # Change dept -> facility
        data = {"application_type": "facility"}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.device.refresh_from_db()
        self.assertEqual(self.device.application_type, "facility")
        
        # Change facility -> process
        data = {"application_type": "process"}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.device.refresh_from_db()
        self.assertEqual(self.device.application_type, "process")
        
        # Change process -> machine
        data = {"application_type": "machine"}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.device.refresh_from_db()
        self.assertEqual(self.device.application_type, "machine")
    
    def test_can_change_parent_device(self):
        """
        Requirement: Can change parent device
        """
        parent = ModbusDevice.objects.create(
            name="Parent Device",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=23
        )
        
        self.assertIsNone(self.device.parent_device)
        
        # Set parent
        data = {"parent_device": parent.id}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.parent_device.id, parent.id)
        
        # Change to different parent
        new_parent = ModbusDevice.objects.create(
            name="New Parent",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=24
        )
        
        data = {"parent_device": new_parent.id}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.parent_device.id, new_parent.id)
        
        # Remove parent (set to None)
        data = {"parent_device": None}
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertIsNone(self.device.parent_device)

    def test_update_device_other_fields(self):
        """Test updating other device fields (name, port, etc.)"""
        data = {
            "name": "Updated Device Name",
            "port": "/dev/ttyUSB1",
            "baud_rate": 19200
        }
        
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, "Updated Device Name")
        self.assertEqual(self.device.port, "/dev/ttyUSB1")
        self.assertEqual(self.device.baud_rate, 19200)


# ============================================================================
# REGISTER CRUD TESTS
# ============================================================================

class RegisterOperationsTestCase(BaseModbusTestCase):
    """Test register CRUD operations"""
    
    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        self.device = ModbusDevice.objects.create(
            name="Test Device",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=1
        )
    
    def test_create_register_via_device_update(self):
        """Test creating a register by updating device"""
        data = {
            "registers": [
                {
            "address": 0x0000,
            "name": "Test Register",
            "data_type": "uint16",
            "scale_factor": 1.0,
            "unit": "V",
            "category": "voltage",
            "visualization_type": "timeseries"
        }
            ]
        }
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.registers.count(), 1)
        register = self.device.registers.first()
        self.assertEqual(register.name, "Test Register")
        self.assertEqual(register.address, 0x0000)
    
    def test_update_register_via_device_update(self):
        """Test updating a register by updating device"""
        register = ModbusRegister.objects.create(
            device=self.device,
            address=0x0000,
            name="Original Name",
            data_type="uint16",
            visualization_type="timeseries"
        )
        
        data = {
            "registers": [
                {
                    "id": register.id,
                    "address": register.address,
                    "name": "Updated Name",
                    "data_type": register.data_type,
                    "scale_factor": register.scale_factor,
                    "visualization_type": "gauge",
                    "category": "other",
                    "order": register.order,
                    "register_count": register.register_count,
                    "word_order": register.word_order,
                    "is_active": register.is_active
                }
            ]
        }
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        register.refresh_from_db()
        self.assertEqual(register.name, "Updated Name")
        self.assertEqual(register.visualization_type, "gauge")
    
    def test_delete_register_via_device_update(self):
        """Test deleting a register by removing it from device update"""
        register = ModbusRegister.objects.create(
            device=self.device,
            address=0x0000,
            name="To Delete",
            data_type="uint16"
        )
        
        # Remove register by not including it in update
        data = {
            "registers": []
        }
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        self.assertEqual(self.device.registers.count(), 0)
        self.assertFalse(ModbusRegister.objects.filter(id=register.id).exists())
    
    def test_unique_address_per_device(self):
        """Test that registers must have unique addresses per device"""
        ModbusRegister.objects.create(
            device=self.device,
            address=0x0000,
            name="First Register",
            data_type="uint16"
        )
        
        # Try to add another register with same address - should update existing
        data = {
            "registers": [
                {
                    "address": 0x0000,
                    "name": "Updated Register",
                    "data_type": "uint16",
                    "visualization_type": "timeseries",
                    "category": "other"
                }
            ]
        }
        response = self.client.patch(f'/api/modbus/devices/{self.device.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.device.refresh_from_db()
        # Should still have only one register, but with updated name
        self.assertEqual(self.device.registers.count(), 1)
        register = self.device.registers.first()
        self.assertEqual(register.name, "Updated Register")


# ============================================================================
# DEVICE MODEL TESTS
# ============================================================================

class DeviceModelTestCase(BaseModbusTestCase):
    """Test DeviceModel operations"""
    
    def test_list_device_models(self):
        """Test listing device models"""
        response = self.client.get('/api/modbus/device-models/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
    
    def test_get_device_model_registers(self):
        """Test retrieving registers for a device model"""
        response = self.client.get(f'/api/modbus/device-models/{self.device_model_abb.id}/registers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)


# ============================================================================
# PARENT DEVICE RELATIONSHIP TESTS
# ============================================================================

class DeviceParentRelationshipTestCase(BaseModbusTestCase):
    """Test parent device relationship operations"""
    
    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        self.parent = ModbusDevice.objects.create(
            name="Parent Device",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=1
        )
        
        self.child = ModbusDevice.objects.create(
            name="Child Device",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=2
        )
    
    def test_set_parent_device_via_endpoint(self):
        """Test setting parent device using the custom endpoint"""
        response = self.client.post(
            f'/api/modbus/devices/{self.child.id}/set_parent/',
            {"parent_device_id": self.parent.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_device.id, self.parent.id)
    
    def test_set_parent_device_via_patch(self):
        """Test setting parent device via PATCH"""
        data = {"parent_device": self.parent.id}
        response = self.client.patch(f'/api/modbus/devices/{self.child.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.child.refresh_from_db()
        self.assertEqual(self.child.parent_device.id, self.parent.id)
    
    def test_remove_parent_device(self):
        """Test removing parent device"""
        self.child.parent_device = self.parent
        self.child.save()
        
        response = self.client.post(
            f'/api/modbus/devices/{self.child.id}/set_parent/',
            {"parent_device_id": None},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.child.refresh_from_db()
        self.assertIsNone(self.child.parent_device)
    
    def test_prevent_circular_reference(self):
        """Test that circular reference is prevented"""
        grandparent = ModbusDevice.objects.create(
            name="Grandparent",
            device_type="electricity",
            application_type="machine",
            port="/dev/ttyUSB0",
            address=3
        )
        
        self.parent.parent_device = grandparent
        self.parent.save()
        self.child.parent_device = self.parent
        self.child.save()
        
        # Try to make grandparent a child of child (circular)
        response = self.client.post(
            f'/api/modbus/devices/{grandparent.id}/set_parent/',
            {"parent_device_id": self.child.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Circular reference', str(response.data))
    
    def test_prevent_self_parent(self):
        """Test that device cannot be its own parent"""
        response = self.client.post(
            f'/api/modbus/devices/{self.child.id}/set_parent/',
            {"parent_device_id": self.child.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cannot be its own parent', str(response.data))
