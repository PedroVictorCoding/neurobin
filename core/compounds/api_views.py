from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from collections import deque
from .models import (
    Compound,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    CompoundKnowledgeGraphRun,
    CompoundKnowledgeGraphEdge,
    Target
)
from .serializers import (
    CompoundTargetInteractionSerializer,
    CompoundToCompoundTargetInteractionSerializer,
    CompoundKnowledgeGraphRunSerializer,
    CompoundKnowledgeGraphEdgeSerializer,
)
from .knowledge_graph import generate_compound_knowledge_graph


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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def compound_network_graph(request):
    """Paginated network graph payload for compounds, targets, and mechanisms."""
    limit_raw = request.GET.get('limit', 500)
    cursor_raw = request.GET.get('cursor', 0)
    include_related_raw = request.GET.get('include_related', '0')
    include_connections_raw = request.GET.get('include_connections', '0')

    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return Response({'error': 'limit must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    try:
        cursor = int(cursor_raw)
    except (TypeError, ValueError):
        return Response({'error': 'cursor must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    if cursor < 0:
        cursor = 0

    include_related = str(include_related_raw).strip().lower() not in {'0', 'false', 'no'}
    include_connections = str(include_connections_raw).strip().lower() not in {'0', 'false', 'no'}

    compounds_page = list(
        Compound.objects.filter(id__gt=cursor)
        .order_by('id')
        .values('id', 'name', 'slug', 'aliases')[: limit + 1]
    )
    has_more = len(compounds_page) > limit
    compounds_page = compounds_page[:limit]

    page_compound_ids = [row['id'] for row in compounds_page]
    next_cursor = page_compound_ids[-1] if has_more and page_compound_ids else None

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_ids: set[str] = set()

    def add_node(node_id: str, node_type: str, label: str, *, note: str = '', meta: dict | None = None) -> None:
        if node_id in nodes:
            return
        payload = {
            'id': node_id,
            'node_type': node_type,
            'label': label,
            'note': note or '',
        }
        if meta:
            payload['meta'] = meta
        nodes[node_id] = payload

    def add_edge(
        edge_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        relation_label: str,
        *,
        note: str = '',
        meta: dict | None = None,
    ) -> None:
        if edge_id in edge_ids:
            return
        edge_ids.add(edge_id)
        payload = {
            'id': edge_id,
            'source': source_id,
            'target': target_id,
            'relation_type': relation_type,
            'relation_label': relation_label,
            'note': note or '',
        }
        if meta:
            payload['meta'] = meta
        edges.append(payload)

    for row in compounds_page:
        alias_text = (row.get('aliases') or '').strip()
        add_node(
            f"compound:{row['id']}",
            'compound',
            row['name'],
            note=alias_text,
            meta={'compound_id': row['id'], 'slug': row['slug']},
        )

    if include_connections and page_compound_ids:
        cti_rows = (
            CompoundTargetInteraction.objects.filter(compound_id__in=page_compound_ids)
            .select_related('compound', 'target')
            .order_by('compound_id', 'target_id', 'mechanism')
        )
        for row in cti_rows:
            compound_node = f"compound:{row.compound_id}"
            target_node = f"target:{row.target_id}"
            mechanism_key = (row.mechanism or 'unknown').strip() or 'unknown'
            mechanism_node = f"mechanism:{mechanism_key}"

            add_node(
                target_node,
                'target',
                row.target.name,
                note=(row.target.gene_name or '').strip(),
                meta={'target_id': row.target_id},
            )
            add_node(
                mechanism_node,
                'mechanism',
                row.get_mechanism_display(),
                note='Mechanism of action',
                meta={'mechanism': mechanism_key},
            )

            affinity_label = row.get_affinity_level_display()
            affinity_suffix = '' if row.affinity_level == 'unknown' else f" ({affinity_label})"

            add_edge(
                f"cti:{row.id}:compound_mechanism",
                compound_node,
                mechanism_node,
                'compound_mechanism',
                row.get_mechanism_display(),
                note=row.notes or '',
                meta={'affinity_level': row.affinity_level, 'affinity_label': affinity_label},
            )
            add_edge(
                f"cti:{row.id}:mechanism_target",
                mechanism_node,
                target_node,
                'mechanism_target',
                f"acts on{affinity_suffix}",
                note=row.notes or '',
                meta={'affinity_level': row.affinity_level, 'affinity_label': affinity_label},
            )
            add_edge(
                f"cti:{row.id}:compound_target",
                compound_node,
                target_node,
                'compound_target',
                f"{row.get_mechanism_display()}{affinity_suffix}",
                note=row.notes or '',
                meta={'affinity_level': row.affinity_level, 'affinity_label': affinity_label},
            )

        cci_rows = (
            CompoundToCompoundTargetInteraction.objects.filter(
                Q(compound_a_id__in=page_compound_ids) | Q(compound_b_id__in=page_compound_ids)
            )
            .select_related('compound_a', 'compound_b', 'target')
            .order_by('compound_a_id', 'compound_b_id', 'target_id')
        )
        for row in cci_rows:
            node_a = f"compound:{row.compound_a_id}"
            node_b = f"compound:{row.compound_b_id}"
            target_node = f"target:{row.target_id}"

            if include_related:
                add_node(
                    node_a,
                    'compound',
                    row.compound_a.name,
                    note=(row.compound_a.aliases or '').strip(),
                    meta={'compound_id': row.compound_a_id, 'slug': row.compound_a.slug},
                )
                add_node(
                    node_b,
                    'compound',
                    row.compound_b.name,
                    note=(row.compound_b.aliases or '').strip(),
                    meta={'compound_id': row.compound_b_id, 'slug': row.compound_b.slug},
                )
            elif node_a not in nodes or node_b not in nodes:
                # Keep graph self-contained when related compounds are disabled.
                continue

            add_node(
                target_node,
                'target',
                row.target.name,
                note=(row.target.gene_name or '').strip(),
                meta={'target_id': row.target_id},
            )

            interaction_label = row.get_interaction_type_display()
            via_target_label = f"{interaction_label} via {row.target.name}"
            note_parts = [part for part in [row.description, row.source] if part]
            interaction_note = " | ".join(note_parts)
            add_edge(
                f"cci:{row.id}:compound_compound",
                node_a,
                node_b,
                'compound_compound',
                via_target_label,
                note=interaction_note,
                meta={
                    'target': row.target.name,
                    'confidence': row.confidence,
                    'confidence_label': row.get_confidence_display(),
                    'interaction_type': row.interaction_type,
                },
            )
            add_edge(
                f"cci:{row.id}:compound_a_target",
                node_a,
                target_node,
                'shared_target',
                f"shared target ({row.target.name})",
                note=interaction_note,
                meta={'interaction_type': row.interaction_type},
            )
            add_edge(
                f"cci:{row.id}:compound_b_target",
                node_b,
                target_node,
                'shared_target',
                f"shared target ({row.target.name})",
                note=interaction_note,
                meta={'interaction_type': row.interaction_type},
            )

    payload = {
        'nodes': list(nodes.values()),
        'edges': edges,
        'mode': {
            'include_connections': include_connections,
            'include_related': include_related,
        },
        'pagination': {
            'cursor': cursor,
            'next_cursor': next_cursor,
            'limit': limit,
            'has_more': has_more,
            'returned_compounds': len(page_compound_ids),
        },
    }
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def compound_network_graph_subgraph(request, compound_id):
    """Return a depth-limited compound-centered subgraph for on-demand expansion."""
    try:
        anchor = Compound.objects.only('id', 'name', 'slug', 'aliases').get(id=compound_id)
    except Compound.DoesNotExist:
        return Response({'error': 'Compound not found'}, status=status.HTTP_404_NOT_FOUND)

    depth_raw = request.GET.get('depth', 3)
    compound_cap_raw = request.GET.get('compound_cap', 350)
    edge_cap_raw = request.GET.get('edge_cap', 4000)

    try:
        depth = int(depth_raw)
    except (TypeError, ValueError):
        return Response({'error': 'depth must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    depth = max(1, min(depth, 3))

    try:
        compound_cap = int(compound_cap_raw)
    except (TypeError, ValueError):
        return Response({'error': 'compound_cap must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    compound_cap = max(20, min(compound_cap, 1500))

    try:
        edge_cap = int(edge_cap_raw)
    except (TypeError, ValueError):
        return Response({'error': 'edge_cap must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    edge_cap = max(200, min(edge_cap, 10000))

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_ids: set[str] = set()

    def add_node(node_id: str, node_type: str, label: str, *, note: str = '', meta: dict | None = None) -> None:
        if node_id in nodes:
            return
        payload = {
            'id': node_id,
            'node_type': node_type,
            'label': label,
            'note': note or '',
        }
        if meta:
            payload['meta'] = meta
        nodes[node_id] = payload

    def add_edge(
        edge_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        relation_label: str,
        *,
        note: str = '',
        meta: dict | None = None,
    ) -> bool:
        if edge_id in edge_ids:
            return False
        if len(edges) >= edge_cap:
            return False
        edge_ids.add(edge_id)
        payload = {
            'id': edge_id,
            'source': source_id,
            'target': target_id,
            'relation_type': relation_type,
            'relation_label': relation_label,
            'note': note or '',
        }
        if meta:
            payload['meta'] = meta
        edges.append(payload)
        return True

    visited_compounds: set[int] = {anchor.id}
    compound_by_id: dict[int, Compound] = {anchor.id: anchor}
    queue: deque[tuple[int, int]] = deque([(anchor.id, 0)])

    while queue and len(edges) < edge_cap:
        current_id, current_depth = queue.popleft()
        current = compound_by_id.get(current_id)
        if current is None:
            current = Compound.objects.only('id', 'name', 'slug', 'aliases').filter(id=current_id).first()
            if current is None:
                continue
            compound_by_id[current_id] = current

        add_node(
            f"compound:{current.id}",
            'compound',
            current.name,
            note=(current.aliases or '').strip(),
            meta={'compound_id': current.id, 'slug': current.slug},
        )

        cti_rows = (
            CompoundTargetInteraction.objects.filter(compound_id=current.id)
            .select_related('target')
            .order_by('target_id', 'mechanism')[:80]
        )
        for cti in cti_rows:
            compound_node = f"compound:{cti.compound_id}"
            target_node = f"target:{cti.target_id}"
            mechanism_key = (cti.mechanism or 'unknown').strip() or 'unknown'
            mechanism_node = f"mechanism:{mechanism_key}"

            add_node(
                target_node,
                'target',
                cti.target.name,
                note=(cti.target.gene_name or '').strip(),
                meta={'target_id': cti.target_id},
            )
            add_node(
                mechanism_node,
                'mechanism',
                cti.get_mechanism_display(),
                note='Mechanism of action',
                meta={'mechanism': mechanism_key},
            )

            affinity_label = cti.get_affinity_level_display()
            affinity_suffix = '' if cti.affinity_level == 'unknown' else f" ({affinity_label})"
            add_edge(
                f"cti:{cti.id}:compound_mechanism",
                compound_node,
                mechanism_node,
                'compound_mechanism',
                cti.get_mechanism_display(),
                note=cti.notes or '',
                meta={'affinity_level': cti.affinity_level, 'affinity_label': affinity_label},
            )
            add_edge(
                f"cti:{cti.id}:mechanism_target",
                mechanism_node,
                target_node,
                'mechanism_target',
                f"acts on{affinity_suffix}",
                note=cti.notes or '',
                meta={'affinity_level': cti.affinity_level, 'affinity_label': affinity_label},
            )
            add_edge(
                f"cti:{cti.id}:compound_target",
                compound_node,
                target_node,
                'compound_target',
                f"{cti.get_mechanism_display()}{affinity_suffix}",
                note=cti.notes or '',
                meta={'affinity_level': cti.affinity_level, 'affinity_label': affinity_label},
            )
            if len(edges) >= edge_cap:
                break

        if current_depth >= depth or len(edges) >= edge_cap:
            continue

        cci_rows = (
            CompoundToCompoundTargetInteraction.objects.filter(
                Q(compound_a_id=current.id) | Q(compound_b_id=current.id)
            )
            .select_related('compound_a', 'compound_b', 'target')
            .order_by('target_id', 'compound_a_id', 'compound_b_id')[:80]
        )
        for cci in cci_rows:
            node_a = f"compound:{cci.compound_a_id}"
            node_b = f"compound:{cci.compound_b_id}"
            target_node = f"target:{cci.target_id}"

            add_node(
                node_a,
                'compound',
                cci.compound_a.name,
                note=(cci.compound_a.aliases or '').strip(),
                meta={'compound_id': cci.compound_a_id, 'slug': cci.compound_a.slug},
            )
            add_node(
                node_b,
                'compound',
                cci.compound_b.name,
                note=(cci.compound_b.aliases or '').strip(),
                meta={'compound_id': cci.compound_b_id, 'slug': cci.compound_b.slug},
            )
            add_node(
                target_node,
                'target',
                cci.target.name,
                note=(cci.target.gene_name or '').strip(),
                meta={'target_id': cci.target_id},
            )

            interaction_label = cci.get_interaction_type_display()
            via_target_label = f"{interaction_label} via {cci.target.name}"
            note_parts = [part for part in [cci.description, cci.source] if part]
            interaction_note = " | ".join(note_parts)

            add_edge(
                f"cci:{cci.id}:compound_compound",
                node_a,
                node_b,
                'compound_compound',
                via_target_label,
                note=interaction_note,
                meta={
                    'target': cci.target.name,
                    'confidence': cci.confidence,
                    'confidence_label': cci.get_confidence_display(),
                    'interaction_type': cci.interaction_type,
                },
            )
            add_edge(
                f"cci:{cci.id}:compound_a_target",
                node_a,
                target_node,
                'shared_target',
                f"shared target ({cci.target.name})",
                note=interaction_note,
                meta={'interaction_type': cci.interaction_type},
            )
            add_edge(
                f"cci:{cci.id}:compound_b_target",
                node_b,
                target_node,
                'shared_target',
                f"shared target ({cci.target.name})",
                note=interaction_note,
                meta={'interaction_type': cci.interaction_type},
            )
            if len(edges) >= edge_cap:
                break

            neighbor = cci.compound_b if cci.compound_a_id == current.id else cci.compound_a
            if neighbor.id not in visited_compounds and len(visited_compounds) < compound_cap:
                visited_compounds.add(neighbor.id)
                compound_by_id[neighbor.id] = neighbor
                queue.append((neighbor.id, current_depth + 1))

    payload = {
        'anchor_compound_id': anchor.id,
        'anchor_node_id': f"compound:{anchor.id}",
        'depth': depth,
        'nodes': list(nodes.values()),
        'edges': edges,
        'limits': {
            'compound_cap': compound_cap,
            'edge_cap': edge_cap,
            'visited_compounds': len(visited_compounds),
        },
    }
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def compound_network_graph_target_subgraph(request, target_id):
    """Return a depth-1 target-centered neighborhood for on-demand node expansion."""
    try:
        anchor = Target.objects.only('id', 'name', 'gene_name').get(id=target_id)
    except Target.DoesNotExist:
        return Response({'error': 'Target not found'}, status=status.HTTP_404_NOT_FOUND)

    compound_cap_raw = request.GET.get('compound_cap', 400)
    edge_cap_raw = request.GET.get('edge_cap', 4000)

    try:
        compound_cap = int(compound_cap_raw)
    except (TypeError, ValueError):
        return Response({'error': 'compound_cap must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    compound_cap = max(20, min(compound_cap, 1500))

    try:
        edge_cap = int(edge_cap_raw)
    except (TypeError, ValueError):
        return Response({'error': 'edge_cap must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
    edge_cap = max(200, min(edge_cap, 10000))

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_ids: set[str] = set()
    included_compound_ids: set[int] = set()

    def add_node(node_id: str, node_type: str, label: str, *, note: str = '', meta: dict | None = None) -> None:
        if node_id in nodes:
            return
        payload = {
            'id': node_id,
            'node_type': node_type,
            'label': label,
            'note': note or '',
        }
        if meta:
            payload['meta'] = meta
        nodes[node_id] = payload

    def add_edge(
        edge_id: str,
        source_id: str,
        target_id_value: str,
        relation_type: str,
        relation_label: str,
        *,
        note: str = '',
        meta: dict | None = None,
    ) -> bool:
        if edge_id in edge_ids:
            return False
        if len(edges) >= edge_cap:
            return False
        edge_ids.add(edge_id)
        payload = {
            'id': edge_id,
            'source': source_id,
            'target': target_id_value,
            'relation_type': relation_type,
            'relation_label': relation_label,
            'note': note or '',
        }
        if meta:
            payload['meta'] = meta
        edges.append(payload)
        return True

    anchor_node_id = f"target:{anchor.id}"
    add_node(
        anchor_node_id,
        'target',
        anchor.name,
        note=(anchor.gene_name or '').strip(),
        meta={'target_id': anchor.id},
    )

    cti_rows = (
        CompoundTargetInteraction.objects.filter(target_id=anchor.id)
        .select_related('compound')
        .order_by('compound_id', 'mechanism')[:2000]
    )
    for cti in cti_rows:
        if cti.compound_id not in included_compound_ids and len(included_compound_ids) >= compound_cap:
            continue

        compound_node = f"compound:{cti.compound_id}"
        add_node(
            compound_node,
            'compound',
            cti.compound.name,
            note=(cti.compound.aliases or '').strip(),
            meta={'compound_id': cti.compound_id, 'slug': cti.compound.slug},
        )
        included_compound_ids.add(cti.compound_id)

        affinity_label = cti.get_affinity_level_display()
        affinity_suffix = '' if cti.affinity_level == 'unknown' else f" ({affinity_label})"
        add_edge(
            f"target_cti:{cti.id}:compound_target",
            compound_node,
            anchor_node_id,
            'compound_target',
            f"{cti.get_mechanism_display()}{affinity_suffix}",
            note=cti.notes or '',
            meta={'affinity_level': cti.affinity_level, 'affinity_label': affinity_label},
        )
        if len(edges) >= edge_cap:
            break

    if len(edges) < edge_cap:
        cci_rows = (
            CompoundToCompoundTargetInteraction.objects.filter(target_id=anchor.id)
            .select_related('compound_a', 'compound_b', 'target')
            .order_by('compound_a_id', 'compound_b_id')[:2000]
        )
        for cci in cci_rows:
            if len(edges) >= edge_cap:
                break

            can_include_a = (
                cci.compound_a_id in included_compound_ids or len(included_compound_ids) < compound_cap
            )
            can_include_b = (
                cci.compound_b_id in included_compound_ids or len(included_compound_ids) < compound_cap
            )
            if not can_include_a and not can_include_b:
                continue

            if can_include_a:
                node_a = f"compound:{cci.compound_a_id}"
                add_node(
                    node_a,
                    'compound',
                    cci.compound_a.name,
                    note=(cci.compound_a.aliases or '').strip(),
                    meta={'compound_id': cci.compound_a_id, 'slug': cci.compound_a.slug},
                )
                included_compound_ids.add(cci.compound_a_id)
            else:
                node_a = f"compound:{cci.compound_a_id}"

            if can_include_b:
                node_b = f"compound:{cci.compound_b_id}"
                add_node(
                    node_b,
                    'compound',
                    cci.compound_b.name,
                    note=(cci.compound_b.aliases or '').strip(),
                    meta={'compound_id': cci.compound_b_id, 'slug': cci.compound_b.slug},
                )
                included_compound_ids.add(cci.compound_b_id)
            else:
                node_b = f"compound:{cci.compound_b_id}"

            if node_a not in nodes or node_b not in nodes:
                continue

            interaction_label = cci.get_interaction_type_display()
            via_target_label = f"{interaction_label} via {anchor.name}"
            note_parts = [part for part in [cci.description, cci.source] if part]
            interaction_note = " | ".join(note_parts)

            add_edge(
                f"target_cci:{cci.id}:compound_compound",
                node_a,
                node_b,
                'compound_compound',
                via_target_label,
                note=interaction_note,
                meta={
                    'target': anchor.name,
                    'confidence': cci.confidence,
                    'confidence_label': cci.get_confidence_display(),
                    'interaction_type': cci.interaction_type,
                },
            )
            add_edge(
                f"target_cci:{cci.id}:compound_a_target",
                node_a,
                anchor_node_id,
                'shared_target',
                f"shared target ({anchor.name})",
                note=interaction_note,
                meta={'interaction_type': cci.interaction_type},
            )
            add_edge(
                f"target_cci:{cci.id}:compound_b_target",
                node_b,
                anchor_node_id,
                'shared_target',
                f"shared target ({anchor.name})",
                note=interaction_note,
                meta={'interaction_type': cci.interaction_type},
            )

    payload = {
        'anchor_target_id': anchor.id,
        'anchor_node_id': anchor_node_id,
        'depth': 1,
        'nodes': list(nodes.values()),
        'edges': edges,
        'limits': {
            'compound_cap': compound_cap,
            'edge_cap': edge_cap,
            'included_compounds': len(included_compound_ids),
        },
    }
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def compound_knowledge_graph_enrich(request, compound_id):
    """Generate moderated graph edges using DB context + internet evidence."""
    if not request.user.is_staff:
        return Response({'error': 'Staff access required'}, status=status.HTTP_403_FORBIDDEN)

    try:
        compound = Compound.objects.get(id=compound_id)
    except Compound.DoesNotExist:
        return Response({'error': 'Compound not found'}, status=status.HTTP_404_NOT_FOUND)

    include_internet = bool(request.data.get('include_internet', True))
    force = bool(request.data.get('force', False))
    max_edges = request.data.get('max_edges', 25)
    try:
        max_edges = int(max_edges)
    except (TypeError, ValueError):
        return Response({'error': 'max_edges must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

    run, cache_hit = generate_compound_knowledge_graph(
        compound=compound,
        requested_by=request.user,
        include_internet=include_internet,
        max_edges=max_edges,
        force=force,
    )
    if cache_hit:
        run.cached_response_used = True
        run.save(update_fields=['cached_response_used'])

    payload = CompoundKnowledgeGraphRunSerializer(run).data
    payload['cache_hit'] = cache_hit
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def compound_knowledge_graph(request, compound_id):
    """Get latest graph run (or specific run) for a compound."""
    try:
        compound = Compound.objects.get(id=compound_id)
    except Compound.DoesNotExist:
        return Response({'error': 'Compound not found'}, status=status.HTTP_404_NOT_FOUND)

    run_id = request.GET.get('run_id')
    if run_id:
        run = (
            CompoundKnowledgeGraphRun.objects.filter(compound=compound, id=run_id)
            .prefetch_related(
                Prefetch(
                    'edges',
                    queryset=CompoundKnowledgeGraphEdge.objects.select_related('related_compound', 'related_target')
                )
            )
            .first()
        )
    else:
        run = (
            CompoundKnowledgeGraphRun.objects.filter(compound=compound, status__in=['completed', 'skipped'])
            .order_by('-created_at')
            .prefetch_related(
                Prefetch(
                    'edges',
                    queryset=CompoundKnowledgeGraphEdge.objects.select_related('related_compound', 'related_target')
                )
            )
            .first()
        )

    if not run:
        return Response(
            {
                'compound': compound.name,
                'run': None,
                'edges': [],
            },
            status=status.HTTP_200_OK
        )

    run_data = CompoundKnowledgeGraphRunSerializer(run).data
    edge_limit = request.GET.get('edge_limit')
    try:
        edge_limit = int(edge_limit) if edge_limit is not None else None
    except (TypeError, ValueError):
        edge_limit = None
    if edge_limit is not None and edge_limit > 0:
        limited_edges = run.edges.all()[:edge_limit]
        run_data['edges'] = CompoundKnowledgeGraphEdgeSerializer(limited_edges, many=True).data

    return Response(run_data, status=status.HTTP_200_OK)
