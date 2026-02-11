import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg
from django.db import transaction
from django.utils import timezone

from .models import (
    ResearchSnippet, 
    SnippetReview, 
    SnippetTag, 
    SnippetTagging,
    SnippetComment,
    ResearchSettings,
    UserRole
)
from .forms import (
    ResearchSnippetForm, 
    SnippetReviewForm, 
    SnippetSearchForm,
    AIAnalysisForm,
    ResearchSettingsForm,
    BulkSnippetActionForm
)
from compounds.models import Compound


def _push_recent_snippet(request, snippet):
    recent = request.session.get("recent_snippets", [])
    if not isinstance(recent, list):
        recent = []
    recent = [row for row in recent if row.get("id") != snippet.id]
    recent.insert(
        0,
        {
            "id": snippet.id,
            "title": snippet.title,
            "compound_slug": snippet.compound.slug,
            "compound_name": snippet.compound.name,
        },
    )
    request.session["recent_snippets"] = recent[:8]


def snippet_list(request):
    """
    Display paginated list of research snippets with filtering.
    """
    form = SnippetSearchForm(request.GET)
    snippets = ResearchSnippet.objects.select_related('compound', 'created_by').prefetch_related('tags', 'reviews')
    
    # Apply user visibility permissions
    if request.user.is_authenticated:
        if request.user.is_staff:
            # Staff can see all snippets
            pass
        else:
            # Regular users see public snippets + their own drafts
            snippets = snippets.filter(
                Q(visibility='public') |
                Q(created_by=request.user, visibility='draft')
            )
    else:
        # Anonymous users only see public snippets
        snippets = snippets.filter(visibility='public')
    
    # Apply search filters
    if form.is_valid():
        query = form.cleaned_data.get('query')
        compound = form.cleaned_data.get('compound')
        snippet_type = form.cleaned_data.get('snippet_type')
        status = form.cleaned_data.get('status')
        tags = form.cleaned_data.get('tags')
        created_by = form.cleaned_data.get('created_by')
        ai_generated = form.cleaned_data.get('ai_generated')
        sort_by = form.cleaned_data.get('sort_by', '-created_at')
        
        if query:
            snippets = snippets.filter(
                Q(title__icontains=query) |
                Q(content__icontains=query) |
                Q(source_title__icontains=query)
            )
        
        if compound:
            snippets = snippets.filter(compound=compound)
        
        if snippet_type:
            snippets = snippets.filter(snippet_type=snippet_type)
        
        if status:
            snippets = snippets.filter(status=status)
        
        if tags:
            snippets = snippets.filter(tags__in=tags).distinct()
        
        if created_by:
            snippets = snippets.filter(created_by=created_by)
        
        if ai_generated == 'true':
            snippets = snippets.filter(ai_generated=True)
        elif ai_generated == 'false':
            snippets = snippets.filter(ai_generated=False)
        
        snippets = snippets.order_by(sort_by)
    
    # Pagination
    paginator = Paginator(snippets, 12)  # 12 snippets per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get research settings for display options
    settings = ResearchSettings.objects.first()
    
    context = {
        'snippets': page_obj,
        'form': form,
        'settings': settings,
        'total_count': snippets.count(),
    }
    
    return render(request, 'research/snippet_list.html', context)


