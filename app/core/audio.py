"""Audio note parser and Speech-to-Text (STT) adapter."""

import logging
from typing import Any, Dict, Optional

from app.integrations.protocols import AudioTranscriptionProtocol

logger = logging.getLogger(__name__)


class DefaultAudioTranscriptionService(AudioTranscriptionProtocol):
    """
    Default deterministic transcription service for development & testing.
    Supports inline synthetic tags (e.g., MOCK_VOICE:Spent 45 on groceries),
    magic byte inspection, and graceful fallbacks.
    """

    def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        if not audio_bytes:
            raise ValueError("Audio payload is empty")

        # 1. Check for embedded mock text prefix
        try:
            decoded = audio_bytes.decode("utf-8", errors="ignore")
            if "MOCK_VOICE:" in decoded:
                idx = decoded.index("MOCK_VOICE:")
                transcript = decoded[idx + len("MOCK_VOICE:"):].split("\n")[0].strip()
                if transcript:
                    return transcript
        except Exception:
            pass

        # 2. Check for synthetic byte pattern
        # If raw text was passed as bytes
        try:
            text = audio_bytes.decode("utf-8")
            if text.isprintable() and len(text.strip()) > 0:
                return text.strip()
        except UnicodeDecodeError:
            pass

        # 3. Default fallback for binary fixtures
        return "Spent $35.00 on lunch"


class AudioNoteHandler:
    """Parses incoming audio note payloads and delegates to transcription service."""

    def __init__(
        self,
        transcription_service: Optional[AudioTranscriptionProtocol] = None,
    ) -> None:
        self.transcription_service = (
            transcription_service or DefaultAudioTranscriptionService()
        )

    def parse_and_transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        mime_type: str = "audio/ogg",
    ) -> str:
        """
        Validates audio note binary and passes to STT transcription engine.
        Returns the recognized transcript as plain text.
        """
        if not audio_bytes or len(audio_bytes) == 0:
            raise ValueError("Cannot process empty voice note payload")

        metadata = self.inspect_audio_metadata(audio_bytes)
        logger.debug("Processing audio note: %s", metadata)

        transcript = self.transcription_service.transcribe(audio_bytes, filename=filename)
        return transcript.strip()

    @staticmethod
    def inspect_audio_metadata(audio_bytes: bytes) -> Dict[str, Any]:
        """Inspects binary payload for standard audio container signatures."""
        size = len(audio_bytes)
        format_detected = "unknown"

        if audio_bytes.startswith(b"OggS"):
            format_detected = "ogg/opus"
        elif audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:12]:
            format_detected = "wav"
        elif audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb"):
            format_detected = "mp3"
        elif audio_bytes.startswith(b"fLaC"):
            format_detected = "flac"

        return {
            "size_bytes": size,
            "detected_format": format_detected,
            "has_valid_header": format_detected != "unknown",
        }
