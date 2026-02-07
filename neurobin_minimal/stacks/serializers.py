from rest_framework import serializers
from .models import Stack, StackItem


class StackItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StackItem
        fields = ['id', 'stack', 'compound_name', 'dosage_amount', 'intake_time', 'notes']


class StackSerializer(serializers.ModelSerializer):
    items = StackItemSerializer(many=True, read_only=True)

    class Meta:
        model = Stack
        fields = ['id', 'name', 'items']
