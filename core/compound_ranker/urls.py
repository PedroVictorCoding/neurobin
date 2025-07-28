from django.urls import path, include
from . import views

app_name = 'compound_ranker'

urlpatterns = [
    # Main ranking views
    path('', views.rankings_list, name='rankings_list'),
    path('rankings/', views.rankings_list, name='rankings_list'),
    path('rankings/<slug:slug>/', views.rankings_detail, name='rankings_detail'),
    path('compound/<int:compound_id>/', views.compound_detail, name='compound_detail'),
    
    # User interaction
    path('annotate/', views.add_user_annotation, name='add_user_annotation'),
    
    # Admin/staff views
    path('training-status/', views.training_status, name='training_status'),
    
    # API endpoints
    path('api/', include('compound_ranker.api.urls')),
    path('api/stats/<slug:slug>/', views.api_category_stats, name='api_category_stats'),
]
