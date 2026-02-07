from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from .models import (
    Compound,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    Target
)
from .serializers import (
    CompoundTargetInteractionSerializer,
    CompoundToCompoundTargetInteractionSerializer
)


class CompoundTargetInteractionListView(generics.ListCreateAPIView):
    """List and create compound-target interactions"""
    serializer_class = CompoundTargetInteractionSerializer
    
    def get_queryset(self):
        queryset = CompoundTargetInteraction.objects.select_related('compound', 'target')
        compound_id = self.request.query_params.get('compound', None)
        target_id = self.request.query_params.get('target', None)
        
        if compound_id:
            queryset = queryset.filter(compound_id=compound_id)
        if target_id:
            queryset = queryset.filter(target_id=target_id)
            
        return queryset


class CompoundToCompoundInteractionListView(generics.ListCreateAPIView):
    """List and create compound-to-compound interactions"""
    serializer_class = CompoundToCompoundTargetInteractionSerializer
    
    def get_queryset(self):
        queryset = CompoundToCompoundTargetInteraction.objects.select_related(
            'compound_a', 'compound_b', 'target', 'created_by'
        )
        
        compound_a = self.request.query_params.get('compound_a', None)
        compound_b = self.request.query_params.get('compound_b', None)
        target_id = self.request.query_params.get('target', None)
        
        if compound_a:
            queryset = queryset.filter(
                Q(compound_a_id=compound_a) | Q(compound_b_id=compound_a)
            )
        if compound_b:
            queryset = queryset.filter(
                Q(compound_a_id=compound_b) | Q(compound_b_id=compound_b)
            )
        if target_id:
            queryset = queryset.filter(target_id=target_id)
            
        return queryset


@api_view(['GET'])
def compound_interactions(request, compound_id):
    """Get all interactions for a specific compound"""
    try:
        compound = Compound.objects.get(id=compound_id)
    except Compound.DoesNotExist:
        return Response({'error': 'Compound not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get all interactions where this compound is involved
    interactions = CompoundToCompoundTargetInteraction.objects.filter(
        Q(compound_a=compound) | Q(compound_b=compound)
    ).select_related('compound_a', 'compound_b', 'target', 'created_by')
    
    serializer = CompoundToCompoundTargetInteractionSerializer(interactions, many=True)
    
    # Format the response to always show the current compound as the primary one
    formatted_interactions = []
    for interaction_data in serializer.data:
        interaction = {
            'id': interaction_data['id'],
            'other_compound': None,
            'target': interaction_data['target'],
            'shared_target': interaction_data['target'],
            'current_compound_mechanism': None,
            'other_compound_mechanism': None,
            'interaction_type': interaction_data['interaction_type'],
            'description': interaction_data['description'],
            'confidence': interaction_data['confidence'],
            'source': interaction_data['source'],
            'created_at': interaction_data['created_at'],
            'created_by': interaction_data['created_by']
        }
        
        # Determine which compound is the "other" one
        if interaction_data['compound_a'] == compound.name:
            interaction['other_compound'] = interaction_data['compound_b']
            interaction['current_compound_mechanism'] = interaction_data['compound_a_mechanism']
            interaction['other_compound_mechanism'] = interaction_data['compound_b_mechanism']
        else:
            interaction['other_compound'] = interaction_data['compound_a']
            interaction['current_compound_mechanism'] = interaction_data['compound_b_mechanism']
            interaction['other_compound_mechanism'] = interaction_data['compound_a_mechanism']
        
        formatted_interactions.append(interaction)
    
    return Response({
        'compound': compound.name,
        'interactions': formatted_interactions
    })


@api_view(['GET'])
def compound_pair_interactions(request):
    """Get interactions between two specific compounds"""
    compound_a_id = request.GET.get('compound_a')
    compound_b_id = request.GET.get('compound_b')
    
    if not compound_a_id or not compound_b_id:
        return Response({
            'error': 'Both compound_a and compound_b parameters are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        compound_a = Compound.objects.get(id=compound_a_id)
        compound_b = Compound.objects.get(id=compound_b_id)
    except Compound.DoesNotExist:
        return Response({'error': 'One or both compounds not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Find interactions between these two compounds
    interactions = CompoundToCompoundTargetInteraction.objects.filter(
        (Q(compound_a=compound_a) & Q(compound_b=compound_b)) |
        (Q(compound_a=compound_b) & Q(compound_b=compound_a))
    ).select_related('compound_a', 'compound_b', 'target', 'created_by')
    
    serializer = CompoundToCompoundTargetInteractionSerializer(interactions, many=True)
    
    return Response({
        'compound_a': compound_a.name,
        'compound_b': compound_b.name,
        'interactions': serializer.data
    })


@api_view(['GET'])
def compound_search_api(request):
    """Search compounds by name and aliases for autocomplete/dropdown"""
    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 20))
    
    if not query:
        return Response({'compounds': []})
    
    # Search by name and aliases
    compounds = Compound.objects.filter(
        Q(name__icontains=query) |
        Q(aliases__icontains=query)
    ).values('id', 'name', 'slug', 'aliases')[:limit]
    
    # Format results for dropdown
    results = []
    for compound in compounds:
        results.append({
            'id': compound['id'],
            'name': compound['name'],
            'slug': compound['slug'],
            'aliases': compound['aliases'] or ''
        })
    
    return Response({'compounds': results})
