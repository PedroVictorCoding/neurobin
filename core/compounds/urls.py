from django.contrib import admin
from django.urls import path, include

from .views import (
    compound_detail,
    add_compound,
    submit_rating,
    compound_search,
    compound_list,
)

urlpatterns = [
    path('', compound_list, name='compound_list'),
    path('add/', add_compound, name='add_compound'),
    path('search/', compound_search, name='compound_search'),

    path('<slug:slug>/', compound_detail, name='compound_detail'),
    path('<slug:slug>/rate/', submit_rating, name='submit_rating'),

]
