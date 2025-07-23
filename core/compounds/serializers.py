from rest_framework import serializers
from .models import (
    CompoundCategories,
    Target,
    CompoundMechanismOfAction,
    Compound,
    CompoundRating,
    CompoundSafetyScreening
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
