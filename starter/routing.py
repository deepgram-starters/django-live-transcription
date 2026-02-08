"""WebSocket URL routing"""
from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('api/live-transcription', consumers.LiveTranscriptionConsumer.as_asgi()),
]
