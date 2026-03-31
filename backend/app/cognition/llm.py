from __future__ import annotations

import json
import re
import time

import structlog
from anthropic import AsyncAnthropic

from app.models.schemas import SymbolicResponse, VisionContext, WorldModelTriple, WorldModelUpdate
from app.cognition.prompt import build_system_prompt

logger = structlog.get_logger()


class LLMClient:
    MODEL = "claude-haiku-4-5-20251001"
    MAX_TOKENS = 512

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        message: str,
        vision: VisionContext,
        conversation_history: list[dict],
        working_memory: list[str],
        episodic_memory: list[str],
    ) -> SymbolicResponse:
        system_prompt = build_system_prompt(
            vision, message, working_memory, episodic_memory
        )

        messages = []
        for turn in conversation_history[-6:]:
            messages.append({
                "role": turn.role,
                "content": turn.content,
            })
        messages.append({"role": "user", "content": message})

        start = time.time()
        response = await self._client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        raw = response.content[0].text.strip()
        logger.debug("llm raw response", elapsed_ms=elapsed_ms, text=raw[:100])

        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> SymbolicResponse:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            logger.warning("llm response not JSON, falling back", raw=raw[:100])
            return SymbolicResponse(
                symbolic_inference="state unclear",
                world_model_update=None,
                natural_language_response=raw,
            )

        try:
            data = json.loads(match.group())
            wmu = None
            if data.get("world_model_update"):
                raw_wmu = data["world_model_update"]
                triple = WorldModelTriple(
                    subject=raw_wmu["triple"]["subject"],
                    predicate=raw_wmu["triple"]["predicate"],
                    object=raw_wmu["triple"]["object"],
                )
                wmu = WorldModelUpdate(
                    triple=triple,
                    confidence=float(raw_wmu.get("confidence", 0.5)),
                    source=raw_wmu.get("source", "behavioral_inference"),
                )
            return SymbolicResponse(
                symbolic_inference=data.get("symbolic_inference", ""),
                world_model_update=wmu,
                natural_language_response=data.get("natural_language_response", ""),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("failed to parse llm json", error=str(e))
            return SymbolicResponse(
                symbolic_inference="parse error",
                world_model_update=None,
                natural_language_response=raw,
            )
