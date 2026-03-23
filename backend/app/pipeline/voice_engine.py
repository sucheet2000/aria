"""
voice_engine.py — Dynamic prosody engine for ARIA TTS.

Maps emotional context from the neurosymbolic reasoning layer to
ElevenLabs voice_settings and v3 audio tags. Designed to be called
per-response with near-zero latency overhead (dict lookups + random.uniform).

Usage:
    from app.pipeline.voice_engine import voice_engine

    payload = voice_engine.build_request_payload(
        text=response_text,
        voice_id=VOICE_ID,
        emotion=avatar_emotion,  # from CognitionResponse
    )
    # POST payload to /v1/text-to-speech/{voice_id}/stream
"""
from __future__ import annotations

import random

import structlog

logger = structlog.get_logger()

# --- Emotion voice profiles ---
# Each profile maps to ElevenLabs voice_settings parameters.
# stability: 0.0 (variable/expressive) to 1.0 (steady/robotic)
# similarity_boost: 0.0 to 1.0 — how closely to match the original voice
# style: 0.0 to 1.0 — style exaggeration (eleven_turbo_v2_5+ only)
# use_speaker_boost: enhances similarity at slight latency cost

EMOTION_VOICE_PROFILES: dict[str, dict] = {
    "focused": {
        "stability": 0.75,
        "similarity_boost": 0.80,
        "style": 0.15,
        "use_speaker_boost": True,
    },
    "distressed": {
        "stability": 0.55,
        "similarity_boost": 0.75,
        "style": 0.30,
        "use_speaker_boost": True,
    },
    "exploring": {
        "stability": 0.65,
        "similarity_boost": 0.78,
        "style": 0.25,
        "use_speaker_boost": True,
    },
    "blocked": {
        "stability": 0.60,
        "similarity_boost": 0.72,
        "style": 0.20,
        "use_speaker_boost": True,
    },
    "idle": {
        "stability": 0.80,
        "similarity_boost": 0.75,
        "style": 0.10,
        "use_speaker_boost": True,
    },
    # Emotion classifier outputs (mapped from vision pipeline)
    "happy": {
        "stability": 0.65,
        "similarity_boost": 0.80,
        "style": 0.30,
        "use_speaker_boost": True,
    },
    "sad": {
        "stability": 0.60,
        "similarity_boost": 0.72,
        "style": 0.25,
        "use_speaker_boost": True,
    },
    "angry": {
        "stability": 0.55,
        "similarity_boost": 0.70,
        "style": 0.20,
        "use_speaker_boost": True,
    },
    "fearful": {
        "stability": 0.55,
        "similarity_boost": 0.72,
        "style": 0.28,
        "use_speaker_boost": True,
    },
    "surprised": {
        "stability": 0.60,
        "similarity_boost": 0.78,
        "style": 0.35,
        "use_speaker_boost": True,
    },
    "disgusted": {
        "stability": 0.65,
        "similarity_boost": 0.70,
        "style": 0.15,
        "use_speaker_boost": True,
    },
    "neutral": {
        "stability": 0.80,
        "similarity_boost": 0.75,
        "style": 0.10,
        "use_speaker_boost": True,
    },
}

DEFAULT_PROFILE = EMOTION_VOICE_PROFILES["idle"]

JITTER_RANGE = 0.05  # +/- applied to stability for human variability

# --- Prosody tag mappings ---
# ElevenLabs v3 audio tags for eleven_turbo_v2_5 and newer models.
# Applied as prefix tags before the spoken text.

PROSODY_TAG_MAP: dict[str, str] = {
    "distressed": "[softly]",
    "fearful":    "[softly]",
    "sad":        "[softly]",
    "exploring":  "[excitedly]",
    "surprised":  "[excitedly]",
    "happy":      "[cheerfully]",
    "focused":    "",            # no tag — clear and direct
    "blocked":    "[thoughtfully]",
    "angry":      "[calmly]",    # de-escalate
    "disgusted":  "[calmly]",
    "neutral":    "",
    "idle":       "",
}

# Suffix tags for natural sentence endings
PAUSE_TAG = " [thoughtful pause]"


class VoiceEngine:
    """
    Maps emotional context to ElevenLabs voice settings and prosody tags.
    Designed as a stateless utility — instantiate once and call per response.
    """

    MODEL_ID = "eleven_turbo_v2_5"
    # Fallback model if turbo not available on account
    FALLBACK_MODEL_ID = "eleven_monolingual_v1"

    def get_voice_settings(self, emotion: str | None) -> dict:
        """
        Return voice_settings dict for the given emotion label.
        Applies stability jitter for human variability.
        Falls back to idle profile on unknown or None emotion.
        """
        emotion_key = (emotion or "idle").lower().strip()
        profile = EMOTION_VOICE_PROFILES.get(emotion_key, DEFAULT_PROFILE)

        # Deep copy to avoid mutating the profile constant
        settings = dict(profile)

        # Apply stability jitter — ARIA never sounds exactly the same twice
        jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
        settings["stability"] = round(
            max(0.0, min(1.0, settings["stability"] + jitter)), 3
        )

        logger.debug(
            "voice settings resolved",
            emotion=emotion_key,
            stability=settings["stability"],
            style=settings["style"],
            jitter=round(jitter, 3),
        )

        return settings

    def apply_prosody_tags(self, text: str, emotion: str | None) -> str:
        """
        Wrap text in ElevenLabs v3 audio tags based on emotion.
        Only applies tags when using eleven_turbo_v2_5 or newer.

        Rules:
        - Prefix tag sets the emotional register for the whole response
        - Thoughtful pause added before questions to create natural pacing
        - Tags are stripped from very short responses (under 20 chars)
          to avoid awkward single-word wrapping

        Returns the tagged text ready for the ElevenLabs API.
        """
        if not text or not text.strip():
            return text

        emotion_key = (emotion or "idle").lower().strip()
        prefix_tag = PROSODY_TAG_MAP.get(emotion_key, "")

        # Do not tag very short responses
        if len(text.strip()) < 20:
            return text

        # Apply prefix tag
        tagged = f"{prefix_tag} {text.strip()}" if prefix_tag else text.strip()

        # Add thoughtful pause before questions to create natural pacing
        # Replace "?" with "[thoughtful pause]?" only for the final question
        if tagged.endswith("?"):
            tagged = tagged[:-1] + PAUSE_TAG + "?"

        return tagged

    def build_request_payload(
        self,
        text: str,
        voice_id: str,
        emotion: str | None = None,
        use_turbo: bool = True,
    ) -> dict:
        """
        Build the complete ElevenLabs API request payload.
        Applies prosody tags and voice settings based on emotion.

        Args:
            text: The natural language response from Claude
            voice_id: ElevenLabs voice ID
            emotion: Emotion label from symbolic_inference or avatar_emotion
            use_turbo: If True, uses eleven_turbo_v2_5 with audio tags.
                       If False, falls back to eleven_monolingual_v1 (no tags).

        Returns dict ready to be JSON-serialized as the request body.
        """
        model_id = self.MODEL_ID if use_turbo else self.FALLBACK_MODEL_ID
        voice_settings = self.get_voice_settings(emotion)

        # Only apply prosody tags on turbo model (v3 tags not supported on v1)
        if use_turbo:
            spoken_text = self.apply_prosody_tags(text, emotion)
        else:
            spoken_text = text

        return {
            "text": spoken_text,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }


# Module-level singleton for use across the application
voice_engine = VoiceEngine()
