from django.contrib import admin
from django.urls import path, include

from .views import (
    compound_detail,
    add_compound,
    submit_rating,
    compound_search,
    compound_list,
    mechanism_list,
    add_mechanism,
    ajax_add_mechanism,
    ajax_add_category,
    ajax_add_target,
    api_targets,
    review_snippet,
)

urlpatterns = [
    path('', compound_list, name='compound_list'),
    path('add/', add_compound, name='add_compound'),
    path('search/', compound_search, name='compound_search'),

    path('mechanisms/', mechanism_list, name='mechanism_list'),
    path('mechanisms/add/', add_mechanism, name='add_mechanism'),
    path('ajax/add-mechanism/', ajax_add_mechanism, name='ajax_add_mechanism'),

    path('ajax/add-category/', ajax_add_category, name='ajax_add_category'),
    path('ajax/add-target/', ajax_add_target, name='ajax_add_target'),
    path('api/targets/', api_targets, name='api_targets'),

    path('<slug:slug>/', compound_detail, name='compound_detail'),
    path('<slug:slug>/rate/', submit_rating, name='submit_rating'),
    path('<slug:slug>/snippet/<int:snippet_id>/review/', review_snippet, name='review_snippet'),
]