def snippet_detail(request, pk):
    """
    Display detailed view of a research snippet with review options.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if not snippet.visibility == 'public' and not snippet.visibility == 'public_review':
        if not request.user.is_authenticated or (snippet.created_by != request.user and not request.user.is_staff):
            return HttpResponseForbidden("You don't have permission to view this snippet.")
    
    # Increment view count
    snippet.view_count += 1
    snippet.save(update_fields=['view_count'])
    _push_recent_snippet(request, snippet)
    
    # Get user's existing review if any
    user_review = None
    if request.user.is_authenticated:
        try:
            user_review = SnippetReview.objects.get(snippet=snippet, reviewer=request.user)
        except SnippetReview.DoesNotExist:
            pass
    
    # Get review stats
    review_stats = snippet.reviews.aggregate(
        total_reviews=Count('id'),
        positive_reviews=Count('id', filter=Q(vote_type='validate')),
        negative_reviews=Count('id', filter=Q(vote_type='reject'))
    )
    
    # Calculate approval percentage
    approval_percentage = 0
    if review_stats['total_reviews'] > 0:
        approval_percentage = round((review_stats['positive_reviews'] / review_stats['total_reviews']) * 100)
    
    # Get all reviews with comments for display
    reviews_with_comments = snippet.reviews.select_related('reviewer').filter(
        comment__isnull=False, comment__gt=''
    ).order_by('-created_at')
    
    # Check if user can review
    can_review = (
        request.user.is_authenticated and 
        snippet.created_by != request.user and 
        not user_review and
        snippet.visibility in ['public', 'public_review']
    )
    
    context = {
        'snippet': snippet,
        'user_review': user_review,
        'review_stats': review_stats,
        'approval_percentage': approval_percentage,
        'reviews_with_comments': reviews_with_comments,
        'can_review': can_review,
        'review_form': SnippetReviewForm() if can_review else None,
    }
    
    return render(request, 'research/snippet_detail.html', context)


@login_required
def create_snippet(request):
    """
    Create a new research snippet.
    """
    # Check if public submissions are enabled
    settings = ResearchSettings.objects.first()
    if settings and not settings.public_submissions_enabled and not request.user.is_staff:
        messages.error(request, "Public research submissions are currently disabled.")
        return redirect('research:snippet_list')
    
    if request.method == 'POST':
        form = ResearchSnippetForm(request.POST)
        if form.is_valid():
            snippet = form.save(commit=False)
            snippet.created_by = request.user
            
            # Set visibility based on whether it's saved as draft
            if request.POST.get('save_draft') or form.cleaned_data.get('save_as_draft'):
                snippet.visibility = 'draft'
                snippet.status = 'draft'
            else:
                snippet.visibility = 'public'
                snippet.status = 'submitted'
            
            snippet.save()
            form.save_m2m()  # Save many-to-many relationships
            
            messages.success(request, "Research snippet created successfully!")
            return redirect('research:snippet_detail', pk=snippet.pk)
    else:
        form = ResearchSnippetForm()
        
        # Pre-fill compound if provided in URL
        compound_id = request.GET.get('compound')
        if compound_id:
            try:
                compound = Compound.objects.get(pk=compound_id)
                form.initial['compound'] = compound
            except Compound.DoesNotExist:
                pass
    
    context = {
        'form': form,
        'title': 'Create Research Snippet',
        'settings': settings,
    }
    
    # Add selected compound to context for back button
    compound_id = request.GET.get('compound')
    if compound_id:
        try:
            context['selected_compound'] = Compound.objects.get(pk=compound_id)
        except Compound.DoesNotExist:
            pass
    elif request.method == 'POST' and form.is_valid():
        context['selected_compound'] = form.cleaned_data['compound']
    
    return render(request, 'research/snippet_form.html', context)


@login_required
def edit_snippet(request, pk):
    """
    Edit an existing research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You don't have permission to edit this snippet.")
    
    if request.method == 'POST':
        form = ResearchSnippetForm(request.POST, instance=snippet)
        if form.is_valid():
            form.save()
            messages.success(request, "Research snippet updated successfully!")
            return redirect('research:snippet_detail', pk=snippet.pk)
    else:
        form = ResearchSnippetForm(instance=snippet)
    
    context = {
        'form': form,
        'snippet': snippet,
        'title': 'Edit Research Snippet',
        'selected_compound': snippet.compound,  # Always available for edit
    }
    
    return render(request, 'research/snippet_form.html', context)


