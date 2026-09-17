"""Жёсткие бизнес-политики поверх ML (ТЗ §6).

## Зачем правила нужны рядом с моделью

Модель учится на истории и поэтому недооценивает редкие, но дорогие паттерны.
Показательный пример из этого проекта: транзакция с незнакомого устройства,
но в домашней сети клиента и на обычную сумму, получает от модели около
1 балла — и это статистически честно, потому что чаще всего так выглядит
покупка нового телефона, а не атака.

Но политика банка в таком случае требует подтверждения владельца (SCA/3DS)
независимо от того, что сказала модель. Это решение бизнеса, а не вывод
из данных, и место ему — в правилах, а не в обучающей выборке.

## Контракт

* правило только **поднимает** Risk Score до своего минимума и никогда не снижает;
* срабатывания возвращаются наружу целиком, чтобы объяснение показывало,
  что именно подняло оценку: модель или политика;
* минимальные баллы берутся из конфигурации, а не зашиты в код.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.config.settings import Settings

FeatureMap = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Rule:
    """Описание одной политики."""

    key: str
    # Формулировка для интерфейса и объяснения (англ., как в примерах ТЗ §7).
    title: str
    # Описание для документации.
    description: str
    min_score: int
    condition: Callable[[FeatureMap], bool]

    def applies_to(self, features: FeatureMap) -> bool:
        return bool(self.condition(features))


@dataclass(frozen=True, slots=True)
class TriggeredRule:
    """Сработавшее правило."""

    key: str
    title: str
    min_score: int

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "min_score": self.min_score}


def _flag(features: FeatureMap, name: str) -> bool:
    """Бинарный признак считается поднятым при значении >= 0.5."""
    return features.get(name, 0.0) >= 0.5


def build_rules(settings: Settings) -> tuple[Rule, ...]:
    """Собрать набор правил с порогами из конфигурации.

    Порядок в кортеже влияет только на порядок отображения: итоговый порог
    берётся как максимум по всем сработавшим правилам.
    """
    return (
        Rule(
            key="impossible_travel",
            title="Impossible travel: location cannot be reached in the elapsed time",
            description=(
                "Между соседними транзакциями требуется скорость перемещения выше "
                "авиационной. Либо карта скомпрометирована, либо реквизитами "
                "пользуются в двух местах одновременно."
            ),
            min_score=settings.rule_impossible_travel_min_score,
            condition=lambda f: _flag(f, "is_impossible_travel"),
        ),
        Rule(
            key="velocity_burst",
            title="Abnormal transaction velocity",
            description=(
                "Всплеск числа операций за час. Характерно для автоматического "
                "прозвона карты, когда злоумышленник проверяет её работоспособность."
            ),
            min_score=settings.rule_velocity_min_score,
            condition=lambda f: (
                f.get("txn_count_last_hour", 0.0) >= settings.rule_velocity_txn_per_hour
            ),
        ),
        Rule(
            key="new_account_large_amount",
            title="Large transaction on a recently opened account",
            description=(
                "Крупная операция на недавно открытом счёте: типичная схема "
                "злоупотребления, когда счёт открывают ради одной операции."
            ),
            min_score=settings.rule_new_account_amount_min_score,
            condition=lambda f: (
                _flag(f, "is_new_account")
                and f.get("amount_deviation_ratio", 0.0) >= settings.rule_new_account_amount_ratio
            ),
        ),
        Rule(
            key="high_risk_country",
            title="Transaction from a high-risk country",
            description=(
                "Страна входит в список повышенного риска карточного фрода. "
                "В проде такой список приходит от провайдера риск-данных."
            ),
            min_score=settings.rule_high_risk_country_min_score,
            condition=lambda f: _flag(f, "is_high_risk_country"),
        ),
        Rule(
            key="unusual_country",
            title="Transaction from an unusual country on an unfamiliar connection",
            description=(
                "Операция вне домашней страны клиента И с незнакомого устройства "
                "или из незнакомой сети. Условие составное намеренно: обычная "
                "поездка сама по себе не повод для проверки, а вот чужая страна "
                "вместе с неопознанным доступом — уже сигнатура захвата аккаунта."
            ),
            min_score=settings.rule_unusual_country_min_score,
            condition=lambda f: (
                _flag(f, "is_unusual_country")
                and (_flag(f, "is_new_device") or _flag(f, "ip_subnet_changed"))
            ),
        ),
        Rule(
            key="new_device",
            title="Unrecognized device on an unrecognized network",
            description=(
                "Незнакомое устройство И незнакомая сеть — классическая сигнатура "
                "входа злоумышленника. Новое устройство в домашней сети клиента "
                "правилом не считается: так выглядит покупка телефона, и модель "
                "оценивает такой случай низко совершенно справедливо."
            ),
            min_score=settings.rule_new_device_min_score,
            condition=lambda f: _flag(f, "is_new_device") and _flag(f, "ip_subnet_changed"),
        ),
    )


def evaluate_rules(rules: tuple[Rule, ...], features: FeatureMap) -> tuple[TriggeredRule, ...]:
    """Какие правила сработали на этом наборе признаков."""
    return tuple(
        TriggeredRule(key=rule.key, title=rule.title, min_score=rule.min_score)
        for rule in rules
        if rule.applies_to(features)
    )


def minimum_score(triggered: tuple[TriggeredRule, ...]) -> int:
    """Порог, ниже которого итоговая оценка опуститься не может."""
    return max((rule.min_score for rule in triggered), default=0)
