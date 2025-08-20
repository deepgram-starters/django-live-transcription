import os
import sys
import json
import asyncio
import logging

from pathlib import Path

def check_api_key():
    """Check if Deepgram API key is available."""
    api_key = os.environ.get('DEEPGRAM_API_KEY')
    if not api_key:
        print("❌ ERROR: DEEPGRAM_API_KEY environment variable not found!")
        print("")
        print("Please set your Deepgram API key:")
        print("export DEEPGRAM_API_KEY=your_api_key_here")
        print("")
        print("Get your API key at: https://console.deepgram.com/signup?jump=keys")
        sys.exit(1)
    return api_key

# =============================================================================
# DJANGO CONFIGURATION & SETUP
# =============================================================================

os.environ.setdefault('DJANGO_SETTINGS_MODULE', '__main__')

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = 'django-live-transcription-starter-key-change-in-production'
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'channels',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = '__main__'
ASGI_APPLICATION = '__main__.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',  # In-memory database for simplicity
    }
}

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'transcription': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# =============================================================================
# DJANGO IMPORTS & INITIALIZATION
# =============================================================================

import django
from django.conf import settings
django.setup()

from django.http import HttpResponse
from django.urls import path, re_path
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.generic.websocket import AsyncWebsocketConsumer
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions, DeepgramClientOptions

logger = logging.getLogger('transcription')


# =============================================================================
# WEBSOCKET CONSUMER (BACKEND TRANSCRIPTION LOGIC)
# =============================================================================