@login_required
@require_POST
def submit_review(request, pk):
    """
    Submit or update a review/vote for a research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by == request.user:
        return JsonResponse({'error': 'Cannot review your own snippet'}, status=400)
    
    if snippet.visibility not in ['public', 'public_review']:
        return JsonResponse({'error': 'Cannot review private snippets'}, status=400)
    
    # Check if user already reviewed
    existing_review = SnippetReview.objects.filter(snippet=snippet, reviewer=request.user).first()
    
    try:
        data = json.loads(request.body)
        vote_type = data.get('vote_type')
        comment = data.get('comment', '').strip()
        
        if vote_type not in ['validate', 'reject']:
            return JsonResponse({'error': 'Invalid vote type'}, status=400)
        
        if existing_review:
            # Update existing review
            existing_review.vote_type = vote_type
            existing_review.comment = comment
            existing_review.save()
            review = existing_review
            action = 'updated'
        else:
            # Create new review
            review = SnippetReview.objects.create(
                snippet=snippet,
                reviewer=request.user,
                vote_type=vote_type,
                comment=comment
            )
            action = 'created'
        
        # Update snippet status
        snippet.update_status()
        
        # Get updated stats
        stats = snippet.reviews.aggregate(
            total=Count('id'),
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        return JsonResponse({
            'success': True,
            'review_id': review.id,
            'action': action,
            'new_status': snippet.status,
            'stats': stats,
            'confidence_level': snippet.confidence_level,
            'confidence_color': snippet.confidence_color
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def delete_snippet(request, pk):
    """
    Delete a research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You don't have permission to delete this snippet.")
    
    if request.method == 'POST':
        snippet.delete()
        messages.success(request, "Research snippet deleted successfully!")
        return redirect('research:snippet_list')
    
    context = {
        'snippet': snippet,
    }
    
    return render(request, 'research/snippet_confirm_delete.html', context)


def compound_snippets(request, slug):
    """
    Display all research snippets for a specific compound.
    """
    compound = get_object_or_404(Compound, slug=slug)
    
    snippets = ResearchSnippet.objects.filter(compound=compound).select_related('created_by').prefetch_related('tags', 'reviews', 'comments')
    
    # Apply visibility filters
    if request.user.is_authenticated:
        if not request.user.is_staff:
            snippets = snippets.filter(
                Q(visibility__in=['public', 'public_review']) |
                Q(created_by=request.user)
            )
    else:
        snippets = snippets.filter(visibility__in=['public', 'public_review'])
    
    # Annotate with review stats
    snippets = snippets.annotate(
        positive_reviews=Count('reviews', filter=Q(reviews__vote_type='validate')),
        negative_reviews=Count('reviews', filter=Q(reviews__vote_type='reject')),
        total_reviews=Count('reviews')
    )
    
    # Get user's reviews for each snippet
    user_reviews = {}
    if request.user.is_authenticated:
        from .models import SnippetReview
        user_review_qs = SnippetReview.objects.filter(
            snippet__in=snippets,
            reviewer=request.user
        ).values('snippet_id', 'vote_type')
        user_reviews = {r['snippet_id']: r['vote_type'] for r in user_review_qs}
    
    # Add user review vote to each snippet
    for snippet in snippets:
        snippet.user_review_vote = user_reviews.get(snippet.id)
    
    # Group by snippet type
    snippet_groups = {}
    for snippet in snippets:
        snippet_type = snippet.get_snippet_type_display()
        if snippet_type not in snippet_groups:
            snippet_groups[snippet_type] = []
        snippet_groups[snippet_type].append(snippet)
    
    context = {
        'compound': compound,
        'snippet_groups': snippet_groups,
        'total_count': snippets.count(),
        'user_reviews': user_reviews,
    }
    
    return render(request, 'research/compound_snippets.html', context)


@login_required
def ai_analysis(request):
    """
    AI-powered research analysis and summarization.
    """
    settings = ResearchSettings.objects.first()
    if settings and not settings.ai_summaries_enabled:
        messages.error(request, "AI analysis features are currently disabled.")
        return redirect('research:snippet_list')
    
    if request.method == 'POST':
        form = AIAnalysisForm(request.POST)
        if form.is_valid():
            # This is where you'd integrate with your AI service
            # For now, we'll return a placeholder response
            content = form.cleaned_data['content']
            analysis_type = form.cleaned_data['analysis_type']
            target_compound = form.cleaned_data.get('target_compound')
            
            # Placeholder AI response
            ai_result = {
                'summary': f"AI analysis of {len(content)} characters of content...",
                'confidence': 0.85,
                'suggested_tags': ['Dopaminergic', 'Clinical Study'],
                'compound_detected': target_compound.name if target_compound else 'Auto-detection needed',
            }
            
            context = {
                'form': form,
                'ai_result': ai_result,
                'original_content': content,
            }
            
            return render(request, 'research/ai_analysis.html', context)
    else:
        form = AIAnalysisForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'research/ai_analysis.html', context)


