from django.urls import path
from . import views

app_name = 'compound_ranker_api'

urlpatterns = [
    # Categories
    path('categories/', views.ScoringCategoryListView.as_view(), name='category_list'),
    path('categories/<slug:slug>/', views.ScoringCategoryDetailView.as_view(), name='category_detail'),
    path('categories/<slug:category_slug>/stats/', views.category_statistics_view, name='category_stats'),
    
    # Compound Scores
    path('compound-scores/', views.CompoundScoreListView.as_view(), name='compound_score_list'),
    path('compound-scores/<int:pk>/', views.CompoundScoreDetailView.as_view(), name='compound_score_detail'),
    
    # Top compounds and rankings
    path('top-compounds/', views.top_compounds_view, name='top_compounds'),
    path('compounds/<int:compound_id>/rankings/', views.compound_rankings_view, name='compound_rankings'),
    
    # User annotations
    path('annotations/', views.UserAnnotationListView.as_view(), name='user_annotation_list'),
    path('annotations/<int:pk>/', views.UserAnnotationDetailView.as_view(), name='user_annotation_detail'),
    
    # Bulk operations
    path('bulk-predict/', views.bulk_predict_view, name='bulk_predict'),
]
