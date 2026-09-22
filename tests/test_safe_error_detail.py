import os
import unittest
import asyncio
import json

os.environ.setdefault("DEEPGRAM_API_KEY", "test-api-key")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from deepgram.core.api_error import ApiError
from starter.consumers import _raw_deepgram_frames, _safe_error_detail
from starter.consumers import LiveTranscriptionConsumer
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close


class SafeErrorDetailTests(unittest.TestCase):
    def test_api_error_does_not_expose_authorization_header(self):
        detail = _safe_error_detail(
            ApiError(
                status_code=401,
                headers={"Authorization": "Token FAKE"},
                body="invalid credentials",
            )
        )

        self.assertEqual(detail, "Deepgram rejected the connection (HTTP 401)")

    def test_connection_closed_preserves_safe_close_details(self):
        detail = _safe_error_detail(
            ConnectionClosed(Close(1011, "audio timeout"), None)
        )

        self.assertEqual(
            detail,
            "Deepgram closed the connection (code 1011: audio timeout)",
        )

    def test_control_frames_are_forwarded_to_deepgram(self):
        class Connection:
            def __init__(self):
                self.calls = []

            async def send_keep_alive(self):
                self.calls.append("KeepAlive")

            async def send_finalize(self):
                self.calls.append("Finalize")

            async def send_close_stream(self):
                self.calls.append("CloseStream")

        async def exercise():
            consumer = object.__new__(LiveTranscriptionConsumer)
            consumer.connection = Connection()
            consumer.close = lambda **_kwargs: None
            for control_type in ("KeepAlive", "Finalize", "CloseStream"):
                await consumer.receive(text_data=f'{{"type":"{control_type}"}}')
            return consumer.connection.calls

        self.assertEqual(
            asyncio.run(exercise()),
            ["KeepAlive", "Finalize", "CloseStream"],
        )

    def test_media_send_failure_reports_a_safe_provider_error(self):
        class Connection:
            async def send_media(self, _data):
                raise ConnectionClosed(Close(1011, "audio timeout"), None)

        async def exercise():
            consumer = object.__new__(LiveTranscriptionConsumer)
            consumer.connection = Connection()
            sent = []
            closed = []

            async def send(**kwargs):
                sent.append(kwargs)

            async def close(**kwargs):
                closed.append(kwargs)

            consumer.send = send
            consumer.close = close
            await consumer.receive(bytes_data=b"audio")
            return sent, closed

        sent, closed = asyncio.run(exercise())
        self.assertEqual(
            json.loads(sent[0]["text_data"]),
            {
                "type": "Error",
                "description": "Deepgram closed the connection (code 1011: audio timeout)",
                "code": "PROVIDER_ERROR",
            },
        )
        self.assertEqual(closed, [{"code": 3000}])

    def test_raw_deepgram_error_frames_reach_the_browser(self):
        class Socket:
            async def messages(self):
                yield '{"type":"Error","variant":"SchemaError","description":"Invalid control frame"}'

            def __aiter__(self):
                return self.messages()

        class Connection:
            _websocket = Socket()

        async def exercise():
            consumer = object.__new__(LiveTranscriptionConsumer)
            consumer.connection = Connection()
            sent = []

            async def send(**kwargs):
                sent.append(kwargs)

            async def close(**_kwargs):
                pass

            consumer.send = send
            consumer.close = close
            await consumer.forward_from_deepgram()
            return sent

        self.assertEqual(
            asyncio.run(exercise()),
            [{"text_data": '{"type":"Error","variant":"SchemaError","description":"Invalid control frame"}'}],
        )

    def test_plain_dictionary_frames_are_forwarded_unchanged(self):
        class Connection:
            class Socket:
                async def messages(self):
                    yield {"type": "Results", "channel": {"alternatives": []}}

                def __aiter__(self):
                    return self.messages()

            _websocket = Socket()

        async def exercise():
            consumer = object.__new__(LiveTranscriptionConsumer)
            consumer.connection = Connection()
            sent = []

            async def send(**kwargs):
                sent.append(kwargs)

            async def close(**_kwargs):
                pass

            consumer.send = send
            consumer.close = close
            await consumer.forward_from_deepgram()
            return sent

        self.assertEqual(
            asyncio.run(exercise()),
            [{"text_data": '{"type": "Results", "channel": {"alternatives": []}}'}],
        )

    def test_missing_private_transport_fails_loudly(self):
        async def exercise():
            async for _ in _raw_deepgram_frames(object()):
                pass

        with self.assertRaisesRegex(RuntimeError, "private _websocket transport"):
            asyncio.run(exercise())

    def test_missing_private_transport_has_a_browser_safe_error(self):
        error = RuntimeError(
            "Deepgram SDK connection does not expose the private _websocket transport "
            "needed to preserve raw transcription frames"
        )

        self.assertEqual(
            _safe_error_detail(error),
            "Deepgram SDK raw frame transport is unavailable",
        )
