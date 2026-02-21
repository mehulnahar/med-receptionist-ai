"""
Speech-to-Text integration — Whisper Medical model.

Supports:
  - Self-hosted Whisper Medical on AWS GPU (primary)
  - OpenAI Whisper API (fallback)
"""

import asyncio
import base64
import logging
import time
from typing import AsyncIterator, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WhisperSTTClient:
    """Client for Whisper Medical speech-to-text transcription.

    Supports streaming transcription (process chunks as they arrive)
    and batch transcription (full audio file).
    """

    def __init__(self):
        settings = get_settings()
        self.endpoint = getattr(settings, "WHISPER_ENDPOINT", "").strip()
        self.model_name = getattr(settings, "WHISPER_MODEL_NAME", "whisper-medical-v1")
        self.openai_api_key = getattr(settings, "OPENAI_API_KEY", "").strip()
        self._client: Optional[httpx.AsyncClient] = None
        self._healthy = True

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def transcribe_chunk(
        self,
        audio_data: bytes,
        language: str = "en",
        sample_rate: int = 16000,
    ) -> Optional[str]:
        """Transcribe an audio chunk (streaming mode).

        Returns the transcribed text or None on failure.
        Target latency: 50-150ms.
        """
        start = time.monotonic()

        # Try self-hosted first
        if self.endpoint and self._healthy:
            try:
                result = await self._transcribe_self_hosted(
                    audio_data, language, sample_rate
                )
                elapsed = (time.monotonic() - start) * 1000
                logger.debug("STT self-hosted: %.0fms, text='%s'", elapsed, result[:50] if result else "")
                return result
            except Exception as e:
                logger.warning("Self-hosted Whisper failed, falling back to OpenAI: %s", e)
                self._healthy = False
                # Schedule health check to re-enable
                asyncio.create_task(self._health_check())

        # Fallback to OpenAI Whisper API
        if self.openai_api_key:
            try:
                result = await self._transcribe_openai(audio_data, language)
                elapsed = (time.monotonic() - start) * 1000
                logger.debug("STT OpenAI: %.0fms, text='%s'", elapsed, result[:50] if result else "")
                return result
            except Exception as e:
                logger.error("OpenAI Whisper fallback also failed: %s", e)

        logger.error("No STT backend available")
        return None

    async def _transcribe_self_hosted(
        self,
        audio_data: bytes,
        language: str,
        sample_rate: int,
    ) -> Optional[str]:
        """Send audio to self-hosted Whisper Medical endpoint."""
        client = await self._get_client()
        response = await client.post(
            f"{self.endpoint}/transcribe",
            json={
                "audio": base64.b64encode(audio_data).decode("ascii"),
                "language": language,
                "sample_rate": sample_rate,
                "model": self.model_name,
                "task": "transcribe",
            },
            timeout=httpx.Timeout(5.0, connect=2.0),
        )
        response.raise_for_status()
        data = response.json()
        return data.get("text", "").strip()

    async def _transcribe_openai(
        self,
        audio_data: bytes,
        language: str,
    ) -> Optional[str]:
        """Fallback to OpenAI Whisper API."""
        client = await self._get_client()
        # OpenAI expects multipart form data with a file
        import io
        files = {
            "file": ("audio.wav", io.BytesIO(audio_data), "audio/wav"),
        }
        data = {
            "model": "whisper-1",
            "language": language,
            "response_format": "json",
        }
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()

    async def _health_check(self, _retries: int = 0) -> None:
        """Periodically check if self-hosted Whisper is back online."""
        max_retries = 10
        await asyncio.sleep(30 * min(_retries + 1, 5))  # Exponential backoff, max 150s
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.endpoint}/health",
                timeout=httpx.Timeout(5.0),
            )
            if response.status_code == 200:
                self._healthy = True
                logger.info("Self-hosted Whisper is back online")
                return
        except Exception:
            pass

        if _retries < max_retries:
            asyncio.create_task(self._health_check(_retries + 1))
        else:
            logger.warning("Self-hosted Whisper still down after %d retries, giving up", max_retries)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton instance
_stt_client: Optional[WhisperSTTClient] = None


def get_stt_client() -> WhisperSTTClient:
    global _stt_client
    if _stt_client is None:
        _stt_client = WhisperSTTClient()
    return _stt_client
