from rest_framework import serializers
from .models import IntakeLog
from compounds.serializers import CompoundSerializer


class IntakeLogSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    compound = CompoundSerializer(read_only=True)
    compound_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = IntakeLog
        fields = '__all__'
        read_only_fields = ('user',)

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
