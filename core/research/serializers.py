from rest_framework import serializers
from .models import (
    ResearchSnippet,
    SnippetReview,
    SnippetTag,
    SnippetTagging,
    UserRole,
    ResearchSettings,
    SnippetComment
)
from compounds.serializers import CompoundSerializer


class SnippetTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = SnippetTag
        fields = '__all__'


class SnippetTaggingSerializer(serializers.ModelSerializer):
    tag = SnippetTagSerializer(read_only=True)
    tag_id = serializers.IntegerField(write_only=True)
    tagged_by = serializers.StringRelatedField(read_only=True)
    
    class Meta:
        model = SnippetTagging
        fields = '__all__'
        read_only_fields = ('tagged_by', 'created_at')

    def create(self, validated_data):
        if self.context.get('request') and self.context['request'].user.is_authenticated:
            validated_data['tagged_by'] = self.context['request'].user
        return super().create(validated_data)


class SnippetReviewSerializer(serializers.ModelSerializer):
    reviewer = serializers.StringRelatedField(read_only=True)
    snippet_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = SnippetReview
        fields = '__all__'
        read_only_fields = ('reviewer', 'created_at')

    def create(self, validated_data):
        validated_data['reviewer'] = self.context['request'].user
        return super().create(validated_data)


class SnippetCommentSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField(read_only=True)
    snippet_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = SnippetComment
        fields = '__all__'
        read_only_fields = ('author', 'created_at', 'updated_at')

    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)


class ResearchSnippetSerializer(serializers.ModelSerializer):
    compound = CompoundSerializer(read_only=True)
    compound_id = serializers.IntegerField(write_only=True)
    created_by = serializers.StringRelatedField(read_only=True)
    tags = SnippetTagSerializer(many=True, read_only=True)
    reviews = SnippetReviewSerializer(many=True, read_only=True)
    comments = SnippetCommentSerializer(many=True, read_only=True)
    net_score = serializers.ReadOnlyField()
    confidence_level = serializers.ReadOnlyField()
    confidence_color = serializers.ReadOnlyField()
    
    class Meta:
        model = ResearchSnippet
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'view_count')

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class UserRoleSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    
    class Meta:
        model = UserRole
        fields = '__all__'
        read_only_fields = ('created_at',)

    def create(self, validated_data):
        user_id = validated_data.pop('user_id', None)
        if user_id:
            validated_data['user_id'] = user_id
        elif self.context.get('request') and self.context['request'].user.is_authenticated:
            validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class ResearchSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchSettings
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')
