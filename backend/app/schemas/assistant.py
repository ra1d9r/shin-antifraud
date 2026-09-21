"""Контракт ответа ассистента (брифинг §6).

Ключевое поле здесь — `source`. По нему видно, кто написал текст:
языковая модель или детерминированный запасной сборщик. Без него
шаблон было бы невозможно отличить от работы ассистента, и система
заявляла бы функциональность, которой в этот момент нет.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.enums import Decision


class ClientMessage(BaseModel):
    """Объяснение решения словами, обращёнными к клиенту."""

    transaction_id: str
    decision: Decision
    text: str = Field(description="То, что можно отправить клиенту как есть")

    source: Literal["llm", "fallback"] = Field(
        description=(
            "`llm` — текст написала языковая модель, `fallback` — собран "
            "из тех же фактов без неё. Различать обязательно: иначе шаблон "
            "выдавался бы за работу ассистента."
        )
    )
    model: str | None = Field(
        default=None, description="Какая языковая модель написала текст"
    )
    fallback_reason: str | None = Field(
        default=None,
        description=(
            "Почему показан запасной текст: ключа нет, модель не ответила "
            "или её ответ противоречил вердикту системы."
        ),
    )

    risk_score: int = Field(description="Оценка, о которой идёт речь")
    facts: list[str] = Field(
        description=(
            "Ровно те факты, которые ушли бы в запрос. Показываются, чтобы "
            "было видно: языковая модель пересказывает решение, а не "
            "принимает его."
        )
    )
    elapsed_ms: float