class TranscriptionConsumer(AsyncWebsocketConsumer):
    """WebSocket Consumer for handling Deepgram live transcription."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deepgram_client = None
        self.deepgram_connection = None
        self.is_transcribing = False
        self.audio_buffer = bytearray()
        self.buffer_lock = asyncio.Lock()
        self.buffer_task = None

    async def connect(self):
        """Accept WebSocket connection and setup Deepgram client."""
        await self.accept()
        logger.info("Client connected")

        api_key = os.environ.get('DEEPGRAM_API_KEY')
        if not api_key:
            logger.error("DEEPGRAM_API_KEY not found in environment variables")
            await self.close(code=4000, reason="Missing API key")
            return

        # Validate API key format
        if not api_key.startswith('sha256'):
            logger.warning(f"API key format check: {api_key[:8]}... (expected format: sha256...)")
        else:
            logger.info(f"API key validated: {api_key[:8]}...")

        # Set up client configuration like the working Flask version
        config = DeepgramClientOptions(
            verbose=logging.WARN,
            options={"keepalive": "true"}
        )
        self.deepgram_client = DeepgramClient(api_key, config)
        logger.info("Deepgram client initialized with keepalive")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection and cleanup Deepgram connections."""
        logger.info(f"Client disconnected with code: {close_code}")

        if self.deepgram_connection:
            try:
                await self.deepgram_connection.finish()
                logger.info("Deepgram connection closed")
            except Exception as e:
                logger.error(f"Error closing Deepgram connection: {e}")

        # Clear audio buffer on disconnect
        async with self.buffer_lock:
            self.audio_buffer.clear()
            logger.info("Audio buffer cleared")

        self.is_transcribing = False

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages."""
        if text_data:
            try:
                data = json.loads(text_data)
                message_type = data.get('type')

                if message_type == 'toggle_transcription':
                    await self.handle_toggle_transcription()
                elif message_type == 'restart_deepgram':
                    await self.handle_restart_deepgram()
                else:
                    logger.warning(f"Unknown message type: {message_type}")

            except json.JSONDecodeError:
                logger.error("Invalid JSON received")

        elif bytes_data:
            print(f"📡 Received {len(bytes_data)} bytes")

            # Add audio data to buffer for decoupling
            async with self.buffer_lock:
                self.audio_buffer.extend(bytes_data)
                print(f"🧠 Buffer size: {len(self.audio_buffer)} bytes")

            # Send buffered audio if transcribing
            if self.is_transcribing and self.deepgram_connection:
                await self.process_audio_buffer()

    async def handle_toggle_transcription(self):
        """Toggle transcription on/off."""
        if self.is_transcribing:
            await self.stop_transcription()
        else:
            await self.start_transcription()

    async def start_transcription(self):
        """Start Deepgram live transcription."""
        try:
            logger.info("Starting Deepgram connection")
            await self.initialize_deepgram_connection()
            self.is_transcribing = True

            await self.send(text_data=json.dumps({
                'type': 'transcription_status',
                'status': 'started'
            }))

        except Exception as e:
            logger.error(f"Error starting transcription: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f"Failed to start transcription: {str(e)}"
            }))

    async def stop_transcription(self):
        """Stop Deepgram live transcription."""
        try:
            logger.info("Stopping transcription")

            if self.deepgram_connection:
                await self.deepgram_connection.finish()
                self.deepgram_connection = None

            # Clear audio buffer when stopping
            async with self.buffer_lock:
                self.audio_buffer.clear()
                logger.info("Audio buffer cleared on stop")

            self.is_transcribing = False

            await self.send(text_data=json.dumps({
                'type': 'transcription_status',
                'status': 'stopped'
            }))

        except Exception as e:
            logger.error(f"Error stopping transcription: {e}")

    async def handle_restart_deepgram(self):
        """Restart Deepgram connection."""
        logger.info("Restarting Deepgram connection")

        if self.is_transcribing:
            await self.stop_transcription()

        await asyncio.sleep(0.5)
        await self.start_transcription()

    async def process_audio_buffer(self):
        """Process buffered audio data and send to Deepgram."""
        try:
            buffer_data = None
            async with self.buffer_lock:
                if len(self.audio_buffer) > 0:
                    # Send buffer contents
                    buffer_data = bytes(self.audio_buffer)
                    self.audio_buffer.clear()  # Clear buffer after copying

            if buffer_data:
                await self.deepgram_connection.send(buffer_data)
                print(f"📤 Sent {len(buffer_data)} bytes to Deepgram")

        except Exception as e:
            print(f"❌ Error processing audio buffer: {e}")
            logger.error(f"Error processing audio buffer: {e}")

    async def initialize_deepgram_connection(self):
        """Initialize Deepgram live transcription connection."""
        try:
                        # Configure for audio from frontend MediaRecorder - let Deepgram auto-detect format
            options = LiveOptions(
                model="nova-3",
                language="en-US",
                interim_results=True
            )

            # Create live transcription connection
            self.deepgram_connection = self.deepgram_client.listen.asyncwebsocket.v("1")

            # Capture Django consumer reference for callbacks
            consumer = self

                        # Define standalone callback functions (like working examples)
            async def on_open(self, open, **kwargs):
                print("🟢 DEEPGRAM CONNECTION OPENED - Ready for audio!")
                print(f"🔍 Open event data: {open}")

            async def on_message(self, result, **kwargs):
                if result:
                    transcript = result.channel.alternatives[0].transcript
                    if transcript.strip():
                        print("=" * 50)
                        print("🎤 LIVE TRANSCRIPTION RESULT:")
                        print(f"📝 Text: '{transcript}'")
                        print(f"🔄 Final: {result.is_final}")
                        print("=" * 50)

                        # Send to Django WebSocket using captured consumer reference
                        import asyncio
                        asyncio.create_task(consumer.send(text_data=json.dumps({
                            'type': 'transcription_update',
                            'transcription': transcript
                        })))

            async def on_metadata(self, metadata, **kwargs):
                print(f"🆔 Metadata received")

            async def on_close(self, close, **kwargs):
                print(f"🔴 DEEPGRAM CONNECTION CLOSED: {close}")

            async def on_error(self, error, **kwargs):
                print(f"🔴 DEEPGRAM ERROR: {error}")

            async def on_unhandled(self, unhandled, **kwargs):
                print(f"🤷 UNHANDLED DEEPGRAM MESSAGE: {unhandled}")

            # Set up event handlers (exact same pattern as working examples)
            self.deepgram_connection.on(LiveTranscriptionEvents.Open, on_open)
            self.deepgram_connection.on(LiveTranscriptionEvents.Transcript, on_message)
            self.deepgram_connection.on(LiveTranscriptionEvents.Metadata, on_metadata)
            self.deepgram_connection.on(LiveTranscriptionEvents.Close, on_close)
            self.deepgram_connection.on(LiveTranscriptionEvents.Error, on_error)
            self.deepgram_connection.on(LiveTranscriptionEvents.Unhandled, on_unhandled)

            # Start the connection with detailed logging
            logger.info(f"Attempting to start Deepgram connection with options: {options}")
            try:
                addons = {"no_delay": "true"}
                connection_result = await self.deepgram_connection.start(options, addons=addons)
                logger.info(f"Deepgram start() returned: {connection_result}")

                if not connection_result:
                    logger.error("Deepgram connection start returned False")
                    raise Exception("Failed to start Deepgram connection - start() returned False")

                logger.info("Deepgram connection initialized successfully")

            except Exception as start_error:
                logger.error(f"Exception during Deepgram start(): {start_error}")
                logger.error(f"Exception type: {type(start_error)}")
                raise Exception(f"Failed to start Deepgram connection: {start_error}")

        except Exception as e:
            logger.error(f"Failed to initialize Deepgram connection: {e}")
            raise



# =============================================================================
# DJANGO VIEWS & URL ROUTING
# =============================================================================

def index_view(request):
    """Serve the main transcription page from index.html file."""
    html_file_path = BASE_DIR / 'index.html'
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HttpResponse(html_content)
    except FileNotFoundError:
        return HttpResponse("""
        <h1>Error: index.html not found</h1>
        <p>Please ensure index.html is in the same directory as app.py</p>
        """, status=500)

urlpatterns = [
    path('', index_view, name='home'),
]

# Add static file serving for development
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

# Add static files handling for development (disabled for testing)
# urlpatterns += staticfiles_urlpatterns()

# =============================================================================
# ASGI APPLICATION SETUP (WEBSOCKET ROUTING)
# =============================================================================

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter([
        re_path(r'ws/transcription/$', TranscriptionConsumer.as_asgi()),
    ]),
})

# =============================================================================
# MAIN EXECUTION & SERVER STARTUP
# =============================================================================
def main():
    """Main application entry point."""
    print("🎙️  Django Live Transcription Starter")
    print("=====================================")
    print("")

    api_key = check_api_key()
    print(f"✅ Deepgram API key loaded: {api_key[:8]}...")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("🚀 Starting ASGI/Channel Layer")
    print("📡 WebSocket endpoint: ws://localhost:8080/ws/transcription/")
    print("🌐 Web interface: http://localhost:8080/")
    print("")
    print("Press Ctrl+C to stop the server")
    print("")

    try:
        from daphne.server import Server
        from daphne.endpoints import build_endpoint_description_strings

        # Start daphne server directly
        server = Server(
            application=application,
            endpoints=build_endpoint_description_strings(host='0.0.0.0', port=8080),
            verbosity=1
        )
        server.run()
    except KeyboardInterrupt:
        print("")
        print("🛑 Server stopped")
        print("👋 Goodbye!")

if __name__ == '__main__':
    main()
