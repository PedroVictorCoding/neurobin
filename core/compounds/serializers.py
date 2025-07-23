from rest_framework import serializers
from .models import (
    CompoundCategories,
    Target,
    CompoundMechanismOfAction,
    Compound,
    CompoundRating,
    CompoundSafetyScreening,
    EffectWindow
)


class CompoundCategoriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompoundCategories
        fields = '__all__'


class TargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Target
        fields = '__all__'


class CompoundMechanismOfActionSerializer(serializers.ModelSerializer):
    target_name = TargetSerializer(read_only=True)
    target_name_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    
    class Meta:
        model = CompoundMechanismOfAction
        fields = '__all__'

    def create(self, validated_data):
        target_name_id = validated_data.pop('target_name_id', None)
        instance = CompoundMechanismOfAction.objects.create(**validated_data)
        if target_name_id:
            instance.target_name_id = target_name_id
            instance.save()
        return instance

    def update(self, instance, validated_data):
        target_name_id = validated_data.pop('target_name_id', None)
        if target_name_id is not None:
            instance.target_name_id = target_name_id
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class CompoundSerializer(serializers.ModelSerializer):
    categories = CompoundCategoriesSerializer(many=True, read_only=True)
    mechanism_of_action = CompoundMechanismOfActionSerializer(many=True, read_only=True)
    categories_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    mechanism_of_action_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = Compound
        fields = '__all__'
        read_only_fields = ('slug',)

    def create(self, validated_data):
        categories_ids = validated_data.pop('categories_ids', [])
        mechanism_ids = validated_data.pop('mechanism_of_action_ids', [])
        
        compound = Compound.objects.create(**validated_data)
        
        if categories_ids:
            compound.categories.set(categories_ids)
        if mechanism_ids:
            compound.mechanism_of_action.set(mechanism_ids)
            
        return compound

    def update(self, instance, validated_data):
        categories_ids = validated_data.pop('categories_ids', None)
        mechanism_ids = validated_data.pop('mechanism_of_action_ids', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if categories_ids is not None:
            instance.categories.set(categories_ids)
        if mechanism_ids is not None:
            instance.mechanism_of_action.set(mechanism_ids)
            
        return instance


class CompoundRatingSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    compound = CompoundSerializer(read_only=True)
    compound_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = CompoundRating
        fields = '__all__'
        read_only_fields = ('user', 'created_at')

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class CompoundSafetyScreeningSerializer(serializers.ModelSerializer):
    compound = CompoundSerializer(read_only=True)
    compound_id = serializers.IntegerField(write_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    
    class Meta:
        model = CompoundSafetyScreening
        fields = '__all__'
        read_only_fields = ('created_at', 'created_by')

    def create(self, validated_data):
        if self.context['request'].user.is_authenticated:
            validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class EffectWindowSerializer(serializers.ModelSerializer):
    compound = CompoundSerializer(read_only=True)
    compound_id = serializers.IntegerField(write_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    peak_duration_minutes = serializers.ReadOnlyField()
    comedown_minutes = serializers.ReadOnlyField()
    effect_curve_data = serializers.SerializerMethodField()
    
    class Meta:
        model = EffectWindow
        fields = '__all__'
        read_only_fields = ('created_at', 'created_by')

    def get_effect_curve_data(self, obj):
        """Get curve data points for visualization"""
        return obj.get_effect_curve_data()

    def create(self, validated_data):
        if self.context['request'].user.is_authenticated:
            validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)

    def validate(self, data):
        """Validate timing constraints"""
        onset = data.get('onset_minutes', 0)
        peak_min = data.get('peak_min_minutes', 0)
        peak_max = data.get('peak_max_minutes', 0)
        duration = data.get('duration_minutes', 0)
        
        if peak_min < onset:
            raise serializers.ValidationError("Peak minimum cannot be before onset")
        
        if peak_max < peak_min:
            raise serializers.ValidationError("Peak maximum cannot be before peak minimum")
        
        if duration < peak_max:
            raise serializers.ValidationError("Duration cannot be shorter than peak maximum")
        
        return data
