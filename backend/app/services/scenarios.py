"""Готовые сценарии ручного тестирования (ТЗ §9).

Шесть сценариев из ТЗ описаны здесь данными, а не разбросаны по документации
и тестам. Один источник правды даёт три вещи сразу: их можно прогнать через
Swagger одним запросом, подставить кнопкой в тестовом интерфейсе (ТЗ §8.4)
и проверить автотестом.

## Два принципа, без которых сценарии бесполезны

**Общий профиль клиента.** Все шесть описывают одного и того же человека:
обычная сумма 100, дом — Казахстан, два известных устройства, три операции
в сутки, счёту 800 дней. Меняется ровно то, что заявлено в названии
сценария. Иначе сравнивать Risk Score между ними бессмысленно.

**Явный контекст и фиксированное время.** Профиль передаётся в каждом
запросе целиком, а метки времени заданы абсолютными значениями. Поэтому
результат не зависит ни от накопленной истории, ни от того, в котором часу
запускают демонстрацию: числа в документации воспроизводятся всегда.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.i18n import Text
from app.schemas.enums import ScenarioKey
from app.schemas.transaction import TransactionRequest

# Опорное время демонстрации: вторник, будний день, 14:30 — обычное время покупок.
DEMO_TIME = datetime(2026, 9, 1, 14, 30, 0)
# Ночь для сценария с атакой: автоматизированный фрод чаще идёт ночью.
DEMO_NIGHT = datetime(2026, 9, 1, 2, 14, 0)

# Домашние координаты клиента — Астана.
HOME_LATITUDE = 51.16
HOME_LONGITUDE = 71.44

# Лагос: используется в сценариях с чужой страной.
LAGOS_LATITUDE = 6.5244
LAGOS_LONGITUDE = 3.3792


def _base(timestamp: datetime = DEMO_TIME, **overrides) -> dict:
    """Обычная транзакция знакомого клиента — основа всех сценариев."""
    body = {
        "user_id": "user_demo",
        "amount": 100.0,
        "timestamp": timestamp.isoformat(),
        "merchant": "Magnum",
        "country": "KZ",
        "device_id": "dev_known_1",
        "ip_address": "85.132.10.55",
        "latitude": HOME_LATITUDE,
        "longitude": HOME_LONGITUDE,
        "transaction_frequency": 3,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
        # --- профиль клиента передаётся явно: результат обязан быть
        # воспроизводимым независимо от накопленной истории
        "user_avg_amount": 100.0,
        "user_amount_std": 30.0,
        "user_home_country": "KZ",
        "user_typical_frequency": 3.0,
        "known_device_ids": ["dev_known_1", "dev_known_2"],
        "previous_ip_address": "85.132.10.40",
        "previous_timestamp": (timestamp - timedelta(hours=5)).isoformat(),
        "previous_latitude": 51.15,
        "previous_longitude": 71.40,
        "txn_count_last_hour": 1,
        "merchant_category": "grocery",
    }
    body.update(overrides)
    return body


@dataclass(frozen=True, slots=True)
class Scenario:
    """Один сценарий ручного тестирования."""

    key: ScenarioKey
    title: str
    description: Text
    expectation: Text
    changed_from_normal: tuple[str, ...]
    request: dict

    def to_transaction(self) -> TransactionRequest:
        return TransactionRequest(**self.request)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key=ScenarioKey.NORMAL,
        title="Normal transaction",
        description=Text(
            ru=(
                "Обычная покупка в продуктовом: привычная сумма, знакомое устройство, "
                "домашняя страна, нормальная частота операций."
            ),
            kk=(
                "Азық-түлік дүкеніндегі әдеттегі сатып алу: таныс сома, таныс құрылғы, үй "
                "елі, қалыпты операция жиілігі."
            ),
            en=(
                "An ordinary grocery purchase: a familiar amount, a known device, the home "
                "country and a normal transaction rate."
            ),
        ),
        expectation=Text(
            ru="низкий Risk Score, решение APPROVE",
            kk="төмен Risk Score, APPROVE шешімі",
            en="a low Risk Score, decision APPROVE",
        ),
        changed_from_normal=(),
        request=_base(),
    ),
    Scenario(
        key=ScenarioKey.NEW_DEVICE,
        title="New device",
        description=Text(
            ru=(
                "Та же покупка, но с незнакомого устройства и из незнакомой сети. Именно "
                "такая пара сигналов — сигнатура входа злоумышленника; новый телефон в "
                "домашней сети система намеренно не считает поводом для проверки."
            ),
            kk=(
                "Сол сатып алу, бірақ бейтаныс құрылғыдан және бейтаныс желіден. Дәл "
                "осындай екі белгі қатар келгені — шабуылдаушы кірген сәттің қолтаңбасы; үй "
                "желісіндегі жаңа телефонды жүйе тексеру себебі деп әдейі санамайды."
            ),
            en=(
                "The same purchase, but from an unfamiliar device and an unfamiliar "
                "network. That pair of signals together is the signature of an intruder "
                "signing in; a new phone on the home network is deliberately not treated as "
                "a reason to check."
            ),
        ),
        expectation=Text(
            ru="Risk Score заметно выше, чем в сценарии 1",
            kk="Risk Score 1-сценарийдегіден айтарлықтай жоғары",
            en="a Risk Score noticeably higher than in scenario 1",
        ),
        changed_from_normal=("device_id", "ip_address"),
        request=_base(device_id="dev_unknown_77", ip_address="203.0.113.7"),
    ),
    Scenario(
        key=ScenarioKey.UNUSUAL_COUNTRY,
        title="Unusual country",
        description=Text(
            ru=(
                "Клиент обычно платит из Казахстана, а операция идёт из Нигерии. Прошло 20 "
                "часов — долететь можно, так что невозможного перемещения здесь нет. IP "
                "местный: человек физически находится в другой стране."
            ),
            kk=(
                "Клиент әдетте Қазақстаннан төлейді, ал операция Нигериядан келіп тұр. 20 "
                "сағат өткен — ұшып жетуге болады, сондықтан мұнда мүмкін емес орын "
                "ауыстыру жоқ. IP жергілікті: адам шын мәнінде басқа елде."
            ),
            en=(
                "The client usually pays from Kazakhstan, but this transaction comes from "
                "Nigeria. Twenty hours have passed — the flight is possible, so there is no "
                "impossible travel here. The IP is local: the person is physically in "
                "another country."
            ),
        ),
        expectation=Text(
            ru="повышенный риск",
            kk="жоғарылаған тәуекел",
            en="elevated risk",
        ),
        changed_from_normal=("country", "latitude", "longitude", "ip_address", "previous_timestamp"),
        request=_base(
            country="NG",
            latitude=LAGOS_LATITUDE,
            longitude=LAGOS_LONGITUDE,
            ip_address="197.210.44.12",
            previous_timestamp=(DEMO_TIME - timedelta(hours=20)).isoformat(),
        ),
    ),
    Scenario(
        key=ScenarioKey.LARGE_AMOUNT,
        title="Large amount",
        description=Text(
            ru=(
                "Сумма в 25 раз выше обычной для клиента. Всё остальное привычно: своё "
                "устройство, домашняя страна, своя сеть."
            ),
            kk=(
                "Сома клиенттің әдеттегісінен 25 есе жоғары. Қалғанының бәрі таныс: өз "
                "құрылғысы, үй елі, өз желісі."
            ),
            en=(
                "The amount is 25 times the client's usual. Everything else is familiar: "
                "their own device, the home country, their own network."
            ),
        ),
        expectation=Text(
            ru="повышенный риск",
            kk="жоғарылаған тәуекел",
            en="elevated risk",
        ),
        changed_from_normal=("amount",),
        request=_base(amount=2500.0),
    ),
    Scenario(
        key=ScenarioKey.MULTIPLE_ANOMALIES,
        title="Multiple anomalies",
        description=Text(
            ru=(
                "Захват аккаунта ночью: крупная сумма, незнакомое устройство и сеть, чужая "
                "страна повышенного риска, всплеск частоты операций и физически невозможное "
                "перемещение — операция в Нигерии через 22 минуты после операции в "
                "Казахстане."
            ),
            kk=(
                "Түнгі аккаунт басып алу: ірі сома, бейтаныс құрылғы мен желі, жоғары "
                "тәуекелді бөтен ел, операция жиілігінің күрт өсуі және физикалық мүмкін "
                "емес орын ауыстыру — Қазақстандағы операциядан кейін 22 минут өткенде "
                "Нигериядағы операция."
            ),
            en=(
                "A night-time account takeover: a large amount, an unfamiliar device and "
                "network, a foreign high-risk country, a spike in transaction rate and "
                "physically impossible travel — a transaction in Nigeria 22 minutes after "
                "one in Kazakhstan."
            ),
        ),
        expectation=Text(
            ru="высокий Risk Score, решение BLOCK",
            kk="жоғары Risk Score, BLOCK шешімі",
            en="a high Risk Score, decision BLOCK",
        ),
        changed_from_normal=(
            "amount", "device_id", "ip_address", "country", "latitude", "longitude",
            "transaction_frequency", "txn_count_last_hour", "merchant",
            "merchant_category", "timestamp", "previous_timestamp",
        ),
        request=_base(
            timestamp=DEMO_NIGHT,
            amount=3000.0,
            device_id="dev_attacker_01",
            ip_address="203.0.113.7",
            country="NG",
            latitude=LAGOS_LATITUDE,
            longitude=LAGOS_LONGITUDE,
            merchant="Binance",
            merchant_category="crypto",
            transaction_frequency=25,
            txn_count_last_hour=12,
            previous_timestamp=(DEMO_NIGHT - timedelta(minutes=22)).isoformat(),
        ),
    ),
    Scenario(
        key=ScenarioKey.HIGH_FREQUENCY,
        title="High frequency",
        description=Text(
            ru=(
                "Всплеск числа операций при прочих привычных параметрах: та же сумма, своё "
                "устройство, домашняя страна, своя сеть. Изолирует признак частоты — так "
                "выглядит начало автоматизированного перебора, когда сумма ещё не выросла."
            ),
            kk=(
                "Басқа параметрлері әдеттегідей болса да операция санының күрт өсуі: сол "
                "сома, өз құрылғысы, үй елі, өз желісі. Жиілік белгісін бөліп көрсетеді — "
                "автоматтандырылған іріктеудің басы осылай көрінеді, сома әлі өспеген "
                "кезде."
            ),
            en=(
                "A spike in the number of transactions while everything else stays usual: "
                "the same amount, their own device, the home country, their own network. It "
                "isolates the frequency signal — this is what the start of an automated "
                "sweep looks like, before the amounts grow."
            ),
        ),
        expectation=Text(
            ru="повышенный риск",
            kk="жоғарылаған тәуекел",
            en="elevated risk",
        ),
        changed_from_normal=("transaction_frequency", "txn_count_last_hour", "previous_timestamp"),
        request=_base(
            transaction_frequency=22,
            txn_count_last_hour=9,
            previous_timestamp=(DEMO_TIME - timedelta(minutes=6)).isoformat(),
        ),
    ),
)

_BY_KEY: dict[ScenarioKey, Scenario] = {scenario.key: scenario for scenario in SCENARIOS}


def get_scenario(key: ScenarioKey) -> Scenario:
    """Сценарий по ключу."""
    try:
        return _BY_KEY[key]
    except KeyError as exc:  # pragma: no cover — ключ валидируется FastAPI
        raise KeyError(f"Неизвестный сценарий: {key}") from exc


def scenario_order() -> tuple[ScenarioKey, ...]:
    """Все сценарии в порядке ТЗ §9."""
    return tuple(scenario.key for scenario in SCENARIOS)


# Пять сценариев прежней редакции ТЗ образуют шкалу нарастания риска:
# от безобидной покупки к явной атаке. Именно на них проверяется
# монотонный рост Risk Score.
#
# `high_frequency` добавлен ревизией 2 и в эту шкалу не входит: он
# изолирует один признак, а не усиливает предыдущий сценарий. Включать
# его в проверку монотонности было бы неверно — он встал бы в середину
# и сломал бы осмысленное свойство ради формального порядка.
ESCALATION_ORDER: tuple[ScenarioKey, ...] = (
    ScenarioKey.NORMAL,
    ScenarioKey.NEW_DEVICE,
    ScenarioKey.UNUSUAL_COUNTRY,
    ScenarioKey.LARGE_AMOUNT,
    ScenarioKey.MULTIPLE_ANOMALIES,
)
