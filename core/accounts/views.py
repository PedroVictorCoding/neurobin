from urllib.parse import urlencode
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from research.models import ResearchSnippet, SnippetReview, SnippetComment
from stacks.models import Stack
from logs.models import UserGoal, UserGoalCompletion
from .models import UserProfile
from .forms import StyledUserCreationForm, UserProfileForm

def register(request):
    if request.method == 'POST':
        form = StyledUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = StyledUserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})

def custom_logout(request):
    """
    Custom logout view that handles both GET and POST requests.
    """
    if request.method == 'POST':
        logout(request)
        messages.success(request, 'You have been successfully logged out.')
        return redirect('home')
    else:
        # For GET requests, show a confirmation page or just log out
        # For simplicity, we'll just log out immediately
        logout(request)
        messages.success(request, 'You have been successfully logged out.')
        return redirect('home')


def _build_goal_tracker_context(user):
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_days = [week_start + timedelta(days=idx) for idx in range(7)]

    goals = list(
        UserGoal.objects.filter(user=user, is_active=True)
        .order_by('goal_type', 'name', 'id')
    )

    weekly_checks = UserGoalCompletion.objects.filter(
        goal__in=goals,
        date__gte=week_days[0],
        date__lte=week_days[-1],
    )
    check_map = {
        (check.goal_id, check.date): bool(check.completed)
        for check in weekly_checks
    }

    goal_rows = []
    week_completed_count = 0
    for goal in goals:
        row_checks = []
        for day in week_days:
            completed = check_map.get((goal.id, day), False)
            if completed:
                week_completed_count += 1
            row_checks.append({
                'date': day,
                'date_iso': day.isoformat(),
                'completed': completed,
                'is_today': day == today,
            })
        goal_rows.append({
            'id': goal.id,
            'name': goal.name,
            'goal_type': goal.goal_type,
            'checks': row_checks,
        })

    completed_dates = set(
        UserGoalCompletion.objects.filter(
            goal__user=user,
            completed=True,
        ).values_list('date', flat=True)
    )
    streak_days = 0
    streak_cursor = today
    while streak_cursor in completed_dates:
        streak_days += 1
        streak_cursor -= timedelta(days=1)

    return {
        'today': today,
        'week_days': week_days,
        'goals': goal_rows,
        'streak_days': streak_days,
        'week_completed_count': week_completed_count,
        'week_total_count': len(goals) * 7,
    }

