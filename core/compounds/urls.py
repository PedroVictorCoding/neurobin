from django.contrib import admin
from django.urls import path, include

from .views import (
    compound_detail,
    compound_details,
    compound_admet_ai_refresh,
    compound_molprop_refresh,
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
    api_mechanisms,
    api_categories,
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
    path('api/mechanisms/', api_mechanisms, name='api_mechanisms'),
    path('api/categories/', api_categories, name='api_categories'),

    path('<slug:slug>/details/', compound_details, name='compound_details'),
    path('<slug:slug>/', compound_detail, name='compound_detail'),
    path('<slug:slug>/rate/', submit_rating, name='submit_rating'),
    path('<slug:slug>/admet-ai/refresh/', compound_admet_ai_refresh, name='compound_admet_ai_refresh'),
    path('<slug:slug>/molprop/refresh/', compound_molprop_refresh, name='compound_molprop_refresh'),
    path('<slug:slug>/snippet/<int:snippet_id>/review/', review_snippet, name='review_snippet'),
]
