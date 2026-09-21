"""Реестр признаков (ТЗ §4).

Каждый признак описан один раз и в одном месте: техническое имя, русское
описание для документации и англоязычные формулировки для XAI (ТЗ §7 приводит
примеры причин на английском).

Порядок `FEATURE_SPECS` — это порядок колонок вектора признаков. Он сохраняется
вместе с моделью, поэтому менять его можно только вместе с переобучением.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.i18n import Text


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Описание одного признака."""

    name: str
    description: Text
    # Пункт ТЗ §4, к которому признак относится. Живёт здесь, а не в скрипте
    # документации: раздел — свойство самого признака, и держать его отдельным
    # списком значило бы иметь место, где можно забыть новый признак. Теперь
    # забыть нельзя — поле обязательное.
    section: Text
    # Формулировка, когда признак ПОВЫШАЕТ риск. Может содержать {value}.
    reason_high: str
    # Формулировка, когда признак ПОНИЖАЕТ риск. None — о таком не рассказываем.
    reason_low: str | None = None
    # Бинарный признак: значение в текст не подставляется.
    is_flag: bool = False
    # Знаков после запятой при показе человеку. Число, а не строка формата:
    # то же значение нужно интерфейсу, а формат Python на клиенте не применить.
    decimals: int = 2

    def format_value(self, value: float) -> str:
        if self.is_flag:
            return "yes" if value >= 0.5 else "no"
        return f"{value:.{self.decimals}f}"



# Разделы ТЗ §4. Вынесены в константы: один раздел объединяет
# несколько признаков, и три перевода не нужно повторять у каждого.

SECTION_AMOUNT = Text(
    ru="§4.1 Отклонение суммы от обычной",
    kk="§4.1 Соманың әдеттегіден ауытқуы",
    en="§4.1 Amount deviation from the usual",
)

SECTION_COUNTRY = Text(
    ru="§4.2 Необычная страна",
    kk="§4.2 Әдеттен тыс ел",
    en="§4.2 Unusual country",
)

SECTION_DEVICE = Text(
    ru="§4.3 Новый device",
    kk="§4.3 Жаңа құрылғы",
    en="§4.3 New device",
)

SECTION_IP = Text(
    ru="§4.4 Изменение IP",
    kk="§4.4 IP өзгеруі",
    en="§4.4 IP change",
)

SECTION_FREQUENCY = Text(
    ru="§4.5 / §4.8 Частота и количество за период",
    kk="§4.5 / §4.8 Кезеңдегі жиілік пен сан",
    en="§4.5 / §4.8 Frequency and count per period",
)

SECTION_GEO = Text(
    ru="§4.6 Резкое изменение геолокации",
    kk="§4.6 Геолокацияның күрт өзгеруі",
    en="§4.6 Abrupt geolocation change",
)

SECTION_TIME = Text(
    ru="§4.7 Время транзакции",
    kk="§4.7 Транзакция уақыты",
    en="§4.7 Transaction time",
)

SECTION_OTHER = Text(
    ru="§4.9 Прочее поведение",
    kk="§4.9 Өзге мінез-құлық",
    en="§4.9 Other behaviour",
)

FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    # ------------------------------------------------ сумма (ТЗ §4.1)
    FeatureSpec(
        name="amount_log",
        section=SECTION_AMOUNT,
        description=Text(
            ru="Логарифм суммы транзакции",
            kk="Транзакция сомасының логарифмі",
            en="Logarithm of the transaction amount",
        ),
        # Значение в текст не подставляется: пользователю нечего делать
        # с логарифмом. Само число всё равно возвращается в поле value.
        reason_high="Large transaction amount in absolute terms",
        decimals=2,
    ),
    FeatureSpec(
        name="amount_deviation_ratio",
        section=SECTION_AMOUNT,
        description=Text(
            ru="Во сколько раз сумма отличается от обычной суммы клиента",
            kk="Сома клиенттің әдеттегі сомасынан неше есе өзгеше",
            en="How many times the amount differs from the client's usual amount",
        ),
        reason_high="Transaction amount is {value}x the user's normal amount",
        reason_low="Amount is in line with the user's normal spending",
        decimals=1,
    ),
    FeatureSpec(
        name="amount_zscore",
        section=SECTION_AMOUNT,
        description=Text(
            ru="Отклонение суммы от обычной в стандартных отклонениях клиента",
            kk="Соманың әдеттегіден ауытқуы, клиенттің стандартты ауытқуымен",
            en="Deviation of the amount from the usual, in the client's standard deviations",
        ),
        reason_high="Amount deviates {value} standard deviations from the user's usual spending",
        decimals=1,
    ),
    FeatureSpec(
        name="amount_vs_previous_ratio",
        section=SECTION_AMOUNT,
        description=Text(
            ru="Отношение суммы к сумме предыдущей транзакции",
            kk="Соманың алдыңғы транзакция сомасына қатынасы",
            en="Ratio of the amount to the previous transaction's amount",
        ),
        reason_high="Amount is {value}x the user's previous transaction",
        decimals=1,
    ),
    FeatureSpec(
        name="is_round_amount",
        section=SECTION_AMOUNT,
        description=Text(
            ru="Круглая сумма — характерна для попыток вывода средств",
            kk="Дөңгелек сома — қаражат шығару әрекеттеріне тән",
            en="Round amount — typical of cash-out attempts",
        ),
        reason_high="Round-number amount, typical of cash-out attempts",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_micro_amount",
        section=SECTION_AMOUNT,
        description=Text(
            ru="Необычно мелкая сумма — характерна для прозвона карты",
            kk="Әдеттен тыс шағын сома — картаны тексеруге тән",
            en="Unusually small amount — typical of card testing",
        ),
        reason_high="Unusually small amount, typical of card-testing probes",
        is_flag=True,
    ),
    # ------------------------------------------------ страна (ТЗ §4.2)
    FeatureSpec(
        name="is_unusual_country",
        section=SECTION_COUNTRY,
        description=Text(
            ru="Транзакция вне домашней страны клиента",
            kk="Транзакция клиенттің үй елінен тыс",
            en="Transaction outside the client's home country",
        ),
        reason_high="Unusual country: transaction outside the user's home country",
        reason_low="Transaction from the user's home country",
        is_flag=True,
    ),
    FeatureSpec(
        name="country_changed_from_previous",
        section=SECTION_COUNTRY,
        description=Text(
            ru="Страна изменилась относительно предыдущей транзакции",
            kk="Ел алдыңғы транзакциямен салыстырғанда өзгерді",
            en="The country changed from the previous transaction",
        ),
        reason_high="Country changed since the previous transaction",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_high_risk_country",
        section=SECTION_COUNTRY,
        description=Text(
            ru="Страна входит в список повышенного риска",
            kk="Ел жоғары тәуекел тізімінде",
            en="The country is on the high-risk list",
        ),
        reason_high="Transaction from a high-risk country",
        is_flag=True,
    ),
    # ------------------------------------------------ устройство (ТЗ §4.3)
    FeatureSpec(
        name="is_new_device",
        section=SECTION_DEVICE,
        description=Text(
            ru="Устройство ранее не встречалось у этого клиента",
            kk="Құрылғы бұл клиентте бұрын кездеспеген",
            en="The device has not been seen for this client before",
        ),
        reason_high="New device detected",
        reason_low="Device is already known for this user",
        is_flag=True,
    ),
    FeatureSpec(
        name="known_device_count",
        section=SECTION_DEVICE,
        description=Text(
            ru="Сколько устройств известно для клиента",
            kk="Клиент үшін қанша құрылғы белгілі",
            en="How many devices are known for the client",
        ),
        reason_high="User has {value} known devices",
        decimals=0,
    ),
    # ------------------------------------------------ IP (ТЗ §4.4)
    FeatureSpec(
        name="ip_changed",
        section=SECTION_IP,
        description=Text(
            ru="IP-адрес отличается от предыдущего",
            kk="IP-мекенжай алдыңғысынан өзгеше",
            en="The IP address differs from the previous one",
        ),
        reason_high="IP address changed since the previous transaction",
        is_flag=True,
    ),
    FeatureSpec(
        name="ip_subnet_changed",
        section=SECTION_IP,
        description=Text(
            ru="Сменилась подсеть /24 — другой провайдер или сеть",
            kk="/24 ішкі желісі ауысты — басқа провайдер немесе желі",
            en="The /24 subnet changed — a different provider or network",
        ),
        reason_high="Network changed: different IP subnet than the previous transaction",
        reason_low="Same network as the previous transaction",
        is_flag=True,
    ),
    # ------------------------------------------------ частота (ТЗ §4.5, §4.8)
    FeatureSpec(
        name="transaction_frequency",
        section=SECTION_FREQUENCY,
        description=Text(
            ru="Количество транзакций клиента за последние 24 часа",
            kk="Соңғы 24 сағаттағы клиент транзакцияларының саны",
            en="Number of the client's transactions in the last 24 hours",
        ),
        reason_high="{value} transactions in the last 24 hours",
        decimals=0,
    ),
    FeatureSpec(
        name="frequency_ratio",
        section=SECTION_FREQUENCY,
        description=Text(
            ru="Во сколько раз текущая частота выше обычной для клиента",
            kk="Ағымдағы жиілік клиенттің әдеттегісінен неше есе жоғары",
            en="How many times the current frequency exceeds the client's usual",
        ),
        reason_high="Transaction frequency is {value}x the user's normal rate",
        reason_low="Transaction frequency is normal for this user",
        decimals=1,
    ),
    FeatureSpec(
        name="txn_count_last_hour",
        section=SECTION_FREQUENCY,
        description=Text(
            ru="Количество транзакций за последний час",
            kk="Соңғы сағаттағы транзакциялар саны",
            en="Number of transactions in the last hour",
        ),
        reason_high="{value} transactions in the last hour",
        decimals=0,
    ),
    FeatureSpec(
        name="is_high_frequency",
        section=SECTION_FREQUENCY,
        description=Text(
            ru="Частота транзакций существенно выше обычной",
            kk="Транзакция жиілігі әдеттегіден едәуір жоғары",
            en="Transaction frequency is substantially above the usual",
        ),
        reason_high="High transaction frequency for this user",
        is_flag=True,
    ),
    # ------------------------------------------------ геолокация (ТЗ §4.6)
    FeatureSpec(
        name="geo_distance_km",
        section=SECTION_GEO,
        description=Text(
            ru="Расстояние до места предыдущей транзакции, км",
            kk="Алдыңғы транзакция орнына дейінгі қашықтық, км",
            en="Distance to the previous transaction's location, km",
        ),
        reason_high="Transaction {value} km away from the previous one",
        decimals=0,
    ),
    FeatureSpec(
        name="hours_since_previous",
        section=SECTION_GEO,
        description=Text(
            ru="Часов прошло с предыдущей транзакции",
            kk="Алдыңғы транзакциядан бері өткен сағат",
            en="Hours elapsed since the previous transaction",
        ),
        reason_high="Only {value} hours since the previous transaction",
        decimals=2,
    ),
    FeatureSpec(
        name="travel_speed_kmh",
        section=SECTION_GEO,
        description=Text(
            ru="Требуемая скорость перемещения между транзакциями, км/ч",
            kk="Транзакциялар арасындағы қажетті жылдамдық, км/сағ",
            en="Required travel speed between transactions, km/h",
        ),
        reason_high="Implied travel speed of {value} km/h between transactions",
        decimals=0,
    ),
    FeatureSpec(
        name="is_impossible_travel",
        section=SECTION_GEO,
        description=Text(
            ru="Перемещение физически невозможно за прошедшее время",
            kk="Өткен уақытта мұндай орын ауыстыру физикалық мүмкін емес",
            en="The travel is physically impossible in the elapsed time",
        ),
        reason_high="Impossible travel: this location cannot be reached in the elapsed time",
        is_flag=True,
    ),
    # ------------------------------------------------ время (ТЗ §4.7)
    FeatureSpec(
        name="hour_of_day",
        section=SECTION_TIME,
        description=Text(
            ru="Час суток",
            kk="Тәулік сағаты",
            en="Hour of the day",
        ),
        reason_high="Transaction at {value}:00",
        decimals=0,
    ),
    FeatureSpec(
        name="is_night",
        section=SECTION_TIME,
        description=Text(
            ru="Ночное время (00:00–05:59)",
            kk="Түнгі уақыт (00:00–05:59)",
            en="Night time (00:00–05:59)",
        ),
        reason_high="Night-time transaction",
        reason_low="Transaction during normal daytime hours",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_weekend",
        section=SECTION_TIME,
        description=Text(
            ru="Выходной день",
            kk="Демалыс күні",
            en="Weekend",
        ),
        reason_high="Weekend transaction",
        is_flag=True,
    ),
    # ------------------------------------------------ счёт и мерчант
    FeatureSpec(
        name="account_age_days",
        section=SECTION_OTHER,
        description=Text(
            ru="Возраст счёта в днях",
            kk="Шот жасы, күнмен",
            en="Account age in days",
        ),
        reason_high="Account age is {value} days",
        reason_low="Long-standing account",
        decimals=0,
    ),
    FeatureSpec(
        name="is_new_account",
        section=SECTION_OTHER,
        description=Text(
            ru="Счёт открыт недавно (моложе 60 дней)",
            kk="Шот жақында ашылған (60 күннен жас)",
            en="The account was opened recently (less than 60 days old)",
        ),
        reason_high="Recently opened account",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_high_risk_merchant",
        section=SECTION_OTHER,
        description=Text(
            ru="Категория мерчанта повышенного риска (crypto, gambling, переводы, ATM)",
            kk="Жоғары тәуекелді мерчант санаты (crypto, gambling, аударымдар, ATM)",
            en="High-risk merchant category (crypto, gambling, transfers, ATM)",
        ),
        reason_high="High-risk merchant category (crypto, gambling, transfers or ATM)",
        is_flag=True,
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURE_SPECS)

_SPEC_BY_NAME: dict[str, FeatureSpec] = {spec.name: spec for spec in FEATURE_SPECS}


def get_spec(name: str) -> FeatureSpec:
    """Описание признака по имени."""
    try:
        return _SPEC_BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"Неизвестный признак: {name}") from exc


def has_spec(name: str) -> bool:
    return name in _SPEC_BY_NAME