def profile_dashboard(request, username=None):
    """
    User profile dashboard with research statistics and activity.
    """
    # Get the target user (current user if no username specified).
    if username:
        profile_user = get_object_or_404(User, username=username)
        is_own_profile = request.user.is_authenticated and request.user == profile_user
    else:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        profile_user = request.user
        is_own_profile = True

    # Ensure user has a profile (create lazily only for own profile).
    profile = UserProfile.objects.filter(user=profile_user).first()
    if not profile:
        profile = UserProfile.objects.create(user=profile_user) if is_own_profile else UserProfile(user=profile_user)

    # Allow profile actions (stack toggles and weekly goals).
    if request.method == 'POST' and is_own_profile:
        action = (request.POST.get('action') or '').strip().lower()
        if action in {'set_stack_active', 'toggle_stack_active'}:
            stack_id = request.POST.get('stack_id')
            stack = Stack.objects.filter(id=stack_id, user=profile_user).first() if stack_id else None
            if stack:
                if action == 'set_stack_active':
                    requested = str(request.POST.get('is_active', '')).strip().lower()
                    desired_active = requested in {'1', 'true', 'on', 'yes'}
                    if stack.is_active != desired_active:
                        stack.is_active = desired_active
                        stack.save(update_fields=['is_active'])
                else:
                    stack.is_active = not stack.is_active
                    stack.save(update_fields=['is_active'])

            params = {'tab': 'stacks'}
            stack_query = (request.POST.get('stack_q') or '').strip()
            if stack_query:
                params['stack_q'] = stack_query
            return redirect(f"{request.path}?{urlencode(params)}")

        if action == 'add_profile_goal':
            goal_name = (request.POST.get('goal_name') or '').strip()
            goal_type = (request.POST.get('goal_type') or '').strip().lower()
            if goal_name and goal_type in {'workout', 'health'}:
                UserGoal.objects.create(
                    user=profile_user,
                    name=goal_name[:120],
                    goal_type=goal_type,
                )
            return redirect(f"{request.path}?tab=goals")

        if action == 'toggle_goal_completion':
            goal_id = request.POST.get('goal_id')
            goal_date_raw = (request.POST.get('goal_date') or '').strip()
            goal = UserGoal.objects.filter(
                id=goal_id,
                user=profile_user,
                is_active=True,
            ).first()

            goal_date = None
            if goal_date_raw:
                try:
                    goal_date = date.fromisoformat(goal_date_raw)
                except ValueError:
                    goal_date = None

            if goal and goal_date:
                desired_completed = str(request.POST.get('is_completed', '')).strip().lower() in {'1', 'true', 'on', 'yes'}
                completion, _ = UserGoalCompletion.objects.get_or_create(
                    goal=goal,
                    date=goal_date,
                    defaults={'completed': desired_completed},
                )
                if completion.completed != desired_completed:
                    completion.completed = desired_completed
                    completion.save(update_fields=['completed', 'updated_at'])

            return redirect(f"{request.path}?tab=goals")

    # Build snippet queryset (own profile sees all; other viewers see only public).
    user_snippets = ResearchSnippet.objects.filter(created_by=profile_user)
    if not is_own_profile:
        user_snippets = user_snippets.filter(visibility='public')
    user_snippets = user_snippets.select_related('compound').prefetch_related('reviews', 'comments')

    # Calculate approval statistics for visible snippets.
    user_snippet_ids = user_snippets.values_list('id', flat=True)
    approval_stats = SnippetReview.objects.filter(
        snippet_id__in=user_snippet_ids
    ).aggregate(
        total_reviews=Count('id'),
        approvals=Count('id', filter=Q(vote_type='validate')),
        rejections=Count('id', filter=Q(vote_type='reject'))
    )
    
    # Calculate approval rating
    total_reviews = approval_stats['total_reviews'] or 0
    approvals = approval_stats['approvals'] or 0
    rejections = approval_stats['rejections'] or 0
    approval_rating = (approvals / total_reviews * 100) if total_reviews > 0 else 0
    
    # Get user's comments on all research (including their own).
    all_comments = SnippetComment.objects.filter(
        author=profile_user
    )
    if not is_own_profile:
        all_comments = all_comments.filter(snippet__visibility='public')
    all_comments = all_comments.select_related('snippet', 'snippet__compound', 'snippet__created_by').order_by('-created_at')

    # Get user's reviews given to others.
    reviews_given = SnippetReview.objects.filter(
        reviewer=profile_user
    ).exclude(
        snippet__created_by=profile_user
    )
    if not is_own_profile:
        reviews_given = reviews_given.filter(snippet__visibility='public')
    reviews_given = reviews_given.select_related('snippet', 'snippet__compound', 'snippet__created_by').order_by('-created_at')

    # Build visible stack listing for profile.
    visible_stacks = Stack.objects.filter(user=profile_user)
    if not is_own_profile:
        visible_stacks = visible_stacks.filter(visibility='public')
    stack_total_count = visible_stacks.count()

    stack_query = (request.GET.get('stack_q') or '').strip()
    if stack_query:
        visible_stacks = visible_stacks.filter(name__icontains=stack_query)
    visible_stacks = (
        visible_stacks
        .annotate(compound_count=Count('items', distinct=True))
        .select_related('risk_assessment')
        .order_by('-is_active', '-created')
    )

    # Analytics are only shown for your own profile.
    has_analytics = is_own_profile and request.user.is_authenticated
    analytics_context = {}
    if has_analytics:
        from logs.views import build_analytics_dashboard_context
        analytics_context = build_analytics_dashboard_context(request.user)

    allowed_tabs = {'research', 'comments', 'reviews', 'stacks'}
    if is_own_profile:
        allowed_tabs.add('goals')
    default_tab = 'stacks'
    if has_analytics:
        allowed_tabs.add('analytics')
        default_tab = 'analytics'
    active_tab = (request.GET.get('tab') or default_tab).strip().lower()
    if active_tab not in allowed_tabs:
        active_tab = default_tab

    # Get user activity summary
    activity_summary = {
        'snippets_posted': user_snippets.count(),
        'total_reviews_received': total_reviews,
        'approval_rating': approval_rating,
        'comments_made': all_comments.count(),
        'reviews_given': reviews_given.count(),
        'verified_snippets': user_snippets.filter(status='verified').count(),
        'draft_snippets': user_snippets.filter(status='draft').count(),
        'stacks_count': stack_total_count,
    }

    goal_tracker = _build_goal_tracker_context(profile_user) if is_own_profile else None

    context = {
        'profile_user': profile_user,
        'user_profile': profile,
        'is_own_profile': is_own_profile,
        'active_tab': active_tab,
        'user_snippets': user_snippets[:10],  # Show latest 10
        'activity_summary': activity_summary,
        'approval_stats': approval_stats,
        'all_comments': all_comments[:15],  # Show latest 15
        'reviews_given': reviews_given[:15],  # Show latest 15
        'profile_stacks': list(visible_stacks[:30]),
        'stack_query': stack_query,
        'has_analytics': has_analytics,
        'goal_tracker': goal_tracker,
    }
    context.update(analytics_context)

    return render(request, 'accounts/profile_dashboard.html', context)

@login_required
def edit_profile(request):
    """
    Edit user profile information including profile image.
    """
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile_dashboard')
    else:
        form = UserProfileForm(instance=profile, user=request.user)
    
    context = {
        'form': form,
        'user_profile': profile,
    }
    
    return render(request, 'accounts/edit_profile.html', context)


# REST Framework ViewSets
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.models import User
from .serializers import UserSerializer, UserProfileSerializer


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'username'

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user's information"""
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Users can only access their own profile or view others if staff
        if self.request.user.is_staff:
            return UserProfile.objects.all()
        return UserProfile.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user's profile"""
        try:
            profile = request.user.profile
            serializer = self.get_serializer(profile)
            return Response(serializer.data)
        except UserProfile.DoesNotExist:
            return Response({'detail': 'Profile not found'}, status=404)
