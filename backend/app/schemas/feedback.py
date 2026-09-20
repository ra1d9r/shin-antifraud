"""Контракты разметки аналитика.

Домен живёт в `app.store.feedback`; здесь только то, что уходит в HTTP.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import Decision, Verdict

# Ограничения контракта, а не бизнес-величины: в `.env` им делать нечего.
# Смысл — не дать одной записи разрастись так, что файл меток перестанет
# быть пригодным для чтения и дообучения.
ANALYST_MAX_LENGTH = 80
COMMENT_MAX_LENGTH = 500


class FeedbackRequest(BaseModel):
    """Отметка аналитика по одной операции."""

    verdict: Verdict = Field(
        description=(
            "CORRECT — система решила правильно, INCORRECT — ошиблась. "
            "Настоящая метка (фрод или нет) выводится из отметки и решения "
            "системы, спрашивать её отдельно незачем."
        )
    )
    analyst: str | None = Field(
        default=None,
        max_length=ANALYST_MAX_LENGTH,
        description="Кто разметил — чтобы спорную метку было с кем обсудить",
    )
    comment: str | None = Field(
        default=None,
        max_length=COMMENT_MAX_LENGTH,
        description="Почему так: подтверждение от клиента, номер обращения, детали",
    )


class FeedbackOut(BaseModel):
    """Сохранённая метка вместе со слепком решения системы."""

    transaction_id: str
    user_id: str
    verdict: Verdict
    actual_fraud: bool = Field(
        description="Настоящая метка, выведенная из отметки: была ли операция мошеннической"
    )
    decision: Decision = Field(description="Что система решила в момент разметки")
    risk_score: int
    model_score: int
    amount: float
    triggered_rules: list[str] = Field(default_factory=list)
    labeled_at: datetime
    analyst: str | None = None
    comment: str | None = None


class DecisionFeedbackOut(BaseModel):
    """Сколько меток собрано на решение и что они показали."""

    decision: Decision
    labeled: int
    fraud: int
    legit: int


class RuleFeedbackOut(BaseModel):
    """Как политика выглядит на подтверждённых операциях."""

    key: str
    labeled: int
    fraud: int
    legit: int


class FeedbackSummary(BaseModel):
    """Что накопленная разметка говорит о качестве системы.

    Матрица ошибок считается относительно того, объявила ли система
    операцию подозрительной: CHALLENGE и BLOCK — положительный ответ,
    APPROVE — отрицательный.
    """

    labeled_total: int = Field(description="Сколько операций разметил аналитик")
    correct: int = Field(description="Вердиктов, признанных верными")
    incorrect: int = Field(description="Вердиктов, признанных ошибочными")
    correct_share: float | None = Field(
        default=None,
        description="Доля верных вердиктов. null — разметки ещё нет, делить не на что",
    )
    fraud_confirmed: int = Field(description="Подтверждённых мошеннических операций")
    legit_confirmed: int = Field(description="Подтверждённых добросовестных операций")
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None = Field(
        default=None,
        description=(
            "Доля подтверждённого фрода среди помеченных системой. "
            "Наименее смещённое из измеримого здесь."
        ),
    )
    recall: float | None = Field(
        default=None,
        description=(
            "Смещена вверх и сравнению с метриками датасета не подлежит: "
            "пропущенный фрод попадает в разметку только если о нём сообщили."
        ),
    )
    fraud_amount_missed: float = Field(
        description="Сумма подтверждённого фрода, который система пропустила"
    )
    by_decision: list[DecisionFeedbackOut] = Field(default_factory=list)
    rules: list[RuleFeedbackOut] = Field(default_factory=list)
    storage_path: str | None = Field(
        default=None, description="Куда пишется архив меток"
    )
    storage_error: str | None = Field(
        default=None,
        description="Почему архив не пишется. Метки при этом живут в памяти до перезапуска",
    )
    skipped_lines: int = Field(
        default=0, description="Сколько битых строк пропущено при чтении архива"
    )


class FeedbackAccepted(BaseModel):
    """Ответ на разметку: сама метка и сразу пересчитанная сводка.

    Сводка возвращается тем же ответом намеренно. Аналитику важно видеть,
    как его отметка легла в общую картину, а отдельный запрос за этим —
    лишний круг по сети; на спящем бесплатном хостинге это заметно.
    """

    record: FeedbackOut
    summary: FeedbackSummary


class FeedbackListResponse(BaseModel):
    """Накопленная разметка постранично.

    Нужна не только интерфейсу: в контейнере с эфемерным диском это
    единственный способ достать метки наружу до того, как он погаснет.
    """

    total: int
    returned: int
    items: list[FeedbackOut]
