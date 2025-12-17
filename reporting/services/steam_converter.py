"""
Steam conversion service to convert steam volume (m³) to energy (kWh) and cost (PKR).
Based on coal consumption required to generate steam.
"""
from typing import Dict, Optional

# Conversion constants
# Typical values: 1 m³ of steam at 100°C requires approximately 0.064 kg of coal
# 1 kg coal ≈ 7 kWh of energy
# Steam density at 100°C: ~0.6 kg/m³

COAL_PER_CUBIC_METER_STEAM = 0.064  # kg coal per m³ steam
ENERGY_PER_KG_COAL = 7.0  # kWh per kg coal
ENERGY_PER_CUBIC_METER_STEAM = COAL_PER_CUBIC_METER_STEAM * ENERGY_PER_KG_COAL  # kWh per m³ steam

# Coal cost in PKR per kg (adjust based on current rates)
COAL_COST_PER_KG_PKR = 250.0  # PKR per kg coal
STEAM_COST_PER_CUBIC_METER_PKR = COAL_PER_CUBIC_METER_STEAM * COAL_COST_PER_KG_PKR  # PKR per m³ steam

# Electricity cost in PKR per kWh
ELECTRICITY_COST_PER_KWH_PKR = 35.0  # PKR per kWh (typical industrial rate)


class SteamConverter:
    """Convert steam volume measurements to energy and cost."""
    
    @staticmethod
    def cubic_meters_to_kwh(volume_m3: float) -> float:
        """
        Convert steam volume (m³) to equivalent energy (kWh).
        
        Args:
            volume_m3: Volume of steam in cubic meters
            
        Returns:
            Equivalent energy in kWh
        """
        return volume_m3 * ENERGY_PER_CUBIC_METER_STEAM
    
    @staticmethod
    def cubic_meters_to_cost_pkr(volume_m3: float) -> float:
        """
        Convert steam volume (m³) to cost in PKR based on coal consumption.
        
        Args:
            volume_m3: Volume of steam in cubic meters
            
        Returns:
            Cost in Pakistani Rupees
        """
        return volume_m3 * STEAM_COST_PER_CUBIC_METER_PKR
    
    @staticmethod
    def kwh_to_cost_pkr(kwh: float, is_electricity: bool = True) -> float:
        """
        Convert energy (kWh) to cost in PKR.
        
        Args:
            kwh: Energy in kWh
            is_electricity: True for electricity, False for steam (already converted)
            
        Returns:
            Cost in Pakistani Rupees
        """
        if is_electricity:
            return kwh * ELECTRICITY_COST_PER_KWH_PKR
        else:
            # Steam kWh equivalent (already includes coal cost)
            return kwh * (STEAM_COST_PER_CUBIC_METER_PKR / ENERGY_PER_CUBIC_METER_STEAM)
    
    @staticmethod
    def get_steam_energy_equivalent(volume_m3: float) -> Dict[str, float]:
        """
        Get energy equivalent and cost for steam volume.
        
        Args:
            volume_m3: Volume of steam in cubic meters
            
        Returns:
            Dictionary with 'kwh_equivalent', 'cost_pkr', and 'coal_kg'
        """
        coal_kg = volume_m3 * COAL_PER_CUBIC_METER_STEAM
        kwh_equivalent = coal_kg * ENERGY_PER_KG_COAL
        cost_pkr = coal_kg * COAL_COST_PER_KG_PKR
        
        return {
            'volume_m3': volume_m3,
            'coal_kg': coal_kg,
            'kwh_equivalent': kwh_equivalent,
            'cost_pkr': cost_pkr,
        }



