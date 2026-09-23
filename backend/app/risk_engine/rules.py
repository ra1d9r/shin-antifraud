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
from app.i18n import DEFAULT_LANGUAGE, Language, Text

FeatureMap = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Rule:
    """Описание одной политики."""

    key: str
    # Формулировка для интерфейса и объяснения на трёх языках.
    # ТЗ §7 приводит примеры по-английски — английский и остался,
    # он стал `?language=en`, а не исчез.
    title: Text
    # Описание для документации.
    description: str
    min_score: int
    # Каким полем `POST /config/policies` меняется минимум этой политики.
    #
    # Хранится рядом с правилом, потому что с ключом совпадает не всегда:
    # `velocity_burst` настраивается полем `velocity_min_score`, а
    # `new_account_large_amount` — полем `new_account_amount_min_score`.
    # Интерфейсу нужно знать это имя, и вывести его из ключа он не может;
    # вывел бы по правилу «ключ плюс `_min_score`» — и две политики из
    # шести молча не сохранялись бы, потому что лишнее поле Pydantic
    # отбрасывает без жалобы.
    config_field: str
    condition: Callable[[FeatureMap], bool]

    def applies_to(self, features: FeatureMap) -> bool:
        return bool(self.condition(features))


@dataclass(frozen=True, slots=True)
class TriggeredRule:
    """Сработавшее правило."""

    key: str
    # Название на трёх языках: оно уходит клиенту в объяснении.
    # Ключ рядом остаётся техническим и не переводится никогда.
    title: Text
    min_score: int

    def to_dict(self, language: Language = DEFAULT_LANGUAGE) -> dict:
        return {
            "key": self.key,
            "title": self.title.get(language),
            "min_score": self.min_score,
        }


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
            title=Text(
                ru="Невозможное перемещение: до точки не добраться за прошедшее время",
                kk="Мүмкін емес орын ауыстыру: өткен уақытта жерге жету мүмкін емес",
                en="Impossible travel: location cannot be reached in the elapsed time",
            ),
            description=(
                "Между соседними транзакциями требуется скорость перемещения выше "
                "авиационной. Либо карта скомпрометирована, либо реквизитами "
                "пользуются в двух местах одновременно."
            ),
            min_score=settings.rule_impossible_travel_min_score,
            config_field="impossible_travel_min_score",
            condition=lambda f: _flag(f, "is_impossible_travel"),
        ),
        Rule(
            key="velocity_burst",
            title=Text(
                ru="Аномальная частота операций",
                kk="Операциялардың аномалды жиілігі",
                en="Abnormal transaction velocity",
            ),
            description=(
                "Всплеск числа операций за час. Характерно для автоматического "
                "прозвона карты, когда злоумышленник проверяет её работоспособность."
            ),
            min_score=settings.rule_velocity_min_score,
            config_field="velocity_min_score",
            condition=lambda f: (
                f.get("txn_count_last_hour", 0.0) >= settings.rule_velocity_txn_per_hour
            ),
        ),
        Rule(
            key="new_account_large_amount",
            title=Text(
                ru="Крупная операция на недавно открытом счёте",
                kk="Жақында ашылған шоттағы ірі операция",
                en="Large transaction on a recently opened account",
            ),
            description=(
                "Крупная операция на недавно открытом счёте: типичная схема "
                "злоупотребления, когда счёт открывают ради одной операции."
            ),
            min_score=settings.rule_new_account_amount_min_score,
            config_field="new_account_amount_min_score",
            condition=lambda f: (
                _flag(f, "is_new_account")
                and f.get("amount_deviation_ratio", 0.0) >= settings.rule_new_account_amount_ratio
            ),
        ),
        Rule(
            key="high_risk_country",
            title=Text(
                ru="Операция из страны повышенного риска",
                kk="Жоғары тәуекелді елден жасалған операция",
                en="Transaction from a high-risk country",
            ),
            description=(
                "Страна входит в список повышенного риска карточного фрода. "
                "В проде такой список приходит от провайдера риск-данных."
            ),
            min_score=settings.rule_high_risk_country_min_score,
            config_field="high_risk_country_min_score",
            condition=lambda f: _flag(f, "is_high_risk_country"),
        ),
        Rule(
            key="unusual_country",
            title=Text(
                ru="Операция из необычной страны с незнакомого подключения",
                kk="Әдеттен тыс елден, бейтаныс қосылым арқылы жасалған операция",
                en="Transaction from an unusual country on an unfamiliar connection",
            ),
            description=(
                "Операция вне домашней страны клиента И с незнакомого устройства "
                "или из незнакомой сети. Условие составное намеренно: обычная "
                "поездка сама по себе не повод для проверки, а вот чужая страна "
                "вместе с неопознанным доступом — уже сигнатура захвата аккаунта."
            ),
            min_score=settings.rule_unusual_country_min_score,
            config_field="unusual_country_min_score",
            condition=lambda f: (
                _flag(f, "is_unusual_country")
                and (_flag(f, "is_new_device") or _flag(f, "ip_subnet_changed"))
            ),
        ),
        Rule(
            key="new_device",
            title=Text(
                ru="Незнакомое устройство в незнакомой сети",
                kk="Бейтаныс желідегі бейтаныс құрылғы",
                en="Unrecognized device on an unrecognized network",
            ),
            description=(
                "Незнакомое устройство И незнакомая сеть — классическая сигнатура "
                "входа злоумышленника. Новое устройство в домашней сети клиента "
                "правилом не считается: так выглядит покупка телефона, и модель "
                "оценивает такой случай низко совершенно справедливо."
            ),
            min_score=settings.rule_new_device_min_score,
            config_field="new_device_min_score",
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
