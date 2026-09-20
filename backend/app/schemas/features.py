"""Контракт справочника признаков (ТЗ §4, брифинг §5.B).

Справочник отдаётся отдельно от предсказания намеренно. Описания
и разделы не меняются от транзакции к транзакции, и возвращать их
в каждом ответе `POST /predict` значило бы гонять полтора килобайта
неизменного текста на каждую операцию.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeatureInfo(BaseModel):
    """Один признак: что это и как его показывать."""

    index: int = Field(
        description=(
            "Позиция в векторе признаков. Порядок сохраняется вместе с моделью, "
            "поэтому менять его можно только вместе с переобучением."
        )
    )
    name: str = Field(description="Техническое имя — оно же ключ в поле `features` ответа")
    description: str = Field(description="Что признак означает, для человека")
    is_flag: bool = Field(description="Бинарный: значение читается как «да» или «нет»")
    decimals: int = Field(
        description=(
            "Сколько знаков после запятой показывать. Число, а не строка формата: "
            "то же правило нужно интерфейсу, а формат Python на клиенте не применить."
        )
    )
    reason_high: str = Field(description="Как XAI формулирует повышение риска этим признаком")


class FeatureSection(BaseModel):
    """Группа признаков одного пункта ТЗ §4."""

    section: str = Field(description="Пункт ТЗ, например «§4.6 Резкое изменение геолокации»")
    features: list[FeatureInfo]


class FeatureRegistry(BaseModel):
    """Все признаки, которые система строит из транзакции."""

    count: int
    sections: list[FeatureSection] = Field(
        description="В порядке вектора признаков, сгруппированные по пунктам ТЗ §4"
    )
