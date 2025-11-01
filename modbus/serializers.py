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
        Skip validations that require a concrete parent when nested under
        a device create/update. The parent serializer handles attachment
        and uniqueness in that flow.
        """
        # If nested under device create/update, bypass parent checks here
        if self.context.get('is_device_update', False):
            return attrs
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
        
        # Enforce uniqueness of address per parent when creating/updating directly
        address = attrs.get('address')
        if address is not None:
            if device is not None:
                qs = ModbusRegister.objects.filter(device=device, address=address)
            else:
                qs = ModbusRegister.objects.filter(device_model=device_model, address=address)
            if self.instance:
                qs = qs.exclude(id=self.instance.id)
            if qs.exists():
                raise serializers.ValidationError(
                    { 'address': 'A register with this address already exists for this parent.' }
                )
        
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
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure nested registers serializer knows it's under a device create/update
        if 'registers' in self.fields and hasattr(self.fields['registers'], 'child'):
            self.fields['registers'].child.context.update({
                'is_device_update': True
            })

    def create(self, validated_data):
        import logging
        logger = logging.getLogger('django.request')
        
        logger.error("=== CREATE METHOD CALLED ===")
        logger.error(f"Validated data keys: {validated_data.keys()}")
        
        registers_data = validated_data.pop('registers', [])
        logger.error(f"Number of registers to create: {len(registers_data)}")
        
        # Create the device first
        device = ModbusDevice.objects.create(**validated_data)
        
        # Create all registers for this device with idempotency by address
        for i, register_data in enumerate(registers_data):
            logger.error(f"Creating register {i}: {register_data}")
            register_data.pop('device', None)
            register_data.pop('device_model', None)
            address = register_data.get('address')
            defaults = {k: v for k, v in register_data.items() if k != 'address'}
            register, created = ModbusRegister.objects.get_or_create(
                device=device,
                address=address,
                defaults=defaults,
            )
            if not created:
                # Update existing register to match provided data
                for attr, value in defaults.items():
                    setattr(register, attr, value)
                register.save()
        
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
