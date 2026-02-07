from django.urls import path
from .views import ExploreStacksView, MyStacksView, StackCalendarView, StackDetailView, StackScheduleView, StackShareEmbedView, StackShareView, stack_risk_refresh

urlpatterns = [
    path('', MyStacksView.as_view(), name='my_stacks'),
    path('<int:stack_id>/', StackDetailView.as_view(), name='stack_detail'),
    path('<int:stack_id>/risk/refresh/', stack_risk_refresh, name='stack_risk_refresh'),
    path('share/<int:stack_id>/', StackShareView.as_view(), name='stack_share'),
    path('share/<int:stack_id>/embed/', StackShareEmbedView.as_view(), name='stack_share_embed'),
    path('schedule/', StackScheduleView.as_view(), name='stack_schedule'),
    path('calendar/', StackCalendarView.as_view(), name='stack_calendar'),
    path('explore/', ExploreStacksView.as_view(), name='explore_stacks'),
]
