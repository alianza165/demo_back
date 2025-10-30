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
        Also ensure register belongs to EITHER device_model OR device, not both
        """
        # Ensure register has exactly one parent (device_model OR device)
        device_model = attrs.get('device_model')
        device = attrs.get('device')
        
        # Check if both are set
        if device_model is not None and device is not None:
            raise serializers.ValidationError(
                "Register cannot belong to both device_model and device. "
                "It must belong to exactly one."
            )
        
        # Check if neither is set
        if device_model is None and device is None:
            raise serializers.ValidationError(
                "Register must belong to either a device_model (template) or a device (instance)."
            )
        
        # If this is part of a device update, skip the unique validation
        # The parent serializer will handle duplicate addresses
        if self.context.get('is_device_update', False):
            return attrs
        
        # Otherwise, run normal validation
        return super().validate(attrs)

class DeviceModelWithRegistersSerializer(serializers.ModelSerializer):
    """Serializer for DeviceModel that includes its register templates"""
    register_templates = ModbusRegisterSerializer(many=True, read_only=True)
    registers_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DeviceModel
        fields = [
            'id', 
            'name', 
            'description', 
            'manufacturer', 
            'model_number', 
            'is_active',
            'created_at',
            'register_templates',
            'registers_count'
        ]
    
    def get_registers_count(self, obj):
        """Get count of register templates for this device model"""
        return obj.register_templates.count()

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

    def create(self, validated_data):
        import logging
        logger = logging.getLogger('django.request')
        
        logger.error("=== CREATE METHOD CALLED ===")
        logger.error(f"Validated data keys: {validated_data.keys()}")
        
        registers_data = validated_data.pop('registers', [])
        logger.error(f"Number of registers to create: {len(registers_data)}")
        
        # Create the device first
        device = ModbusDevice.objects.create(**validated_data)
        
        # Create all registers for this device
        for i, register_data in enumerate(registers_data):
            logger.error(f"Creating register {i}: {register_data}")
            register_data.pop('device', None)
            register_data.pop('device_model', None)
            ModbusRegister.objects.create(device=device, **register_data)
        
        return device
    
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
