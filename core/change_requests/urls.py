from django.urls import path
from . import views

app_name = 'change_requests'

urlpatterns = [
    path('', views.change_request_list, name='list'),
    path('<int:pk>/', views.change_request_detail, name='detail'),
    path('compound/create/', views.create_compound_change_request, name='create_compound'),
    path('<int:pk>/apply/', views.apply_change_request, name='apply'),
]
