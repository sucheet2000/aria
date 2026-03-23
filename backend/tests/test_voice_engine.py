from __future__ import annotations

import pytest

from app.pipeline.voice_engine import (
    DEFAULT_PROFILE,
    EMOTION_VOICE_PROFILES,
    VoiceEngine,
    voice_engine,
)


# ---------------------------------------------------------------------------
# get_voice_settings
# ---------------------------------------------------------------------------


class TestGetVoiceSettings:
    def test_returns_required_keys(self) -> None:
        settings = voice_engine.get_voice_settings("focused")
        assert "stability" in settings
        assert "similarity_boost" in settings
        assert "style" in settings
        assert "use_speaker_boost" in settings

    @pytest.mark.parametrize("emotion", list(EMOTION_VOICE_PROFILES.keys()))
    def test_stability_within_bounds_for_all_emotions(self, emotion: str) -> None:
        for _ in range(10):
            settings = voice_engine.get_voice_settings(emotion)
            assert 0.0 <= settings["stability"] <= 1.0, (
                f"stability out of range for emotion={emotion!r}: {settings['stability']}"
            )

    def test_unknown_emotion_returns_idle_profile(self) -> None:
        settings = voice_engine.get_voice_settings("nonexistent_emotion_xyz")
        assert settings["similarity_boost"] == pytest.approx(
            DEFAULT_PROFILE["similarity_boost"], abs=1e-9
        )
        assert settings["style"] == DEFAULT_PROFILE["style"]
        assert settings["use_speaker_boost"] == DEFAULT_PROFILE["use_speaker_boost"]

    def test_none_emotion_returns_idle_profile(self) -> None:
        settings = voice_engine.get_voice_settings(None)
        assert settings["style"] == DEFAULT_PROFILE["style"]
        assert settings["use_speaker_boost"] == DEFAULT_PROFILE["use_speaker_boost"]

    def test_stability_varies_across_calls(self) -> None:
        stabilities = {voice_engine.get_voice_settings("idle")["stability"] for _ in range(100)}
        assert len(stabilities) > 1, "stability should vary due to jitter"

    def test_does_not_mutate_profile_constant(self) -> None:
        original = EMOTION_VOICE_PROFILES["happy"]["stability"]
        for _ in range(20):
            voice_engine.get_voice_settings("happy")
        assert EMOTION_VOICE_PROFILES["happy"]["stability"] == original


# ---------------------------------------------------------------------------
# apply_prosody_tags
# ---------------------------------------------------------------------------


class TestApplyProsodyTags:
    def test_distressed_adds_softly_prefix(self) -> None:
        result = voice_engine.apply_prosody_tags("I am feeling overwhelmed right now.", "distressed")
        assert result.startswith("[softly]")

    def test_exploring_adds_excitedly_prefix(self) -> None:
        result = voice_engine.apply_prosody_tags("Let me look into that more carefully.", "exploring")
        assert result.startswith("[excitedly]")

    def test_neutral_adds_no_prefix(self) -> None:
        text = "Here is the information you requested."
        result = voice_engine.apply_prosody_tags(text, "neutral")
        assert result == text

    def test_short_text_returned_unchanged(self) -> None:
        short = "Yes."
        result = voice_engine.apply_prosody_tags(short, "distressed")
        assert result == short

    def test_question_gets_thoughtful_pause(self) -> None:
        text = "Would you like me to continue with this approach?"
        result = voice_engine.apply_prosody_tags(text, "neutral")
        assert "[thoughtful pause]?" in result
        assert result.endswith("?")

    def test_none_emotion_falls_back_to_idle_no_tag(self) -> None:
        text = "Here is the answer to your question about this topic."
        result = voice_engine.apply_prosody_tags(text, None)
        assert result == text

    def test_empty_text_returned_unchanged(self) -> None:
        assert voice_engine.apply_prosody_tags("", "happy") == ""
        assert voice_engine.apply_prosody_tags("   ", "happy") == "   "

    def test_focused_emotion_adds_no_prefix(self) -> None:
        text = "Processing your request now, please stand by."
        result = voice_engine.apply_prosody_tags(text, "focused")
        assert result == text

    def test_sad_adds_softly_prefix(self) -> None:
        result = voice_engine.apply_prosody_tags("I understand how difficult this must be.", "sad")
        assert result.startswith("[softly]")


# ---------------------------------------------------------------------------
# build_request_payload
# ---------------------------------------------------------------------------


class TestBuildRequestPayload:
    def test_returns_required_keys(self) -> None:
        payload = voice_engine.build_request_payload(
            text="Hello there.", voice_id="abc", emotion="neutral"
        )
        assert "text" in payload
        assert "model_id" in payload
        assert "voice_settings" in payload

    def test_use_turbo_true_uses_turbo_model(self) -> None:
        payload = voice_engine.build_request_payload(
            text="Hello there.", voice_id="abc", use_turbo=True
        )
        assert payload["model_id"] == VoiceEngine.MODEL_ID

    def test_use_turbo_false_uses_fallback_model(self) -> None:
        payload = voice_engine.build_request_payload(
            text="Hello there.", voice_id="abc", use_turbo=False
        )
        assert payload["model_id"] == VoiceEngine.FALLBACK_MODEL_ID

    def test_use_turbo_false_does_not_apply_prosody_tags(self) -> None:
        text = "I am feeling overwhelmed and need your assistance here."
        payload = voice_engine.build_request_payload(
            text=text, voice_id="abc", emotion="distressed", use_turbo=False
        )
        assert payload["text"] == text

    def test_use_turbo_true_applies_prosody_tags_for_distressed(self) -> None:
        text = "I am feeling overwhelmed and need your assistance here."
        payload = voice_engine.build_request_payload(
            text=text, voice_id="abc", emotion="distressed", use_turbo=True
        )
        assert payload["text"].startswith("[softly]")

    def test_emotion_passed_to_voice_settings(self) -> None:
        angry_payload = voice_engine.build_request_payload(
            text="Hello.", voice_id="abc", emotion="angry", use_turbo=False
        )
        idle_payload = voice_engine.build_request_payload(
            text="Hello.", voice_id="abc", emotion="idle", use_turbo=False
        )
        # angry stability base (0.55) differs from idle base (0.80); with jitter
        # they are very unlikely to be equal — but we check style instead (no jitter)
        assert angry_payload["voice_settings"]["style"] != idle_payload["voice_settings"]["style"]

    def test_voice_settings_has_required_keys(self) -> None:
        payload = voice_engine.build_request_payload(
            text="Hello.", voice_id="abc", emotion="happy"
        )
        vs = payload["voice_settings"]
        assert "stability" in vs
        assert "similarity_boost" in vs
        assert "style" in vs
        assert "use_speaker_boost" in vs
