#!/usr/bin/env python3
"""
MODBUS MONITOR - IMPROVED VERSION
Handles multiple data types (uint16, int16, uint32, int32, float32)
Created based on your original modbus_monitor.py
"""

from pymodbus.client import ModbusSerialClient
from influxdb_client import InfluxDBClient, Point
import time
import logging
import json
import os
import glob
import subprocess
import sys
from pathlib import Path
from struct import pack, unpack

def find_available_usb_ports():
    """Find all available USB serial ports with better detection"""
    all_ports = []
    for pattern in ['/dev/ttyUSB*', '/dev/ttyACM*']:
        all_ports.extend(glob.glob(pattern))
    return sorted(all_ports)

# Configure logging
BASE_DIR = Path('/opt/modbus_monitor')
LOG_DIR = Path('/var/log/modbus_monitor')
LOG_FILE = LOG_DIR / 'modbus_monitor.log'

BASE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class RegisterReader:
    """Handles reading different Modbus register data types"""
    
    @staticmethod
    def get_register_count(data_type):
        """Get number of registers needed for a data type"""
        type_map = {
            'uint16': 1, 'int16': 1,
            'uint32': 2, 'int32': 2, 'float32': 2
        }
        return type_map.get(data_type.lower(), 1)
    
    @staticmethod
    def decode_value(raw_registers, data_type, scale_factor):
        """
        Decode raw Modbus registers based on data type and apply scaling
        Args:
            raw_registers: List of raw register values (1 or 2 values)
            data_type: 'uint16', 'int16', 'uint32', 'int32', 'float32'
            scale_factor: Scaling factor to apply
        Returns:
            Scaled float value
        """
        try:
            data_type = data_type.lower()
            
            if data_type in ['uint16', 'int16']:
                # Single register
                if data_type == 'int16':
                    # Signed 16-bit
                    value = unpack('>h', pack('>H', raw_registers[0]))[0]
                else:
                    # Unsigned 16-bit
                    value = raw_registers[0]
                
                return float(value) / scale_factor
            
            elif data_type in ['uint32', 'int32', 'float32']:
                # Two registers (high word, low word)
                if len(raw_registers) < 2:
                    logger.error(f"Insufficient registers for {data_type}: got {len(raw_registers)}")
                    return 0.0
                
                if data_type == 'uint32':
                    # Unsigned 32-bit (high register, low register)
                    value = (raw_registers[0] << 16) | raw_registers[1]
                    return float(value) / scale_factor
                
                elif data_type == 'int32':
                    # Signed 32-bit
                    raw_value = (raw_registers[0] << 16) | raw_registers[1]
                    # Handle sign extension
                    if raw_value & 0x80000000:
                        raw_value = raw_value - 0x100000000
                    return float(raw_value) / scale_factor
                
                elif data_type == 'float32':
                    # IEEE 754 32-bit float
                    high, low = raw_registers[0], raw_registers[1]
                    # Pack as 32-bit float (big-endian)
                    float_bytes = pack('>HH', high, low)
                    value = unpack('>f', float_bytes)[0]
                    return float(value) / scale_factor
            
            else:
                logger.warning(f"Unknown data type: {data_type}, treating as uint16")
                return float(raw_registers[0]) / scale_factor
                
        except Exception as e:
            logger.error(f"Error decoding value: {e}")
            return 0.0


class DeviceMonitor:
    """Represents a single Modbus device"""
    def __init__(self, device_id, config_data):
        self.device_id = device_id
        self.name = config_data.get('name', f'device_{device_id}')
        self.slave_id = config_data.get('slave_id', 1)
        
        # Parse parameters - handle both 3-tuple and 4-tuple formats
        params = config_data.get('parameters', {})
        self.parameters = {}
        for addr_str, param_data in params.items():
            address = int(addr_str)
            
            if len(param_data) == 4:
                # New format: (name, scale, unit, data_type)
                field_name, scaling, units, data_type = param_data
            elif len(param_data) == 3:
                # Old format: (name, scale, unit) - assume uint16
                field_name, scaling, units = param_data
                data_type = 'uint16'
            else:
                logger.warning(f"Invalid parameter format for address {address}: {param_data}")
                continue
            
            self.parameters[address] = {
                'name': field_name,
                'scale': float(scaling),
                'unit': units,
                'data_type': data_type
            }
        
    def __str__(self):
        return f"{self.name} (slave {self.slave_id})"


