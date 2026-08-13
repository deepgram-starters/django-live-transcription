"""WebSocket consumer for Live Transcription — bridges the browser to Deepgram listen.v1 via the SDK."""
import os
import json
import asyncio
from urllib.parse import parse_qs

import jwt
from channels.generic.websocket import AsyncWebsocketConsumer
from dotenv import load_dotenv

from deepgram import AsyncDeepgramClient
from deepgram.environment import DeepgramClientEnvironment
from deepgram.core.api_error import ApiError
from starter.views import SESSION_SECRET

load_dotenv()
API_KEY = os.environ.get("DEEPGRAM_API_KEY")
if not API_KEY:
    raise ValueError("DEEPGRAM_API_KEY required")


# One async SDK client, reused across connections; the browser never sees the API key.
# DEEPGRAM_BASE_URL (e.g. wss://api.staging.deepgram.com) overrides the default
# production endpoint. listen.v1 uses environment.production for the /v1/listen ws.
def _build_client():
    base_url = os.environ.get("DEEPGRAM_BASE_URL")
    if base_url:
        https = base_url.replace("wss://", "https://").replace("ws://", "http://")
        env = DeepgramClientEnvironment(
            base=https, production=base_url, agent=base_url, agent_rest=https
        )
        print(f"Using custom Deepgram base URL: {base_url}")
        return AsyncDeepgramClient(api_key=API_KEY, environment=env)
    return AsyncDeepgramClient(api_key=API_KEY)


deepgram = _build_client()


def _safe_error_detail(e):
    """Build a browser-safe (and log-safe) description of a Deepgram error.

    NEVER surface str(e): a deepgram-sdk ApiError stringifies its request
    headers, which include `Authorization: Token <api-key>`. Forwarding that
    to the browser (or writing it to logs) leaks the API key, so we only ever
    expose the exception's HTTP status or type name.
    """
    if isinstance(e, ApiError):
        return f"Deepgram rejected the connection (HTTP {e.status_code})"
    return f"Failed to connect to Deepgram ({type(e).__name__})"


class LiveTranscriptionConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection = None
        self._connection_cm = None
        self.forward_task = None

    async def connect(self):
        """Accept WebSocket connection from client"""
        # Validate JWT from subprotocol
        protocols = self.scope.get("subprotocols", [])
        valid_proto = None
        for proto in protocols:
            if proto.startswith("access_token."):
                token = proto[len("access_token."):]
                try:
                    jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
                    valid_proto = proto
                except Exception:
                    pass
                break

        if not valid_proto:
            await self.close(code=4401)
            return

        await self.accept(subprotocol=valid_proto)
        print("Client connected to /api/live-transcription")

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

        print(f"Connecting to Deepgram STT: model={model}, language={language}")

        try:
            # `connect()` is an async context manager; enter it manually so the
            # connection lives across the consumer's connect/disconnect lifecycle.
            self._connection_cm = deepgram.listen.v1.connect(
                model=model,
                language=language,
                smart_format=smart_format,
                interim_results=interim_results,
                punctuate=punctuate,
                encoding=encoding,
                sample_rate=sample_rate,
            )
            self.connection = await self._connection_cm.__aenter__()
            print("Connected to Deepgram STT API")

            self.forward_task = asyncio.create_task(self.forward_from_deepgram())

        except Exception as e:
            detail = _safe_error_detail(e)
            print(f"Error connecting to Deepgram: {detail}")
            await self.send(text_data=json.dumps({
                "type": "Error",
                "description": detail,
                "code": "CONNECTION_FAILED"
            }))
            await self.close(code=3000)

    async def disconnect(self, close_code):
        """Cleanup on disconnect"""
        print(f"Client disconnected: {close_code}")

        if self.forward_task:
            self.forward_task.cancel()
            try:
                await self.forward_task
            except asyncio.CancelledError:
                pass

        if self._connection_cm:
            try:
                await self._connection_cm.__aexit__(None, None, None)
            except Exception as e:
                print(f"Error closing Deepgram connection: {_safe_error_detail(e)}")

    async def receive(self, text_data=None, bytes_data=None):
        """Forward audio from client to Deepgram"""
        if not self.connection:
            return

        try:
            if bytes_data:
                await self.connection.send_media(bytes_data)
            elif text_data:
                # The frontend streams raw audio only; ignore any stray text frames.
                print("Ignoring unexpected text message from client")
        except Exception as e:
            print(f"Error forwarding to Deepgram: {_safe_error_detail(e)}")
            await self.close(code=3000)

    async def forward_from_deepgram(self):
        """Forward Deepgram messages to the browser: bytes as binary, models as JSON."""
        try:
            async for message in self.connection:
                if isinstance(message, (bytes, bytearray)):
                    await self.send(bytes_data=bytes(message))
                elif isinstance(message, dict):
                    # listen.v2's socket iterator yields raw bytes OR
                    # construct_type(...) over a union that includes typing.Any,
                    # so plain dicts legitimately arrive and must be forwarded
                    # intact (a dict has no model_dump_json / .type).
                    await self.send(text_data=json.dumps(message))
                elif hasattr(message, "model_dump_json"):
                    await self.send(text_data=message.model_dump_json())
                else:
                    await self.send(text_data=json.dumps(
                        {"type": getattr(message, "type", "Unknown")}
                    ))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            detail = _safe_error_detail(e)
            print(f"Error forwarding from Deepgram: {detail}")
            try:
                await self.send(text_data=json.dumps({
                    "type": "Error",
                    "description": detail,
                    "code": "PROVIDER_ERROR"
                }))
            except Exception:
                pass
        finally:
            try:
                await self.close(code=1000)
            except Exception:
                pass
