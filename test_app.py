#!/usr/bin/env python
"""
Test suite for Django Live Transcription Starter App

Tests WebSocket connection establishment, audio streaming, and transcription functionality.
Run with: pytest -v test_app.py
"""
import pytest
import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async

# Set up Django for testing
os.environ.setdefault('DEEPGRAM_API_KEY', 'test-api-key')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app')

import app

class TestTranscriptionConsumer:
    """Test the WebSocket consumer for live transcription."""

    @pytest.fixture
    def consumer_communicator(self):
        """Create a WebSocket communicator for testing."""
        communicator = WebsocketCommunicator(app.TranscriptionConsumer.as_asgi(), "/ws/transcription/")
        return communicator

    @pytest.mark.asyncio
    async def test_websocket_connection_establishment(self, consumer_communicator):
        """Test WebSocket connection can be established."""
        connected, _ = await consumer_communicator.connect()
        assert connected
        await consumer_communicator.disconnect()

    @pytest.mark.asyncio
    async def test_websocket_missing_api_key(self):
        """Test WebSocket connection fails without API key."""
        with patch.dict(os.environ, {}, clear=True):  # Clear environment variables
            communicator = WebsocketCommunicator(app.TranscriptionConsumer.as_asgi(), "/ws/transcription/")
            connected, _ = await communicator.connect()
            assert not connected

    @pytest.mark.asyncio
    async def test_toggle_transcription_message(self, consumer_communicator):
        """Test toggle transcription WebSocket message."""
        connected, _ = await consumer_communicator.connect()
        assert connected

        # Mock Deepgram client
        with patch('app.DeepgramClient') as mock_deepgram:
            mock_connection = AsyncMock()
            mock_deepgram.return_value.listen.asynclive.v.return_value = mock_connection
            mock_connection.start.return_value = True

            # Send toggle transcription message
            await consumer_communicator.send_json_to({
                'type': 'toggle_transcription'
            })

            # Should receive status update
            response = await consumer_communicator.receive_json_from()
            assert response['type'] == 'transcription_status'
            assert response['status'] == 'started'

        await consumer_communicator.disconnect()

    @pytest.mark.asyncio
    async def test_audio_stream_handling(self, consumer_communicator):
        """Test handling of audio stream data."""
        connected, _ = await consumer_communicator.connect()
        assert connected

        # Mock Deepgram connection
        with patch('app.DeepgramClient') as mock_deepgram:
            mock_connection = AsyncMock()
            mock_deepgram.return_value.listen.asynclive.v.return_value = mock_connection
            mock_connection.start.return_value = True

            # Start transcription
            await consumer_communicator.send_json_to({
                'type': 'toggle_transcription'
            })

            # Receive status update
            await consumer_communicator.receive_json_from()

            # Send binary audio data
            fake_audio_data = b'fake_audio_data'
            await consumer_communicator.send_bytes_to(fake_audio_data)

            # Verify audio data was sent to Deepgram
            mock_connection.send.assert_called_once_with(fake_audio_data)

        await consumer_communicator.disconnect()



    @pytest.mark.asyncio
    async def test_transcription_result_handling(self, consumer_communicator):
        """Test handling of transcription results from Deepgram."""
        connected, _ = await consumer_communicator.connect()
        assert connected

        consumer = app.TranscriptionConsumer()
        consumer.send = AsyncMock()

        # Mock transcription result
        mock_result = MagicMock()
        mock_result.channel.alternatives[0].transcript = "Hello world"
        mock_result.is_final = True
        mock_result.channel.alternatives[0].confidence = 0.95

        # Test transcript handling
        await consumer.on_deepgram_transcript(result=mock_result)

        # Verify correct message was sent
        consumer.send.assert_called_once()
        call_args = consumer.send.call_args[1]
        sent_data = json.loads(call_args['text_data'])

        assert sent_data['type'] == 'transcription_update'
        assert sent_data['transcript'] == 'Hello world'
        assert sent_data['is_final'] == True
        assert sent_data['confidence'] == 0.95

        await consumer_communicator.disconnect()

    @pytest.mark.asyncio
    async def test_proper_cleanup_on_disconnect(self, consumer_communicator):
        """Test proper cleanup when WebSocket disconnects."""
        connected, _ = await consumer_communicator.connect()
        assert connected

        with patch('app.DeepgramClient') as mock_deepgram:
            mock_connection = AsyncMock()
            mock_deepgram.return_value.listen.asynclive.v.return_value = mock_connection
            mock_connection.start.return_value = True

            # Start transcription
            await consumer_communicator.send_json_to({
                'type': 'toggle_transcription'
            })
            await consumer_communicator.receive_json_from()

            # Disconnect
            await consumer_communicator.disconnect()

            # Verify cleanup was called
            mock_connection.finish.assert_called_once()

    def test_deepgram_api_integration_setup(self):
        """Test that Deepgram API integration is properly configured."""
        # Test that required imports work
        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

        # Test that we can create instances (without actual API calls)
        assert DeepgramClient
        assert LiveTranscriptionEvents
        assert LiveOptions

    def test_audio_webm_format_support(self):
        """Test that the app supports 'audio/webm' format as required."""
        # This is more of a documentation test - the actual format handling
        # happens in the frontend JavaScript MediaRecorder

        # Verify that our WebSocket consumer can handle binary data
        consumer = app.TranscriptionConsumer()

        # Test that receive method exists and handles bytes_data
        import inspect
        signature = inspect.signature(consumer.receive)
        params = list(signature.parameters.keys())

        assert 'text_data' in params
        assert 'bytes_data' in params

class TestDjangoApplication:
    """Test the Django application setup."""

    def test_django_settings_configuration(self):
        """Test Django settings are properly configured."""
        from django.conf import settings

        assert settings.DEBUG == True
        assert 'channels' in settings.INSTALLED_APPS
        assert settings.ASGI_APPLICATION == '__main__.application'
        assert 'InMemoryChannelLayer' in settings.CHANNEL_LAYERS['default']['BACKEND']

    def test_main_view_returns_html(self):
        """Test that the main view returns HTML content."""
        from django.http import HttpRequest

        request = HttpRequest()
        response = app.index_view(request)

        assert response.status_code == 200
        assert 'Django Live Transcription' in response.content.decode()
        assert 'ws/transcription/' in response.content.decode()

    def test_url_configuration(self):
        """Test URL routing is properly configured."""
        from django.urls import reverse, resolve

        # Test root URL resolves
        url = reverse('home')
        assert url == '/'

        # Test URL resolution
        resolved = resolve('/')
        assert resolved.func == app.index_view

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