class SimpleModbusMonitor:
    def __init__(self, config_path='/etc/modbus_monitor/config.json'):
        self.config_path = config_path
        self.modbus_client = None
        self.influx_client = None
        self.write_api = None
        self.devices = []
        self.modbus_config = {}
        self.load_config()
        self.config_last_modified = 0
        self.register_reader = RegisterReader()
        
    def check_config_changed(self):
        """Simple config change detection"""
        try:
            current_mtime = os.path.getmtime('/etc/modbus_monitor/config.json')
            if current_mtime > self.config_last_modified:
                logger.info("Config file changed - reloading...")
                self.config_last_modified = current_mtime
                self.load_config()
                return True
        except Exception as e:
            logger.error(f"Error checking config: {e}")
        return False

    def load_config(self):
        """Load configuration with automatic USB port detection"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Get modbus config
            self.modbus_config = config.get('global_config', {
                'port': '/dev/ttyUSB0',
                'baudrate': 9600,
                'stopbits': 1,
                'bytesize': 8,
                'parity': 'N',
                'timeout': 3
            })
            
            # Auto-detect USB port if configured port doesn't exist
            configured_port = self.modbus_config.get('port', '/dev/ttyUSB0')
            if not os.path.exists(configured_port):
                available_ports = find_available_usb_ports()
                if available_ports:
                    self.modbus_config['port'] = available_ports[0]
                    logger.info(f"Auto-switched to USB port: {self.modbus_config['port']}")
                else:
                    logger.error("No USB serial ports found!")
            
            # Load devices
            self.devices = []
            if config.get('devices'):
                for device_id, device_config in config['devices'].items():
                    device = DeviceMonitor(device_id, device_config)
                    self.devices.append(device)
                    logger.info(f"Loaded device: {device.name} (slave {device.slave_id}) "
                              f"with {len(device.parameters)} parameters")
            else:
                # Fallback for old config format
                device = DeviceMonitor('device_1', config)
                self.devices.append(device)
                logger.info(f"Loaded single device: {device.name}")
            
            logger.info(f"Total devices configured: {len(self.devices)}")
            
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self.setup_fallback_config()
    
    def setup_fallback_config(self):
        """Fallback configuration if config file is missing"""
        self.modbus_config = {
            'port': '/dev/ttyUSB0',
            'baudrate': 9600,
            'stopbits': 1,
            'bytesize': 8,
            'parity': 'N',
            'timeout': 3
        }
        
        # Create a fallback device
        device = DeviceMonitor('fallback_device', {
            'name': 'Fallback Device',
            'slave_id': 1,
            'parameters': {
                778: ['voltage_v12', 10.0, 'V', 'uint16'],
                782: ['voltage_v1n', 10.0, 'V', 'uint16']
            }
        })
        self.devices = [device]
        logger.info("Using fallback configuration")
    
    def initialize_clients(self):
        """Initialize modbus and influxdb clients"""
        try:
            # Initialize Modbus client (single client for all devices)
            self.modbus_client = ModbusSerialClient(**self.modbus_config)
            
            # Initialize InfluxDB client
            self.influx_client = InfluxDBClient(
                url='http://localhost:8086',
                token='PQF2DMjfNtn__ooeubqDTUaiXegywYbzUBNyTjpvd7qoUrmq9PpGVyS8lybnmf-sszI7V1HEwZWdSvgkEGfzcQ==',
                org='DATABRIDGE'
            )
            self.write_api = self.influx_client.write_api()
            
            logger.info("Clients initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing clients: {e}")
            return False
    
    def connect_modbus(self):
        """Connect to modbus device with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if self.modbus_client.connect():
                    logger.info(f"Connected to Modbus on {self.modbus_config['port']}")
                    return True
                else:
                    logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed")
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Connection error on attempt {attempt + 1}: {e}")
                time.sleep(2)
        
        logger.error(f"Failed to connect after {max_retries} attempts")
        return False
    
    def convert_modbus_address(self, address):
        """
        Convert Modbus notation address to protocol address.
        Modbus notation: 40001-49999 are holding registers
        Protocol: 0-based addressing (40001 -> 0, 40003 -> 2, etc.)
        """
        # If address is in Modbus notation range (40001-49999), convert to 0-based
        if 40001 <= address <= 49999:
            return address - 40001
        # Otherwise, assume it's already in protocol format
        return address
    
    def read_device_parameters(self, device):
        """Read all parameters for a specific device with proper data type handling"""
        data_points = {}
        successful_reads = 0
        failed_reads = 0
        
        for address, param_info in device.parameters.items():
            field_name = param_info['name']
            data_type = param_info['data_type']
            scale_factor = param_info['scale']
            
            try:
                # Convert Modbus notation address to protocol address
                protocol_address = self.convert_modbus_address(address)
                
                # Get number of registers to read based on data type
                register_count = self.register_reader.get_register_count(data_type)
                
                response = self.modbus_client.read_holding_registers(
                    address=protocol_address, 
                    count=register_count,
                    slave=device.slave_id
                )
                
                if response.isError():
                    logger.error(f"Error reading {field_name} from {device.name} "
                               f"(slave {device.slave_id}): {response}")
                    failed_reads += 1
                    continue
                    
                # Decode the value based on data type
                raw_value = response.registers
                scaled_value = self.register_reader.decode_value(
                    raw_value, data_type, scale_factor
                )
                
                data_points[field_name] = scaled_value
                successful_reads += 1
                
                logger.debug(f"{device.name} - {field_name}: {scaled_value} "
                           f"{param_info['unit']} (type: {data_type})")
                
            except Exception as e:
                logger.error(f"Exception reading {field_name} from {device.name}: {e}")
                failed_reads += 1
            
            # Small delay between reads to avoid overwhelming the device
            time.sleep(0.05)
        
        logger.info(f"{device.name}: Read {successful_reads}/{len(device.parameters)} "
                   f"parameters successfully ({failed_reads} failed)")
        return data_points
    
    def write_to_influxdb(self, device_name, data_points):
        """Write device data to InfluxDB"""
        if not self.influx_client or not self.write_api:
            logger.warning("InfluxDB client not available")
            return False
            
        try:
            point = Point("energy_measurements") \
                .tag("device_id", device_name) \
                .tag("location", "electrical_room")
            
            for field_name, value in data_points.items():
                point = point.field(field_name, float(value))
            
            point = point.time(time.time_ns())
            self.write_api.write(bucket="databridge", record=point)
            
            logger.debug(f"Written {len(data_points)} measurements for {device_name} to InfluxDB")
            return True
            
        except Exception as e:
            logger.error(f"Error writing to InfluxDB for {device_name}: {e}")
            return False
    
    def monitor_devices(self):
        """Monitor all devices in sequence"""
        total_successful_reads = 0
        
        for device in self.devices:
            try:
                logger.info(f"Reading from {device.name} (slave {device.slave_id})")
                
                data_points = self.read_device_parameters(device)
                
                if data_points:
                    # Write to InfluxDB
                    if self.write_to_influxdb(device.name, data_points):
                        total_successful_reads += 1
                    
                    # Log summary for this device
                    voltage_keys = [k for k in data_points.keys() if 'voltage' in k.lower()]
                    power_keys = [k for k in data_points.keys() if 'power' in k.lower()]
                    
                    # Show voltage or power summary
                    if voltage_keys:
                        first_voltage = voltage_keys[0]
                        logger.info(f"{device.name}: {data_points[first_voltage]:.1f}V")
                    elif power_keys and 'total' in str(power_keys):
                        total_power = next(k for k in power_keys if 'total' in k)
                        logger.info(f"{device.name}: {data_points[total_power]:.2f}kW")
                
                # Brief pause between devices
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error monitoring {device.name}: {e}")
        
        return total_successful_reads
    
    def run(self):
        """Main monitoring loop"""
        logger.info(f"Starting Modbus monitor for {len(self.devices)} devices")
        
        if not self.initialize_clients():
            logger.error("Failed to initialize clients")
            return
        
        consecutive_failures = 0
        max_consecutive_failures = 5
        
        try:
            while True:
                # Check connection
                if not self.modbus_client.connected:
                    logger.info("Attempting to connect to Modbus device...")
                    if not self.connect_modbus():
                        consecutive_failures += 1
                        logger.warning(f"Connection failed ({consecutive_failures}/{max_consecutive_failures})")
                        
                        if consecutive_failures >= max_consecutive_failures:
                            logger.error("Too many consecutive failures, waiting before retry...")
                            time.sleep(30)
                            consecutive_failures = 0
                        else:
                            time.sleep(10)
                        continue
                
                # Reset failure counter on successful connection
                consecutive_failures = 0
                
                # Monitor all devices
                successful_devices = self.monitor_devices()
                
                if successful_devices > 0:
                    logger.info(f"Successfully monitored {successful_devices}/{len(self.devices)} devices")
                else:
                    logger.warning("No successful device readings this cycle")
                
                # Wait before next cycle
                self.check_config_changed()
                time.sleep(10)
                
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up resources...")
        try:
            if self.modbus_client:
                self.modbus_client.close()
                logger.info("Modbus client closed")
        except:
            pass
        
        try:
            if self.influx_client:
                self.influx_client.close()
                logger.info("InfluxDB client closed")
        except:
            pass


def main():
    """Main function"""
    try:
        monitor = SimpleModbusMonitor()
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

