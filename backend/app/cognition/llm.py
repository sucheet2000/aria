import structlog
from anthropic import AsyncAnthropic

from app.config import settings

logger = structlog.get_logger()


class LLMClient:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate_response(
        self,
        user_message: str,
        system_prompt: str = "You are ARIA, a helpful multimodal AGI avatar.",
        max_tokens: int = 1024,
    ) -> str:
        message = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        content = message.content[0]
        if hasattr(content, "text"):
            return content.text
        return ""
