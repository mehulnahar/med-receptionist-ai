"""
Text-to-Speech integration — Chatterbox Turbo.

Supports streaming TTS (start speaking before full text is generated)
with natural filler phrases for EHR lookups.
"""

import asyncio
import base64
import logging
import time
from typing import AsyncIterator, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Natural filler phrases while waiting for backend operations
FILLER_PHRASES = {
    "en": [
        "Let me check that for you, one moment.",
        "Sure, let me look that up for you.",
        "Just a moment while I check our system.",
        "Let me pull that information up for you.",
    ],
    "es": [
        "Permitame verificar eso, un momento.",
        "Claro, permitame buscar esa informacion.",
        "Un momento mientras reviso nuestro sistema.",
        "Permitame buscar esa informacion para usted.",
    ],
}


class ChatterboxTTSClient:
    """Client for Chatterbox Turbo text-to-speech synthesis.

    Target latency: ~200ms for first audio chunk.
    """

    def __init__(self):
        settings = get_settings()
        self.endpoint = getattr(settings, "CHATTERBOX_ENDPOINT", "").strip()
        self.voice_id = getattr(settings, "CHATTERBOX_VOICE_ID", "professional-warm")
        self._client: Optional[httpx.AsyncClient] = None
        self._healthy = True
        self._filler_index = {"en": 0, "es": 0}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def synthesize(
        self,
        text: str,
        language: str = "en",
    ) -> Optional[bytes]:
        """Synthesize text to audio (batch mode).

        Returns raw audio bytes (PCM 16-bit, 16kHz) or None on failure.
        """
        if not text or not text.strip():
            return None

        start = time.monotonic()

        if self.endpoint and self._healthy:
            try:
                result = await self._synthesize_chatterbox(text, language)
                elapsed = (time.monotonic() - start) * 1000
                logger.debug("TTS chatterbox: %.0fms, text_len=%d", elapsed, len(text))
                return result
            except Exception as e:
                logger.warning("Chatterbox TTS failed: %s", e)
                self._healthy = False
                asyncio.create_task(self._health_check())

        # No fallback — log error
        logger.error("No TTS backend available for text: %s", text[:50])
        return None

    async def synthesize_stream(
        self,
        text: str,
        language: str = "en",
    ) -> AsyncIterator[bytes]:
        """Stream TTS audio as chunks arrive.

        Yields audio chunks as they become available.
        First chunk target: ~200ms.
        """
        if not text or not text.strip():
            return

        if self.endpoint and self._healthy:
            try:
                client = await self._get_client()
                async with client.stream(
                    "POST",
                    f"{self.endpoint}/synthesize/stream",
                    json={
                        "text": text,
                        "voice_id": self.voice_id,
                        "language": language,
                        "format": "pcm_16k",
                        "stream": True,
                    },
                    timeout=httpx.Timeout(30.0, connect=5.0),
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        yield chunk
                return
            except Exception as e:
                logger.warning("Chatterbox streaming TTS failed: %s", e)

    async def _synthesize_chatterbox(
        self,
        text: str,
        language: str,
    ) -> Optional[bytes]:
        """Send text to Chatterbox Turbo endpoint."""
        client = await self._get_client()
        response = await client.post(
            f"{self.endpoint}/synthesize",
            json={
                "text": text,
                "voice_id": self.voice_id,
                "language": language,
                "format": "pcm_16k",
            },
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
        response.raise_for_status()
        return response.content

    def get_filler_audio_text(self, language: str = "en") -> str:
        """Get the next filler phrase for when backend is processing."""
        phrases = FILLER_PHRASES.get(language, FILLER_PHRASES["en"])
        idx = self._filler_index.get(language, 0)
        phrase = phrases[idx % len(phrases)]
        self._filler_index[language] = idx + 1
        return phrase

    async def _health_check(self, _retries: int = 0) -> None:
        """Check if Chatterbox is back online."""
        max_retries = 10
        await asyncio.sleep(30 * min(_retries + 1, 5))
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.endpoint}/health",
                timeout=httpx.Timeout(5.0),
            )
            if response.status_code == 200:
                self._healthy = True
                logger.info("Chatterbox TTS is back online")
                return
        except Exception:
            pass

        if _retries < max_retries:
            asyncio.create_task(self._health_check(_retries + 1))
        else:
            logger.warning("Chatterbox TTS still down after %d retries, giving up", max_retries)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_tts_client: Optional[ChatterboxTTSClient] = None


def get_tts_client() -> ChatterboxTTSClient:
    global _tts_client
    if _tts_client is None:
        _tts_client = ChatterboxTTSClient()
    return _tts_client
