"""
Process mapping service to map devices to factory processes.
Since we only have 2 devices (flowmeter + electricity analyzer) but need to show
4 processes (Denim, Washing, Finishing, Sewing), we use intelligent mapping
and field categorization.
"""
from typing import Dict, List, Optional
from modbus.models import ModbusDevice


class ProcessMapper:
    """
    Maps devices and their fields to factory processes.
    """
    
    # Process names
    PROCESSES = ['denim', 'washing', 'finishing', 'sewing']
    
    # Device to process mapping (can be configured per installation)
    # Now uses department/process fields from ModbusDevice model
    @classmethod
    def _get_process_from_device(cls, device: ModbusDevice) -> Optional[str]:
        """Get process from device's process_area field, with fallback to name mapping."""
        # First check process_area field (this is the current field name)
        if hasattr(device, 'process_area') and device.process_area and device.process_area != 'general':
            return device.process_area.lower()
        # Fallback to name-based mapping
        return cls.DEVICE_PROCESS_MAP.get(device.name)
    
    DEVICE_PROCESS_MAP = {
        'Ombre Apparel Flow meter': 'denim',  # Default mapping (can be overridden by department/process fields)
        'Ombre Apparel LT-1 Main': 'denim',   # Main LT panel serves denim area
        '2-P Office DB': 'office',            # Office area
    }
    
    # Field name patterns to component mapping
    FIELD_TO_COMPONENT = {
        'light': 'lights',
        'l1 active power': 'machines',
        'l2 active power': 'machines',
        'l3 active power': 'machines',
        'active power': 'machines',
        'total active power': 'machines',
        'hvac': 'hvac',
        'cooling': 'hvac',
        'ac': 'hvac',
        'exhaust': 'exhaust_fan',
        'fan': 'exhaust_fan',
        'office': 'office',
        'laser': 'laser',
        'heat': 'machines',  # Steam heat for washing machines
        'instantaneous heat': 'machines',
        'total amount of heat': 'machines',
    }
    
    # Process component allocation (percentage breakdown for each process)
    # These are estimates based on typical textile factory operations
    PROCESS_COMPONENT_ALLOCATION = {
        'denim': {
            'machines': 0.54,
            'exhaust_fan': 0.30,
            'lights': 0.05,
            'hvac': 0.04,
            'office': 0.07,
        },
        'washing': {
            'machines': 0.77,
            'exhaust_fan': 0.12,
            'lights': 0.07,
            'laser': 0.04,
        },
        'finishing': {
            'machines': 0.06,
            'exhaust_fan': 0.20,
            'lights': 0.02,
            'hvac': 0.02,
            'office': 0.70,
        },
        'sewing': {
            'machines': 0.45,
            'exhaust_fan': 0.35,
            'lights': 0.07,
            'hvac': 0.05,
            'office': 0.08,
        },
    }
    
    @classmethod
    def get_process_for_device(cls, device: ModbusDevice) -> Optional[str]:
        """Get the primary process for a device."""
        return cls._get_process_from_device(device)
    
    @classmethod
    def identify_component(cls, field_name: str) -> Optional[str]:
        """Identify component from field name."""
        field_lower = field_name.lower()
        for pattern, component in cls.FIELD_TO_COMPONENT.items():
            if pattern in field_lower:
                return component
        return None
    
    @classmethod
    def allocate_to_processes(
        cls, 
        device: ModbusDevice, 
        total_energy: float,
        component_breakdown: Dict[str, float]
    ) -> Dict[str, Dict[str, float]]:
        """
        Allocate device energy to multiple processes.
        Returns dict: {process_name: {component: energy}}
        """
        primary_process = cls.get_process_for_device(device)
        
        if not primary_process or primary_process not in cls.PROCESSES:
            # If device doesn't map to a standard process, return empty
            return {}
        
        # Allocate total energy to processes based on device department/process
        # If device has a specific department/process, allocate 100% to that process
        if primary_process and primary_process in cls.PROCESSES:
            process_allocation = {primary_process: 1.0}
        elif device.device_type == 'electricity' and device.load_type == 'MAIN':
            # Main LT panels distribute across processes (60% denim, 25% washing, 10% finishing, 5% sewing)
            process_allocation = {
                'denim': 0.60,
                'washing': 0.25,
                'finishing': 0.10,
                'sewing': 0.05,
            }
        else:
            # Default: allocate to first available process or denim
            process_allocation = {'denim': 1.0}
        
        # Build breakdown by process
        result = {}
        for process, process_ratio in process_allocation.items():
            process_energy = total_energy * process_ratio
            process_breakdown = {}
            
            # Use predefined component allocation for each process
            if process in cls.PROCESS_COMPONENT_ALLOCATION:
                component_allocation = cls.PROCESS_COMPONENT_ALLOCATION[process]
                for component, component_ratio in component_allocation.items():
                    process_breakdown[component] = process_energy * component_ratio
            
            # If we have actual component breakdown, use it as a guide
            if component_breakdown:
                # Distribute actual components proportionally
                for component, value in component_breakdown.items():
                    if component in process_breakdown:
                        # Blend actual data with allocation
                        process_breakdown[component] = (
                            process_breakdown[component] * 0.5 + value * process_ratio * 0.5
                        )
            
            result[process] = process_breakdown
        
        return result
    
    @classmethod
    def get_all_process_breakdowns(
        cls,
        devices: List[ModbusDevice],
        aggregates: List
    ) -> Dict[str, Dict[str, float]]:
        """
        Get component breakdown for all processes from device aggregates.
        Returns: {process_name: {component: energy}}
        """
        all_process_breakdowns = {process: {} for process in cls.PROCESSES}
        
        # Create a mapping from device to aggregate
        device_to_aggregate = {}
        for agg in aggregates:
            if hasattr(agg, 'device') and agg.device:
                device_to_aggregate[agg.device.id] = agg
        
        # Process each device
        for device in devices:
            if device.id not in device_to_aggregate:
                continue
            
            agg = device_to_aggregate[device.id]
            total_energy = agg.total_energy_kwh if hasattr(agg, 'total_energy_kwh') else 0
            component_breakdown = agg.component_breakdown if hasattr(agg, 'component_breakdown') else {}
            
            # Allocate to processes
            process_allocations = cls.allocate_to_processes(
                device, total_energy, component_breakdown
            )
            
            # Merge into all_process_breakdowns
            for process, breakdown in process_allocations.items():
                if process in all_process_breakdowns:
                    for component, energy in breakdown.items():
                        all_process_breakdowns[process][component] = (
                            all_process_breakdowns[process].get(component, 0) + energy
                        )
        
        return all_process_breakdowns

