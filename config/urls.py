"""HTTP URL routing"""
from django.urls import path, include

urlpatterns = [
    path('api/', include('starter.urls')),
]
