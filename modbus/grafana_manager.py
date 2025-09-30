import requests
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class GrafanaConfigurationManager:
    def __init__(self):
        self.grafana_url = settings.GRAFANA_CONFIG['URL']
        self.api_key = settings.GRAFANA_CONFIG['API_KEY']
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def ensure_datasource_exists(self):
        """Ensure InfluxDB datasource exists in Grafana"""
        try:
            datasource_name = "influxdb"
            datasource_url = f"{self.grafana_url}/api/datasources"
            
            # Check if datasource exists
            response = requests.get(datasource_url, headers=self.headers)
            if response.status_code == 200:
                datasources = response.json()
                for ds in datasources:
                    if ds['name'] == datasource_name:
                        logger.info(f"Datasource {datasource_name} already exists")
                        return True
            
            # Create datasource if it doesn't exist
            datasource_config = {
                "name": datasource_name,
                "type": "influxdb",
                "url": "http://localhost:8086",
                "access": "proxy",
                "database": "databridge",
                "isDefault": True
            }
            
            response = requests.post(datasource_url, headers=self.headers, json=datasource_config)
            if response.status_code == 200:
                logger.info(f"Created datasource: {datasource_name}")
                return True
            else:
                logger.error(f"Failed to create datasource: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error ensuring datasource: {e}")
            return False
    
    def create_or_update_device_dashboard(self, device):
        """Create or update dashboard for a specific device"""
        try:
            dashboard_uid = f"energy-{device.name.lower().replace(' ', '-')}"
            dashboard_url = f"{self.grafana_url}/api/dashboards/uid/{dashboard_uid}"
            
            # Check if dashboard exists
            response = requests.get(dashboard_url, headers=self.headers)
            dashboard_exists = response.status_code == 200
            
            # Generate dashboard JSON
            dashboard_json = self.generate_dashboard_json(device, dashboard_uid)
            
            # Create or update dashboard
            api_url = f"{self.grafana_url}/api/dashboards/db"
            response = requests.post(api_url, headers=self.headers, json=dashboard_json)
            
            if response.status_code == 200:
                result = response.json()
                full_url = f"{self.grafana_url}{result['url']}"
                logger.info(f"{'Updated' if dashboard_exists else 'Created'} dashboard for {device.name}")
                return True, full_url
            else:
                logger.error(f"Failed to create dashboard: {response.text}")
                return False, response.text
                
        except Exception as e:
            logger.error(f"Error creating dashboard for {device.name}: {e}")
            return False, str(e)
    
    def generate_dashboard_json(self, device, dashboard_uid):
        """Generate dashboard JSON based on device registers"""
        panels = []
        panel_id = 1
        
        # Map register names to actual field names in InfluxDB
        field_mapping = self.get_field_mapping(device)
        
        for i, (register_name, field_name) in enumerate(field_mapping.items()):
            # Calculate grid position (2 panels per row)
            x_pos = (i % 2) * 12
            y_pos = (i // 2) * 8
            
            # Get register for unit information
            register = device.registers.filter(name=register_name, is_active=True).first()
            unit = register.unit if register else "short"
            
            # Create a panel for each register
            panel = {
                "id": panel_id,
                "title": f"{register_name}",
                "type": "timeseries",
                "gridPos": {
                    "h": 8,
                    "w": 12,
                    "x": x_pos,
                    "y": y_pos
                },
                "targets": [
                    {
                        "query": f'''
                            from(bucket: "databridge")
                              |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
                              |> filter(fn: (r) => r["_measurement"] == "energy_measurements")
                              |> filter(fn: (r) => r["_field"] == "{field_name}")
                              |> filter(fn: (r) => r["device_id"] == "{device.name}")
                              |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
                              |> yield(name: "mean")
                        ''',
                        "rawQuery": True,
                        "resultFormat": "time_series"
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": unit,
                        "color": {"mode": "palette-classic"},
                        "custom": {
                            "drawStyle": "line",
                            "lineInterpolation": "linear",
                            "barAlignment": 0,
                            "lineWidth": 1,
                            "fillOpacity": 10,
                            "gradientMode": "none",
                            "spanNulls": False,
                            "showPoints": "auto",
                            "pointSize": 5
                        }
                    }
                }
            }
            panels.append(panel)
            panel_id += 1
        
        return {
            "dashboard": {
                "uid": dashboard_uid,
                "title": f"Energy Monitor - {device.name}",
                "tags": ["energy", "modbus", device.name],
                "timezone": "browser",
                "panels": panels,
                "time": {"from": "now-1h", "to": "now"},
                "refresh": "30s"
            },
            "overwrite": True
        }
    
    def get_field_mapping(self, device):
        """Map register names to actual InfluxDB field names"""
        field_mapping = {}
        
        for register in device.registers.filter(is_active=True):
            if hasattr(register, 'influxdb_field_name') and register.influxdb_field_name:
                field_mapping[register.name] = register.influxdb_field_name
            else:
                field_mapping[register.name] = register.name
        
        return field_mapping
    
    def update_device_dashboards(self, devices):
        """Update dashboards for multiple devices"""
        try:
            # Ensure datasource exists first
            if not self.ensure_datasource_exists():
                return False, "Failed to ensure datasource exists"
            
            dashboard_urls = {}
            all_success = True
            error_messages = []
            
            for device in devices:
                success, result = self.create_or_update_device_dashboard(device)
                if success:
                    dashboard_urls[device.id] = result
                else:
                    all_success = False
                    error_messages.append(f"{device.name}: {result}")
                    dashboard_urls[device.id] = None
            
            if all_success:
                return True, dashboard_urls
            else:
                return False, "; ".join(error_messages)
                
        except Exception as e:
            logger.error(f"Error updating device dashboards: {e}")
            return False, str(e)
