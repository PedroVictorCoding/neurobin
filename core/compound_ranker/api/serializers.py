from rest_framework import serializers
from compounds.models import Compound
from compound_ranker.models import ScoringCategory, CompoundScore, UserCompoundAnnotation


class ScoringCategorySerializer(serializers.ModelSerializer):
    compound_count = serializers.SerializerMethodField()
    avg_score = serializers.SerializerMethodField()

    class Meta:
        model = ScoringCategory
        fields = ['id', 'name', 'description', 'slug', 'icon', 'is_active', 
                 'compound_count', 'avg_score', 'created_at']

    def get_compound_count(self, obj):
        return obj.get_compound_count()

    def get_avg_score(self, obj):
        from django.db.models import Avg
        avg = CompoundScore.objects.filter(category=obj).aggregate(Avg('score'))['score__avg']
        return round(avg, 3) if avg else None


class CompoundBasicSerializer(serializers.ModelSerializer):
    """Lightweight compound serializer for nested use"""
    class Meta:
        model = Compound
        fields = ['id', 'name', 'chembl_id', 'slug', 'smiles']


class CompoundScoreSerializer(serializers.ModelSerializer):
    compound = CompoundBasicSerializer(read_only=True)
    category = ScoringCategorySerializer(read_only=True)
    rank_in_category = serializers.ReadOnlyField()
    score_percentage = serializers.ReadOnlyField()
    confidence_percentage = serializers.ReadOnlyField()

    class Meta:
        model = CompoundScore
        fields = ['id', 'compound', 'category', 'score', 'confidence', 
                 'model_version', 'rank_in_category', 'score_percentage', 
                 'confidence_percentage', 'timestamp', 'updated_at']


class CompoundScoreCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating compound scores"""
    class Meta:
        model = CompoundScore
        fields = ['compound', 'category', 'score', 'confidence', 'model_version', 'features_used']

    def validate_score(self, value):
        if not (0 <= value <= 1):
            raise serializers.ValidationError("Score must be between 0 and 1")
        return value

    def validate_confidence(self, value):
        if not (0 <= value <= 1):
            raise serializers.ValidationError("Confidence must be between 0 and 1")
        return value


class TopCompoundsSerializer(serializers.Serializer):
    """Serializer for top compounds response"""
    category = ScoringCategorySerializer()
    compounds = CompoundScoreSerializer(many=True)
    total_count = serializers.IntegerField()
    limit = serializers.IntegerField()


class UserCompoundAnnotationSerializer(serializers.ModelSerializer):
    compound = CompoundBasicSerializer(read_only=True)
    category = ScoringCategorySerializer(read_only=True)
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = UserCompoundAnnotation
        fields = ['id', 'compound', 'category', 'user', 'user_score', 'notes', 
                 'created_at', 'is_verified']


class UserCompoundAnnotationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating user annotations"""
    class Meta:
        model = UserCompoundAnnotation
        fields = ['compound', 'category', 'user_score', 'notes']

    def validate_user_score(self, value):
        if not (0 <= value <= 1):
            raise serializers.ValidationError("User score must be between 0 and 1")
        return value

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class CompoundRankingSerializer(serializers.Serializer):
    """Serializer for compound ranking across multiple categories"""
    compound = CompoundBasicSerializer()
    scores = CompoundScoreSerializer(many=True)
    overall_rank = serializers.FloatField()
    total_categories = serializers.IntegerField()
