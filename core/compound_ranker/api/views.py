from rest_framework import generics, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly

# Try to import django_filters, gracefully handle if not available
try:
    from django_filters.rest_framework import DjangoFilterBackend
    DJANGO_FILTERS_AVAILABLE = True
except ImportError:
    # Create a dummy class to prevent errors
    class DjangoFilterBackend:
        pass
    DJANGO_FILTERS_AVAILABLE = False

from django.db.models import Q, Avg, Count
from django.shortcuts import get_object_or_404

from compound_ranker.models import ScoringCategory, CompoundScore, UserCompoundAnnotation
from compounds.models import Compound
from .serializers import (
    ScoringCategorySerializer,
    CompoundScoreSerializer,
    CompoundScoreCreateSerializer,
    TopCompoundsSerializer,
    UserCompoundAnnotationSerializer,
    UserCompoundAnnotationCreateSerializer,
    CompoundRankingSerializer
)


class ScoringCategoryListView(generics.ListCreateAPIView):
    """List all scoring categories or create a new one"""
    queryset = ScoringCategory.objects.filter(is_active=True)
    serializer_class = ScoringCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']


class ScoringCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a scoring category"""
    queryset = ScoringCategory.objects.all()
    serializer_class = ScoringCategorySerializer
    lookup_field = 'slug'


class CompoundScoreListView(generics.ListCreateAPIView):
    """List compound scores with filtering"""
    queryset = CompoundScore.objects.select_related('compound', 'category')
    
    # Only include DjangoFilterBackend if available
    if DJANGO_FILTERS_AVAILABLE:
        filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
        filterset_fields = ['category__slug', 'model_version']
    else:
        filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    
    search_fields = ['compound__name', 'compound__chembl_id']
    ordering_fields = ['score', 'confidence', 'timestamp']
    ordering = ['-score']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CompoundScoreCreateSerializer
        return CompoundScoreSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by compound if specified
        compound_id = self.request.query_params.get('compound', None)
        if compound_id:
            queryset = queryset.filter(compound_id=compound_id)
        
        # Filter by score range
        min_score = self.request.query_params.get('min_score', None)
        max_score = self.request.query_params.get('max_score', None)
        if min_score:
            try:
                queryset = queryset.filter(score__gte=float(min_score))
            except ValueError:
                pass
        if max_score:
            try:
                queryset = queryset.filter(score__lte=float(max_score))
            except ValueError:
                pass
        
        # Filter by confidence range
        min_confidence = self.request.query_params.get('min_confidence', None)
        if min_confidence:
            try:
                queryset = queryset.filter(confidence__gte=float(min_confidence))
            except ValueError:
                pass
        
        return queryset


class CompoundScoreDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a compound score"""
    queryset = CompoundScore.objects.select_related('compound', 'category')
    serializer_class = CompoundScoreSerializer


