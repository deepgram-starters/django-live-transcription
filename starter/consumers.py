"""WebSocket consumer for Live Transcription"""
import os
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("DEEPGRAM_API_KEY")
if not API_KEY:
    raise ValueError("DEEPGRAM_API_KEY environment variable is required")

deepgram = DeepgramClient(api_key=API_KEY)


class LiveTranscriptionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Accept WebSocket connection and setup Deepgram connection"""
        await self.accept()
        print("Client connected to /stt/stream")

        # Store connection reference
        self.dg_connection = None

    async def disconnect(self, close_code):
        """Clean up Deepgram connection"""
        print(f"Client disconnected with code: {close_code}")
        if self.dg_connection:
            await self.dg_connection.finish()

    async def receive(self, text_data=None, bytes_data=None):
        """
        Receive messages from WebSocket.
        First message: JSON config with model/language
        Subsequent messages: Audio bytes
        """
        try:
            # First message is configuration
            if text_data:
                config = json.loads(text_data)
                model = config.get('model', 'nova-2')
                language = config.get('language', 'en')

                # Create Deepgram connection
                self.dg_connection = deepgram.listen.asyncwebsocket.v("1")

                # Set up event handlers
                async def on_message(self, result, **kwargs):
                    """Forward transcription results to client"""
                    sentence = result.channel.alternatives[0].transcript
                    if len(sentence) > 0:
                        await self.send(text_data=json.dumps({
                            'transcript': sentence,
                            'is_final': result.is_final
                        }))

                async def on_error(self, error, **kwargs):
                    """Handle Deepgram errors"""
                    print(f"Deepgram error: {error}")
                    await self.send(text_data=json.dumps({
                        'error': str(error)
                    }))

                self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
                self.dg_connection.on(LiveTranscriptionEvents.Error, on_error)

                # Start connection with options
                options = LiveOptions(
                    model=model,
                    language=language,
                    smart_format=True,
                    interim_results=True,
                )

                if await self.dg_connection.start(options):
                    print(f"Deepgram connection started with model={model}, language={language}")
                else:
                    print("Failed to start Deepgram connection")
                    await self.close()

            # Subsequent messages are audio data
            elif bytes_data and self.dg_connection:
                await self.dg_connection.send(bytes_data)

        except Exception as e:
            print(f"Error in receive: {e}")
            await self.send(text_data=json.dumps({
                'error': str(e)
            }))