@staff_member_required
def manage_settings(request):
    """
    Admin view for managing research system settings.
    """
    settings, created = ResearchSettings.objects.get_or_create(
        defaults={
            'public_submissions_enabled': True,
            'require_review_flair': True,
            'ai_summaries_enabled': True,
        }
    )
    
    if request.method == 'POST':
        form = ResearchSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings updated successfully!")
            return redirect('research:manage_settings')
    else:
        form = ResearchSettingsForm(instance=settings)
    
    # Get system statistics
    stats = {
        'total_snippets': ResearchSnippet.objects.count(),
        'verified_snippets': ResearchSnippet.objects.filter(status='verified').count(),
        'pending_review': ResearchSnippet.objects.filter(status='needs_review').count(),
        'total_reviews': SnippetReview.objects.count(),
        'active_contributors': ResearchSnippet.objects.values('created_by').distinct().count(),
    }
    
    context = {
        'form': form,
        'settings': settings,
        'stats': stats,
    }
    
    return render(request, 'research/manage_settings.html', context)


@staff_member_required
def moderation_queue(request):
    """
    Admin view for moderating research snippets.
    """
    # Get snippets that need attention
    flagged_snippets = ResearchSnippet.objects.filter(status='flagged').select_related('created_by', 'compound')
    pending_snippets = ResearchSnippet.objects.filter(status='needs_review').select_related('created_by', 'compound')
    
    context = {
        'flagged_snippets': flagged_snippets,
        'pending_snippets': pending_snippets,
    }
    
    return render(request, 'research/moderation_queue.html', context)


