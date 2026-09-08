import os
import unittest
import asyncio

os.environ.setdefault("DEEPGRAM_API_KEY", "test-api-key")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from deepgram.core.api_error import ApiError
from starter.consumers import _safe_error_detail
from starter.consumers import LiveTranscriptionConsumer


class SafeErrorDetailTests(unittest.TestCase):
    def test_api_error_does_not_expose_authorization_header(self):
        detail = _safe_error_detail(
            ApiError(
                status_code=401,
                headers={"Authorization": "Token FAKE"},
                body="invalid credentials",
            )
        )

        self.assertIn("HTTP 401", detail)
        self.assertNotIn("FAKE", detail)

    def test_unmodeled_sdk_frames_are_ignored(self):
        class Connection:
            async def messages(self):
                yield None

            def __aiter__(self):
                return self.messages()

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

        self.assertEqual(asyncio.run(exercise()), [])
