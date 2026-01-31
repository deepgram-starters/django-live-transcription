"""WebSocket URL routing"""
from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('stt/stream', consumers.LiveTranscriptionConsumer.as_asgi()),
]
