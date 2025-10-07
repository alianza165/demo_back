# serializers.py
from rest_framework import serializers
from .models import DeviceModel, ModbusDevice, ModbusRegister, ConfigurationLog

class DeviceModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceModel
        fields = '__all__'

class ModbusRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModbusRegister
        fields = '__all__'
        extra_kwargs = {
            'device': {'required': False},
            'device_model': {'required': False}
        }

class ModbusDeviceSerializer(serializers.ModelSerializer):
    registers = ModbusRegisterSerializer(many=True, read_only=True)
    device_model_name = serializers.CharField(source='device_model.name', read_only=True)
    
    class Meta:
        model = ModbusDevice
        fields = '__all__'

class ModbusDeviceCreateSerializer(serializers.ModelSerializer):
    registers = ModbusRegisterSerializer(many=True, required=False)
    
    class Meta:
        model = ModbusDevice
        fields = '__all__'
    
    def create(self, validated_data):
        registers_data = validated_data.pop('registers', [])
        device = ModbusDevice.objects.create(**validated_data)
        
        for register_data in registers_data:
            register_data.pop('device', None)
            register_data.pop('device_model', None)
            ModbusRegister.objects.create(device=device, **register_data)
        
        return device
    
    def update(self, instance, validated_data):
        registers_data = validated_data.pop('registers', [])
        
        # Update device fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Only update registers if registers_data is provided
        if registers_data:
            # Get existing register IDs to track what should be deleted
            existing_register_ids = set(instance.registers.values_list('id', flat=True))
            updated_register_ids = set()
            
            # Update or create registers
            for register_data in registers_data:
                register_id = register_data.get('id')
                register_data.pop('device', None)
                register_data.pop('device_model', None)
                
                if register_id and instance.registers.filter(id=register_id).exists():
                    # Update existing register
                    register = instance.registers.get(id=register_id)
                    for attr, value in register_data.items():
                        setattr(register, attr, value)
                    register.save()
                    updated_register_ids.add(register_id)
                else:
                    # Create new register
                    register = ModbusRegister.objects.create(device=instance, **register_data)
                    updated_register_ids.add(register.id)
            
            # Delete registers that weren't included in the update
            registers_to_delete = existing_register_ids - updated_register_ids
            if registers_to_delete:
                instance.registers.filter(id__in=registers_to_delete).delete()
        
        return instance

class ConfigurationLogSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = ConfigurationLog
        fields = '__all__'
