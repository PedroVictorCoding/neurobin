from rest_framework import serializers
from .models import Compound


class CompoundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Compound
        fields = ['id', 'name', 'smiles']
