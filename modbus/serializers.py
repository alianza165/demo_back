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
    
    def validate(self, attrs):
        """
        Skip unique validation during updates when we're handling duplicates in the parent serializer
        """
        # If this is part of a device update, skip the unique validation
        # The parent serializer will handle duplicate addresses
        if self.context.get('is_device_update', False):
            return attrs
        
        # Otherwise, run normal validation
        return super().validate(attrs)

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
    
    def get_fields(self):
        fields = super().get_fields()
        # Add context to indicate this is a device update
        if hasattr(self, 'context') and self.context.get('request'):
            fields['registers'].context['is_device_update'] = True
        return fields
    
    def update(self, instance, validated_data):
        registers_data = validated_data.pop('registers', None)
        
        # Update device fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle registers update
        if registers_data is not None:
            existing_register_ids = set(instance.registers.values_list('id', flat=True))
            updated_register_ids = set()
            
            # Process each register in the request
            for register_data in registers_data:
                register_id = register_data.get('id')
                register_data.pop('device', None)
                register_data.pop('device_model', None)
                
                # Check if we should update existing register by address (not just ID)
                existing_register = None
                if register_id and instance.registers.filter(id=register_id).exists():
                    existing_register = instance.registers.get(id=register_id)
                else:
                    # Check if register with same address already exists
                    existing_register = instance.registers.filter(
                        address=register_data.get('address')
                    ).first()
                
                if existing_register:
                    # Update existing register
                    for attr, value in register_data.items():
                        setattr(existing_register, attr, value)
                    existing_register.save()
                    updated_register_ids.add(existing_register.id)
                    print(f"Updated existing register {existing_register.id} with address {register_data.get('address')}")
                else:
                    # Create new register
                    register = ModbusRegister.objects.create(device=instance, **register_data)
                    updated_register_ids.add(register.id)
                    print(f"Created new register {register.id} with address {register_data.get('address')}")
            
            # Delete registers that weren't included in the update
            registers_to_delete = existing_register_ids - updated_register_ids
            if registers_to_delete:
                deleted_count = instance.registers.filter(id__in=registers_to_delete).delete()
                print(f"Deleted {deleted_count} registers")
        
        return instance
        

class ConfigurationLogSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = ConfigurationLog
        fields = '__all__'
