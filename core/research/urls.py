from django.urls import path
from . import views

app_name = 'research'

urlpatterns = [
    # Main snippet views
    path('', views.snippet_list, name='snippet_list'),
    path('snippet/<int:pk>/', views.snippet_detail, name='snippet_detail'),
    path('create/', views.create_snippet, name='create_snippet'),
    path('snippet/<int:pk>/edit/', views.edit_snippet, name='edit_snippet'),
    path('snippet/<int:pk>/delete/', views.delete_snippet, name='delete_snippet'),
    
    # Review system
    path('snippet/<int:pk>/review/', views.submit_review, name='submit_review'),
    
    # Compound-specific snippets
    path('compound/<slug:slug>/', views.compound_snippets, name='compound_snippets'),
    path('compound/<slug:slug>/explore/', views.compound_research_explorer, name='compound_research_explorer'),
    path(
        'compound/<slug:slug>/explore/graph-context/',
        views.compound_explorer_graph_context,
        name='compound_explorer_graph_context',
    ),
    path(
        'compound/<slug:slug>/explore/url-graph-context/',
        views.compound_explorer_url_graph_context,
        name='compound_explorer_url_graph_context',
    ),
    
    # AI features
    path('ai-analysis/', views.ai_analysis, name='ai_analysis'),
    
    # Admin/moderation
    path('admin/settings/', views.manage_settings, name='manage_settings'),
    path('admin/moderation/', views.moderation_queue, name='moderation_queue'),
    path('admin/moderate/<int:pk>/', views.moderate_snippet, name='moderate_snippet'),
    
    # AJAX endpoints
    path('snippet/<int:pk>/toggle-visibility/', views.toggle_snippet_visibility, name='toggle_visibility'),
    path('snippet/<int:pk>/quick-vote/', views.quick_vote_snippet, name='quick_vote_snippet'),
    path('snippet/<int:pk>/comment/', views.add_snippet_comment, name='add_snippet_comment'),
]
