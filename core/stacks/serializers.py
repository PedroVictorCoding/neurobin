from rest_framework import serializers
from .models import Stack, StackItem


class StackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stack
        fields = [
            'id',
            'user',
            'name',
            'description',
            'visibility',
            'is_active',
            'copied_from',
            'copied_at',
            'created',
        ]
        read_only_fields = ['user', 'copied_from', 'copied_at', 'created']


class PublicStackItemSerializer(serializers.ModelSerializer):
    compound_name = serializers.CharField(source='compound.name', read_only=True)

    class Meta:
        model = StackItem
        fields = [
            'id',
            'compound',
            'compound_name',
            'dosage_amount',
            'dosage_unit',
            'time_of_day',
            'intake_time',
            'recurrence_interval',
            'recurrence_unit',
            'order',
            'notes',
        ]


class PublicStackSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source='user.username', read_only=True)
    items = PublicStackItemSerializer(many=True, read_only=True)
    usage_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Stack
        fields = [
            'id',
            'owner_username',
            'name',
            'description',
            'visibility',
            'usage_count',
            'created',
            'items',
        ]


class StackItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StackItem
        fields = [
            'id', 'stack', 'compound', 'dosage_amount', 'dosage_unit', 'time_of_day', 'intake_time',
            'recurrence_interval', 'recurrence_unit', 'order', 'notes', 'completed', 'added'
        ]

    def validate_stack(self, stack):
        request = self.context.get('request')
        if request and stack.user_id != request.user.id:
            raise serializers.ValidationError("You can only add items to your own stacks.")
        return stack
