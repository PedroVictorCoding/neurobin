from django.contrib import admin
from django.urls import path, include

from .views import (
    compound_detail,
    add_compound,
)

urlpatterns = [
    path('add/', add_compound, name='add_compound'),
    path('<slug:slug>/', compound_detail, name='compound_detail'),
]