@api_view(['GET'])
def top_compounds_view(request):
    """Get top N compounds for a specific category"""
    category_slug = request.query_params.get('category')
    if not category_slug:
        return Response({'error': 'category parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        limit = int(request.query_params.get('n', 10))
        limit = min(limit, 100)  # Max 100 compounds
    except ValueError:
        limit = 10
    
    category = get_object_or_404(ScoringCategory, slug=category_slug, is_active=True)
    
    top_scores = CompoundScore.objects.filter(
        category=category
    ).select_related('compound').order_by('-score')[:limit]
    
    total_count = CompoundScore.objects.filter(category=category).count()
    
    response_data = {
        'category': ScoringCategorySerializer(category).data,
        'compounds': CompoundScoreSerializer(top_scores, many=True).data,
        'total_count': total_count,
        'limit': limit
    }
    
    return Response(response_data)


@api_view(['GET'])
def compound_rankings_view(request, compound_id):
    """Get compound rankings across all categories"""
    compound = get_object_or_404(Compound, id=compound_id)
    
    scores = CompoundScore.objects.filter(
        compound=compound
    ).select_related('category').order_by('-score')
    
    # Calculate overall ranking (average of normalized ranks)
    total_categories = scores.count()
    if total_categories > 0:
        rank_sum = 0
        for score in scores:
            total_in_category = CompoundScore.objects.filter(category=score.category).count()
            normalized_rank = score.rank_in_category / total_in_category
            rank_sum += normalized_rank
        overall_rank = rank_sum / total_categories
    else:
        overall_rank = 0
    
    from .serializers import CompoundBasicSerializer
    response_data = {
        'compound': CompoundBasicSerializer(compound).data,
        'scores': CompoundScoreSerializer(scores, many=True).data,
        'overall_rank': overall_rank,
        'total_categories': total_categories
    }
    
    return Response(response_data)


class UserAnnotationListView(generics.ListCreateAPIView):
    """List user annotations or create a new one"""
    permission_classes = [IsAuthenticated]
    
    # Only include DjangoFilterBackend if available
    if DJANGO_FILTERS_AVAILABLE:
        filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
        filterset_fields = ['category__slug', 'compound__id', 'is_verified']
    else:
        filter_backends = [filters.OrderingFilter]
    
    ordering_fields = ['created_at', 'user_score']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return UserCompoundAnnotationCreateSerializer
        return UserCompoundAnnotationSerializer

    def get_queryset(self):
        return UserCompoundAnnotation.objects.filter(
            user=self.request.user
        ).select_related('compound', 'category')


class UserAnnotationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a user annotation"""
    permission_classes = [IsAuthenticated]
    serializer_class = UserCompoundAnnotationSerializer

    def get_queryset(self):
        return UserCompoundAnnotation.objects.filter(
            user=self.request.user
        ).select_related('compound', 'category')


@api_view(['GET'])
def category_statistics_view(request, category_slug):
    """Get detailed statistics for a category"""
    category = get_object_or_404(ScoringCategory, slug=category_slug, is_active=True)
    
    scores = CompoundScore.objects.filter(category=category)
    
    stats = {
        'category': ScoringCategorySerializer(category).data,
        'total_compounds': scores.count(),
        'average_score': scores.aggregate(Avg('score'))['score__avg'] or 0,
        'average_confidence': scores.aggregate(Avg('confidence'))['confidence__avg'] or 0,
        'high_confidence_count': scores.filter(confidence__gte=0.8).count(),
        'medium_confidence_count': scores.filter(confidence__gte=0.6, confidence__lt=0.8).count(),
        'low_confidence_count': scores.filter(confidence__lt=0.6).count(),
        'score_distribution': {
            'excellent': scores.filter(score__gte=0.8).count(),
            'good': scores.filter(score__gte=0.6, score__lt=0.8).count(),
            'fair': scores.filter(score__gte=0.4, score__lt=0.6).count(),
            'poor': scores.filter(score__lt=0.4).count(),
        }
    }
    
    return Response(stats)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_predict_view(request):
    """Trigger prediction for multiple compounds"""
    compound_ids = request.data.get('compound_ids', [])
    category_slugs = request.data.get('categories', [])
    
    if not compound_ids:
        return Response({'error': 'compound_ids is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        from compound_ranker.ml.predictor import predict_compound_scores
        
        results = []
        for compound_id in compound_ids:
            try:
                compound = Compound.objects.get(id=compound_id)
                if category_slugs:
                    categories = ScoringCategory.objects.filter(slug__in=category_slugs, is_active=True)
                else:
                    categories = ScoringCategory.objects.filter(is_active=True)
                
                for category in categories:
                    score_obj = predict_compound_scores(compound, category)
                    if score_obj:
                        results.append({
                            'compound_id': compound.id,
                            'category': category.slug,
                            'score': score_obj.score,
                            'confidence': score_obj.confidence
                        })
            except Compound.DoesNotExist:
                continue
        
        return Response({
            'message': f'Predicted scores for {len(results)} compound-category pairs',
            'results': results
        })
        
    except ImportError:
        return Response({
            'error': 'Prediction system not available'
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        return Response({
            'error': f'Prediction failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
