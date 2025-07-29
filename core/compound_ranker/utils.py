"""
Utility functions for compound ranker
"""
import csv
import io
from typing import List, Dict, Optional
from django.http import HttpResponse
from django.db.models import Avg, Count, Q
from django.utils import timezone

from compounds.models import Compound
from .models import ScoringCategory, CompoundScore, UserCompoundAnnotation


def export_rankings_csv(category: ScoringCategory, limit: int = None) -> HttpResponse:
    """Export compound rankings to CSV"""
    scores = CompoundScore.objects.filter(
        category=category
    ).select_related('compound').order_by('-score')
    
    if limit:
        scores = scores[:limit]
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Rank',
        'Compound Name',
        'ChEMBL ID',
        'Score',
        'Confidence',
        'Score Percentage',
        'Model Version',
        'SMILES',
        'Categories',
        'Mechanisms'
    ])
    
    # Write data
    for rank, score in enumerate(scores, 1):
        compound = score.compound
        
        # Get compound categories and mechanisms
        categories = ', '.join(compound.categories.values_list('name', flat=True))
        mechanisms = ', '.join(compound.mechanism_of_action.values_list('name', flat=True))
        
        writer.writerow([
            rank,
            compound.name,
            compound.chembl_id or '',
            round(score.score, 4),
            round(score.confidence, 4),
            round(score.score * 100, 1),
            score.model_version,
            compound.smiles or '',
            categories,
            mechanisms
        ])
    
    # Create HTTP response
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{category.slug}_rankings.csv"'
    
    return response


