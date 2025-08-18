from django.urls import path
from .views import MyStacksView

urlpatterns = [
    path('', MyStacksView.as_view(), name='my_stacks'),
]