@staff_member_required
@require_POST
def moderate_snippet(request, pk):
    """
    Moderate a specific snippet (approve, reject, etc.).
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    try:
        data = json.loads(request.body)
        action = data.get('action')
        
        if action == 'approve':
            snippet.status = 'verified'
        elif action == 'reject':
            snippet.status = 'rejected'
        elif action == 'flag':
            snippet.status = 'flagged'
        elif action == 'reset':
            snippet.status = 'needs_review'
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)
        
        snippet.save()
        
        return JsonResponse({
            'success': True,
            'new_status': snippet.status,
            'message': f'Snippet {action}ed successfully'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# API endpoints for AJAX functionality

@require_POST
def toggle_snippet_visibility(request, pk):
    """
    Toggle snippet visibility (for snippet owners).
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=403)
    
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    if snippet.created_by != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        new_visibility = data.get('visibility')
        
        if new_visibility not in ['private', 'public', 'public_review']:
            return JsonResponse({'error': 'Invalid visibility option'}, status=400)
        
        snippet.visibility = new_visibility
        
        # Update status based on new visibility
        if new_visibility == 'private':
            snippet.status = 'draft'
        elif new_visibility == 'public':
            snippet.status = 'submitted'
        else:  # public_review
            snippet.status = 'needs_review'
        
        snippet.save()
        
        return JsonResponse({
            'success': True,
            'new_visibility': snippet.visibility,
            'new_status': snippet.status
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def quick_vote_snippet(request, pk):
    """
    Handle quick vote (approve/reject) for a snippet from compound page.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by == request.user:
        return JsonResponse({'error': 'Cannot vote on your own snippet'}, status=400)
    
    # Check if user already voted
    existing_review = SnippetReview.objects.filter(snippet=snippet, reviewer=request.user).first()
    if existing_review:
        return JsonResponse({'error': 'You have already voted on this snippet'}, status=400)
    
    try:
        data = json.loads(request.body)
        vote_type = data.get('vote_type')
        
        if vote_type not in ['validate', 'reject']:
            return JsonResponse({'error': 'Invalid vote type'}, status=400)
        
        # Create review without comment (quick vote)
        review = SnippetReview.objects.create(
            snippet=snippet,
            reviewer=request.user,
            vote_type=vote_type,
            comment=''
        )
        
        # Update snippet status
        snippet.update_status()
        
        # Get updated stats
        stats = snippet.reviews.aggregate(
            total=Count('id'),
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        return JsonResponse({
            'success': True,
            'vote_type': vote_type,
            'stats': stats
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def add_snippet_comment(request, pk):
    """
    Add a comment to a research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    try:
        data = json.loads(request.body)
        content = data.get('content', '').strip()
        
        if not content or len(content) < 5:
            return JsonResponse({'error': 'Comment must be at least 5 characters long'}, status=400)
        
        # Create comment
        comment = SnippetComment.objects.create(
            snippet=snippet,
            author=request.user,
            content=content
        )
        
        return JsonResponse({
            'success': True,
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'author': comment.author.username,
                'created_at': comment.created_at.strftime('%b %d, %Y at %I:%M %p')
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# REST Framework ViewSets
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Q
from .serializers import (
    ResearchSnippetSerializer,
    SnippetReviewSerializer,
    SnippetTagSerializer,
    SnippetTaggingSerializer,
    UserRoleSerializer,
    ResearchSettingsSerializer,
    SnippetCommentSerializer
)


class ResearchSnippetViewSet(viewsets.ModelViewSet):
    serializer_class = ResearchSnippetSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'id'

    def get_queryset(self):
        queryset = ResearchSnippet.objects.select_related('compound', 'created_by').prefetch_related('tags', 'reviews', 'comments')
        
        # Apply visibility permissions
        if self.request.user.is_authenticated:
            if self.request.user.is_staff:
                # Staff can see all snippets
                pass
            else:
                # Regular users see public snippets + their own drafts
                queryset = queryset.filter(
                    Q(visibility='public') |
                    Q(created_by=self.request.user, visibility='draft')
                )
        else:
            # Anonymous users only see public snippets
            queryset = queryset.filter(visibility='public')
            
        # Filter by compound if specified
        compound_id = self.request.query_params.get('compound', None)
        if compound_id:
            queryset = queryset.filter(compound_id=compound_id)
            
        # Filter by status if specified
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def increment_view(self, request, id=None):
        """Increment view count for snippet"""
        snippet = self.get_object()
        snippet.view_count += 1
        snippet.save()
        return Response({'view_count': snippet.view_count})

    @action(detail=True, methods=['get'])
    def analytics(self, request, id=None):
        """Get analytics data for snippet"""
        snippet = self.get_object()
        reviews = snippet.reviews.aggregate(
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        analytics_data = {
            'view_count': snippet.view_count,
            'positive_reviews': reviews['positive'] or 0,
            'negative_reviews': reviews['negative'] or 0,
            'confidence_level': snippet.confidence_level,
            'comment_count': snippet.comments.count(),
        }
        
        return Response(analytics_data)


class SnippetReviewViewSet(viewsets.ModelViewSet):
    queryset = SnippetReview.objects.all()
    serializer_class = SnippetReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = SnippetReview.objects.select_related('snippet', 'reviewer')
        snippet_id = self.request.query_params.get('snippet', None)
        if snippet_id:
            queryset = queryset.filter(snippet_id=snippet_id)
        return queryset.order_by('-created_at')


class SnippetTagViewSet(viewsets.ModelViewSet):
    queryset = SnippetTag.objects.all()
    serializer_class = SnippetTagSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class SnippetTaggingViewSet(viewsets.ModelViewSet):
    queryset = SnippetTagging.objects.all()
    serializer_class = SnippetTaggingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = SnippetTagging.objects.select_related('snippet', 'tag', 'tagged_by')
        snippet_id = self.request.query_params.get('snippet', None)
        if snippet_id:
            queryset = queryset.filter(snippet_id=snippet_id)
        return queryset.order_by('-created_at')


class UserRoleViewSet(viewsets.ModelViewSet):
    queryset = UserRole.objects.all()
    serializer_class = UserRoleSerializer
    permission_classes = [permissions.IsAdminUser]


class ResearchSettingsViewSet(viewsets.ModelViewSet):
    queryset = ResearchSettings.objects.all()
    serializer_class = ResearchSettingsSerializer
    permission_classes = [permissions.IsAdminUser]


class SnippetCommentViewSet(viewsets.ModelViewSet):
    queryset = SnippetComment.objects.all()
    serializer_class = SnippetCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = SnippetComment.objects.select_related('snippet', 'author')
        snippet_id = self.request.query_params.get('snippet', None)
        if snippet_id:
            queryset = queryset.filter(snippet_id=snippet_id)
        return queryset.order_by('-created_at')