def export_all_rankings_csv() -> HttpResponse:
    """Export all compound rankings across categories to CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Compound Name',
        'ChEMBL ID',
        'Category',
        'Score',
        'Confidence',
        'Rank',
        'Model Version',
        'SMILES'
    ])
    
    # Get all scores
    scores = CompoundScore.objects.select_related(
        'compound', 'category'
    ).order_by('compound__name', 'category__name')
    
    for score in scores:
        writer.writerow([
            score.compound.name,
            score.compound.chembl_id or '',
            score.category.name,
            round(score.score, 4),
            round(score.confidence, 4),
            score.rank_in_category,
            score.model_version,
            score.compound.smiles or ''
        ])
    
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="all_compound_rankings.csv"'
    
    return response


def get_compound_ranking_overview(compound: Compound) -> Dict:
    """Get comprehensive ranking overview for a compound"""
    scores = CompoundScore.objects.filter(
        compound=compound
    ).select_related('category')
    
    overview = {
        'compound': compound,
        'total_categories': scores.count(),
        'avg_score': scores.aggregate(Avg('score'))['score__avg'] or 0,
        'avg_confidence': scores.aggregate(Avg('confidence'))['confidence__avg'] or 0,
        'category_scores': {},
        'top_categories': [],
        'performance_tier': 'unranked'
    }
    
    # Category-specific data
    for score in scores:
        rank = score.rank_in_category
        total_in_category = CompoundScore.objects.filter(category=score.category).count()
        percentile = (1 - (rank - 1) / total_in_category) * 100 if total_in_category > 0 else 0
        
        overview['category_scores'][score.category.slug] = {
            'score': score.score,
            'confidence': score.confidence,
            'rank': rank,
            'total_compounds': total_in_category,
            'percentile': percentile,
            'tier': get_performance_tier(percentile)
        }
    
    # Top categories (best performing)
    top_scores = scores.order_by('-score')[:3]
    overview['top_categories'] = [
        {
            'category': score.category,
            'score': score.score,
            'rank': score.rank_in_category
        }
        for score in top_scores
    ]
    
    # Overall performance tier
    if overview['avg_score'] >= 0.8:
        overview['performance_tier'] = 'excellent'
    elif overview['avg_score'] >= 0.6:
        overview['performance_tier'] = 'good'
    elif overview['avg_score'] >= 0.4:
        overview['performance_tier'] = 'fair'
    elif overview['avg_score'] > 0:
        overview['performance_tier'] = 'poor'
    
    return overview


def get_performance_tier(percentile: float) -> str:
    """Get performance tier based on percentile"""
    if percentile >= 90:
        return 'top-10'
    elif percentile >= 75:
        return 'top-25'
    elif percentile >= 50:
        return 'top-50'
    elif percentile >= 25:
        return 'bottom-50'
    else:
        return 'bottom-25'


def get_category_insights(category: ScoringCategory) -> Dict:
    """Get insights and statistics for a category"""
    scores = CompoundScore.objects.filter(category=category)
    
    insights = {
        'category': category,
        'total_compounds': scores.count(),
        'avg_score': scores.aggregate(Avg('score'))['score__avg'] or 0,
        'avg_confidence': scores.aggregate(Avg('confidence'))['confidence__avg'] or 0,
        'score_distribution': {},
        'confidence_distribution': {},
        'top_mechanisms': [],
        'recent_additions': [],
        'user_annotations_count': 0
    }
    
    if scores.exists():
        # Score distribution
        insights['score_distribution'] = {
            'excellent': scores.filter(score__gte=0.8).count(),
            'good': scores.filter(score__gte=0.6, score__lt=0.8).count(),
            'fair': scores.filter(score__gte=0.4, score__lt=0.6).count(),
            'poor': scores.filter(score__lt=0.4).count(),
        }
        
        # Confidence distribution
        insights['confidence_distribution'] = {
            'high': scores.filter(confidence__gte=0.8).count(),
            'medium': scores.filter(confidence__gte=0.6, confidence__lt=0.8).count(),
            'low': scores.filter(confidence__lt=0.6).count(),
        }
        
        # Top mechanisms for high-scoring compounds
        from django.db.models import Count
        high_score_compounds = scores.filter(score__gte=0.7).values_list('compound', flat=True)
        
        if high_score_compounds:
            from compounds.models import CompoundMechanismOfAction
            mechanism_counts = CompoundMechanismOfAction.objects.filter(
                compounds__in=high_score_compounds
            ).annotate(
                compound_count=Count('compounds')
            ).order_by('-compound_count')[:5]
            
            insights['top_mechanisms'] = [
                {
                    'name': mech.name,
                    'compound_count': mech.compound_count,
                    'percentage': (mech.compound_count / len(high_score_compounds)) * 100
                }
                for mech in mechanism_counts
            ]
        
        # Recent high-scoring additions
        recent_scores = scores.filter(score__gte=0.6).order_by('-timestamp')[:5]
        insights['recent_additions'] = [
            {
                'compound': score.compound,
                'score': score.score,
                'added': score.timestamp
            }
            for score in recent_scores
        ]
    
    # User annotations count
    insights['user_annotations_count'] = UserCompoundAnnotation.objects.filter(
        category=category
    ).count()
    
    return insights


def find_similar_compounds(compound: Compound, category: ScoringCategory, limit: int = 5) -> List[Dict]:
    """Find compounds with similar scoring patterns"""
    try:
        target_score = CompoundScore.objects.get(compound=compound, category=category)
    except CompoundScore.DoesNotExist:
        return []
    
    # Find compounds with similar scores (+/- 0.1)
    score_range = 0.1
    similar_scores = CompoundScore.objects.filter(
        category=category,
        score__gte=target_score.score - score_range,
        score__lte=target_score.score + score_range
    ).exclude(
        compound=compound
    ).select_related('compound').order_by(
        # Order by score similarity
        'score'
    )[:limit]
    
    similar_compounds = []
    for score in similar_scores:
        # Calculate similarity metrics
        score_diff = abs(score.score - target_score.score)
        confidence_diff = abs(score.confidence - target_score.confidence)
        
        # Check for shared mechanisms
        target_mechanisms = set(compound.mechanism_of_action.values_list('id', flat=True))
        similar_mechanisms = set(score.compound.mechanism_of_action.values_list('id', flat=True))
        shared_mechanisms = target_mechanisms.intersection(similar_mechanisms)
        mechanism_similarity = len(shared_mechanisms) / max(len(target_mechanisms), 1)
        
        similar_compounds.append({
            'compound': score.compound,
            'score': score.score,
            'confidence': score.confidence,
            'score_difference': score_diff,
            'confidence_difference': confidence_diff,
            'mechanism_similarity': mechanism_similarity,
            'shared_mechanisms_count': len(shared_mechanisms)
        })
    
    # Sort by overall similarity (score similarity + mechanism similarity)
    similar_compounds.sort(
        key=lambda x: x['score_difference'] + (1 - x['mechanism_similarity']) * 0.5
    )
    
    return similar_compounds


def get_trending_compounds(category: ScoringCategory = None, days: int = 7) -> List[Dict]:
    """Get compounds that are trending (recently added or updated with high scores)"""
    from datetime import datetime, timedelta
    
    cutoff_date = timezone.now() - timedelta(days=days)
    
    if category:
        recent_scores = CompoundScore.objects.filter(
            category=category,
            timestamp__gte=cutoff_date,
            score__gte=0.6
        ).select_related('compound', 'category').order_by('-score', '-timestamp')[:10]
    else:
        recent_scores = CompoundScore.objects.filter(
            timestamp__gte=cutoff_date,
            score__gte=0.6
        ).select_related('compound', 'category').order_by('-score', '-timestamp')[:20]
    
    trending = []
    for score in recent_scores:
        trending.append({
            'compound': score.compound,
            'category': score.category,
            'score': score.score,
            'confidence': score.confidence,
            'rank': score.rank_in_category,
            'added_date': score.timestamp,
            'is_new': score.timestamp >= cutoff_date
        })
    
    return trending


def cleanup_old_scores(days_old: int = 90, dry_run: bool = True) -> Dict:
    """Clean up old compound scores that may be outdated"""
    from datetime import datetime, timedelta
    
    cutoff_date = timezone.now() - timedelta(days=days_old)
    
    old_scores = CompoundScore.objects.filter(
        timestamp__lt=cutoff_date
    )
    
    stats = {
        'total_old_scores': old_scores.count(),
        'categories_affected': old_scores.values('category').distinct().count(),
        'compounds_affected': old_scores.values('compound').distinct().count(),
    }
    
    if not dry_run:
        deleted_count = old_scores.delete()[0]
        stats['deleted_count'] = deleted_count
    
    return stats
