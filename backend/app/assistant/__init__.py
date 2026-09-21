"""Ассистент риск-аналитика: объяснение решения клиенту (брифинг §6).

Языковая модель здесь только формулирует уже принятое решение.
Обоснование разделения — в `message.py`.
"""

from app.assistant.llm import LlmClient, LlmConfig, LlmUnavailableError
from app.assistant.message import (
    DecisionFacts,
    build_facts,
    contradicts,
    fallback_text,
    needs_assistant,
)
from app.assistant.phrases import system_prompt
from app.i18n import DEFAULT_LANGUAGE, LANGUAGES, Language

__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "DecisionFacts",
    "Language",
    "LlmClient",
    "LlmConfig",
    "LlmUnavailableError",
    "build_facts",
    "contradicts",
    "fallback_text",
    "needs_assistant",
    "system_prompt",
]
