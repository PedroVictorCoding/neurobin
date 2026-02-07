from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count, Q, Avg
from research.models import ResearchSnippet, SnippetReview, SnippetComment
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

@login_required
def profile_dashboard(request, username=None):
    """
    User profile dashboard with research statistics and activity.
    """
    # Get the target user (current user if no username specified)
    if username:
        profile_user = get_object_or_404(User, username=username)
        is_own_profile = request.user == profile_user
    else:
        profile_user = request.user
        is_own_profile = True
    
    # Ensure user has a profile
    profile, created = UserProfile.objects.get_or_create(user=profile_user)
    
    # Get user's submitted research snippets
    user_snippets = ResearchSnippet.objects.filter(
        created_by=profile_user,
        visibility='public'
    ).select_related('compound').prefetch_related('reviews', 'comments')
    
    # Calculate approval statistics for user's own research
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
    
    # Get user's comments on all research (including their own)
    all_comments = SnippetComment.objects.filter(
        author=profile_user
    ).select_related('snippet', 'snippet__compound', 'snippet__created_by').order_by('-created_at')
    
    # Get user's reviews given to others
    reviews_given = SnippetReview.objects.filter(
        reviewer=profile_user
    ).exclude(
        snippet__created_by=profile_user
    ).select_related('snippet', 'snippet__compound', 'snippet__created_by').order_by('-created_at')
    
    # Get user activity summary
    activity_summary = {
        'snippets_posted': user_snippets.count(),
        'total_reviews_received': total_reviews,
        'approval_rating': approval_rating,
        'comments_made': all_comments.count(),
        'reviews_given': reviews_given.count(),
        'verified_snippets': user_snippets.filter(status='verified').count(),
        'draft_snippets': user_snippets.filter(status='draft').count(),
    }
    
    context = {
        'profile_user': profile_user,
        'user_profile': profile,
        'is_own_profile': is_own_profile,
        'user_snippets': user_snippets[:10],  # Show latest 10
        'activity_summary': activity_summary,
        'approval_stats': approval_stats,
        'all_comments': all_comments[:15],  # Show latest 15
        'reviews_given': reviews_given[:15],  # Show latest 15
    }
    
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
