"""WebSocket consumer for Live Transcription - Raw WebSocket proxy to Deepgram"""
import os
import json
import asyncio
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
import websockets
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get("DEEPGRAM_API_KEY")
if not API_KEY:
    raise ValueError("DEEPGRAM_API_KEY required")

DEEPGRAM_STT_URL = "wss://api.deepgram.com/v1/listen"

class LiveTranscriptionConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deepgram_ws = None
        self.forward_task = None
        self.stop_event = asyncio.Event()

    async def connect(self):
        """Accept WebSocket connection from client"""
        await self.accept()
        print("Client connected to /stt/stream")

        # Parse query parameters from scope
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        params = parse_qs(query_string)

        model = params.get('model', ['nova-2'])[0]
        language = params.get('language', ['en'])[0]
        smart_format = params.get('smart_format', ['true'])[0]
        interim_results = params.get('interim_results', ['true'])[0]
        punctuate = params.get('punctuate', ['true'])[0]
        encoding = params.get('encoding', ['linear16'])[0]
        sample_rate = params.get('sample_rate', ['16000'])[0]

        # Build Deepgram WebSocket URL with parameters
        deepgram_url = (
            f"{DEEPGRAM_STT_URL}?"
            f"model={model}&"
            f"language={language}&"
            f"smart_format={smart_format}&"
            f"interim_results={interim_results}&"
            f"punctuate={punctuate}&"
            f"encoding={encoding}&"
            f"sample_rate={sample_rate}"
        )

        print(f"Connecting to Deepgram STT: model={model}, language={language}")

        try:
            # Connect to Deepgram
            self.deepgram_ws = await websockets.connect(
                deepgram_url,
                additional_headers={"Authorization": f"Token {API_KEY}"}
            )
            print("✓ Connected to Deepgram STT API")

            # Start forwarding task
            self.forward_task = asyncio.create_task(self.forward_from_deepgram())

        except Exception as e:
            print(f"Error connecting to Deepgram: {e}")
            await self.send(text_data=json.dumps({
                "type": "Error",
                "description": str(e),
                "code": "CONNECTION_FAILED"
            }))
            await self.close(code=3000)

    async def disconnect(self, close_code):
        """Cleanup on disconnect"""
        print(f"Client disconnected: {close_code}")
        self.stop_event.set()

        if self.forward_task:
            self.forward_task.cancel()
            try:
                await self.forward_task
            except asyncio.CancelledError:
                pass

        if self.deepgram_ws:
            try:
                await self.deepgram_ws.close()
            except Exception as e:
                print(f"Error closing Deepgram connection: {e}")

    async def receive(self, text_data=None, bytes_data=None):
        """Forward messages from client to Deepgram"""
        if not self.deepgram_ws:
            return

        try:
            if text_data:
                await self.deepgram_ws.send(text_data)
            elif bytes_data:
                await self.deepgram_ws.send(bytes_data)
        except Exception as e:
            print(f"Error forwarding to Deepgram: {e}")
            await self.close(code=3000)

    async def forward_from_deepgram(self):
        """Forward messages from Deepgram to client"""
        try:
            async for message in self.deepgram_ws:
                if self.stop_event.is_set():
                    break

                # Forward binary or text messages
                if isinstance(message, bytes):
                    await self.send(bytes_data=message)
                else:
                    await self.send(text_data=message)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"Deepgram connection closed: {e.code} {e.reason}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error forwarding from Deepgram: {e}")
            await self.send(text_data=json.dumps({
                "type": "Error",
                "description": str(e),
                "code": "PROVIDER_ERROR"
            }))
        finally:
            if not self.stop_event.is_set():
                await self.close(code=1000)
