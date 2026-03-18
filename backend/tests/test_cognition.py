from __future__ import annotations

import pytest

from app.cognition.conflict import detect_conflict, speech_sentiment, visual_sentiment
from app.cognition.prompt import CONFLICT_INSTRUCTION, NO_CONFLICT_INSTRUCTION, build_system_prompt
from app.models.schemas import SymbolicResponse, VisionContext, WorldModelTriple, WorldModelUpdate


# --- speech_sentiment ---

def test_speech_sentiment_positive():
    score = speech_sentiment("I am happy and everything is great")
    assert score > 0.0


def test_speech_sentiment_negative():
    score = speech_sentiment("I am frustrated and stuck")
    assert score < 0.0


def test_speech_sentiment_neutral():
    score = speech_sentiment("hello there")
    assert score == 0.0


# --- visual_sentiment ---

def test_visual_sentiment_positive():
    assert visual_sentiment("happy", 0.9) == 0.9


def test_visual_sentiment_negative():
    assert visual_sentiment("fearful", 0.8) == -0.8


def test_visual_sentiment_neutral():
    assert visual_sentiment("neutral", 1.0) == 0.0


# --- detect_conflict ---

def test_detect_conflict_positive_speech_negative_visual():
    conflict, delta = detect_conflict("I am fine", "fearful", 0.8)
    assert conflict is True
    assert delta >= 0.4


def test_detect_conflict_aligned_negative():
    conflict, delta = detect_conflict("I am frustrated", "angry", 0.7)
    assert conflict is False


# --- build_system_prompt ---

def test_build_system_prompt_contains_aria():
    vision = VisionContext(emotion="neutral", confidence=0.5)
    prompt = build_system_prompt(vision, "hello", [], [])
    assert "ARIA" in prompt


def test_build_system_prompt_contains_emotion():
    vision = VisionContext(emotion="happy", confidence=0.9)
    prompt = build_system_prompt(vision, "hello", [], [])
    assert "happy" in prompt


def test_build_system_prompt_conflict_instruction_when_conflict():
    vision = VisionContext(emotion="fearful", confidence=0.8)
    prompt = build_system_prompt(vision, "I am fine", [], [])
    assert CONFLICT_INSTRUCTION in prompt


def test_build_system_prompt_no_conflict_instruction_when_aligned():
    vision = VisionContext(emotion="angry", confidence=0.7)
    prompt = build_system_prompt(vision, "I am frustrated", [], [])
    assert NO_CONFLICT_INSTRUCTION in prompt


# --- SymbolicResponse schema ---

def test_symbolic_response_minimal():
    sr = SymbolicResponse(
        symbolic_inference="user is focused",
        natural_language_response="Got it.",
    )
    assert sr.world_model_update is None
    assert sr.symbolic_inference == "user is focused"


def test_symbolic_response_with_world_model_update():
    triple = WorldModelTriple(subject="user", predicate="prefers", object="dark mode")
    wmu = WorldModelUpdate(triple=triple, confidence=0.9, source="explicit_statement")
    sr = SymbolicResponse(
        symbolic_inference="user stated a preference",
        world_model_update=wmu,
        natural_language_response="Noted.",
    )
    assert sr.world_model_update is not None
    assert sr.world_model_update.triple.object == "dark mode"
