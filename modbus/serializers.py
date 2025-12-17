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
            'device': {'required': False, 'allow_null': True},
            'device_model': {'required': False, 'allow_null': True}
        }
    
    def validate(self, attrs):
        """
        Skip validations that require a concrete parent when nested under
        a device create/update. The parent serializer handles attachment
        and uniqueness in that flow.
        """
        # If nested under device create/update, bypass parent checks here
        if self.context.get('is_device_update', False):
            # Ensure device_model is None when nested (device will be set by parent)
            # Also ensure device is None as it will be set by parent serializer
            if 'device_model' not in attrs or attrs.get('device_model') is None:
                attrs['device_model'] = None
            if 'device' not in attrs or attrs.get('device') is None:
                attrs['device'] = None
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
    parent_device_name = serializers.CharField(source='parent_device.name', read_only=True)
    parent_device_id = serializers.IntegerField(source='parent_device.id', read_only=True)
    
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
        if 'registers' in self.fields:
            # Set context on the nested serializer field
            if hasattr(self.fields['registers'], 'child'):
                # Create a new child serializer with updated context
                child_class = self.fields['registers'].child.__class__
                child_context = self.fields['registers'].child.context.copy() if hasattr(self.fields['registers'].child, 'context') else {}
                child_context['is_device_update'] = True
                self.fields['registers'].child = child_class(context=child_context)

    def create(self, validated_data):
        import logging
        logger = logging.getLogger('django.request')
        
        logger.info("=== CREATE METHOD CALLED ===")
        logger.info(f"Validated data keys: {validated_data.keys()}")
        
        registers_data = validated_data.pop('registers', [])
        device_model = validated_data.get('device_model')
        
        logger.info(f"Number of registers to create: {len(registers_data)}")
        logger.info(f"Device model: {device_model}")
        
        # Create the device first
        device = ModbusDevice.objects.create(**validated_data)
        
        # If device_model is provided, copy its registers to the device
        if device_model:
            model_registers = ModbusRegister.objects.filter(
                device_model=device_model,
                is_active=True
            ).order_by('order', 'address')
            
            logger.info(f"Copying {model_registers.count()} registers from device model {device_model.name}")
            
            for model_register in model_registers:
                # Copy register from model to device instance
                ModbusRegister.objects.create(
                    device=device,
                    address=model_register.address,
                    name=model_register.name,
                    data_type=model_register.data_type,
                    scale_factor=model_register.scale_factor,
                    unit=model_register.unit,
                    order=model_register.order,
                    register_count=model_register.register_count,
                    word_order=model_register.word_order,
                    category=model_register.category,
                    visualization_type=model_register.visualization_type,
                    grafana_metric_name=model_register.grafana_metric_name,
                    influxdb_field_name=model_register.influxdb_field_name,
                    energy_measurement_field=model_register.energy_measurement_field,
                    is_active=model_register.is_active,
                )
        
        # Add any custom registers provided in the request
        # These will override any registers from the model if they have the same address
        for i, register_data in enumerate(registers_data):
            logger.info(f"Creating custom register {i}: {register_data}")
            register_data.pop('device', None)
            register_data.pop('device_model', None)
            address = register_data.get('address')
            defaults = {k: v for k, v in register_data.items() if k != 'address'}
            
            # Use update_or_create to handle both new and existing registers
            register, created = ModbusRegister.objects.update_or_create(
                device=device,
                address=address,
                defaults=defaults,
            )
            if created:
                logger.info(f"Created new register at address {address}")
            else:
                logger.info(f"Updated existing register at address {address}")
        
        return device
    
    def update(self, instance, validated_data):
        import logging
        logger = logging.getLogger('django.request')
        
        # Prevent changing device_model after creation
        if 'device_model' in validated_data:
            new_device_model = validated_data.get('device_model')
            if instance.device_model != new_device_model:
                if instance.device_model is not None:
                    raise serializers.ValidationError({
                        'device_model': 'Cannot change device_model after device creation. Device is already associated with a model.'
                    })
                # If device didn't have a model before, allow setting it once
                # But this is discouraged - model should be set at creation
                logger.warning(f"Device {instance.id} is being assigned a device_model during update. This should be done during creation.")
        
        # Prevent changing application_type between supply and load categories
        # But allow changes within the same category (e.g., gen -> wapda, or dept -> facility)
        if 'application_type' in validated_data:
            new_application_type = validated_data.get('application_type')
            old_application_type = instance.application_type
            
            # Define supply and load categories
            supply_types = ['gen', 'wapda', 'solar']
            load_types = ['dept', 'facility', 'process', 'machine']
            
            old_is_supply = old_application_type in supply_types
            old_is_load = old_application_type in load_types
            new_is_supply = new_application_type in supply_types
            new_is_load = new_application_type in load_types
            
            # Prevent changing from supply to load or vice versa
            if old_is_supply and new_is_load:
                raise serializers.ValidationError({
                    'application_type': 'Cannot change application_type from supply category (gen/wapda/solar) to load category (dept/facility/process/machine).'
                })
            if old_is_load and new_is_supply:
                raise serializers.ValidationError({
                    'application_type': 'Cannot change application_type from load category (dept/facility/process/machine) to supply category (gen/wapda/solar).'
                })
        
        registers_data = validated_data.pop('registers', None)
        
        # Update device fields (excluding device_model if it shouldn't change)
        for attr, value in validated_data.items():
            if attr != 'device_model' or instance.device_model is None:
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
                    # Update existing register (allows changing visualization_type and other fields)
                    for attr, value in register_data.items():
                        setattr(existing_register, attr, value)
                    existing_register.save()
                    updated_register_ids.add(existing_register.id)
                    logger.info(f"Updated existing register {existing_register.id} with address {register_data.get('address')}")
                else:
                    # Create new register
                    register = ModbusRegister.objects.create(device=instance, **register_data)
                    updated_register_ids.add(register.id)
                    logger.info(f"Created new register {register.id} with address {register_data.get('address')}")
            
            # Delete registers that weren't included in the update
            registers_to_delete = existing_register_ids - updated_register_ids
            if registers_to_delete:
                deleted_count = instance.registers.filter(id__in=registers_to_delete).delete()[0]
                logger.info(f"Deleted {deleted_count} registers")
        
        return instance
        

class ConfigurationLogSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = ConfigurationLog
        fields = '__all__'
