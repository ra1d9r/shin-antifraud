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
    # Три языка: ТЗ §7 приводит примеры по-английски, и английский
    # остался — он стал `?language=en`, а не исчез.
    reason_high: Text
    # Формулировка, когда признак ПОНИЖАЕТ риск. None — о таком не рассказываем.
    reason_low: Text | None = None
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
        reason_high=Text(
            ru="Крупная сумма операции в абсолютном выражении",
            kk="Абсолютті мәнде ірі операция сомасы",
            en="Large transaction amount in absolute terms",
        ),
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
        reason_high=Text(
            ru="Сумма операции в {value} раз больше обычной для клиента",
            kk="Операция сомасы клиенттің әдеттегісінен {value} есе көп",
            en="Transaction amount is {value}x the user's normal amount",
        ),
        reason_low=Text(
            ru="Сумма в пределах обычных трат клиента",
            kk="Сома клиенттің әдеттегі шығындары шегінде",
            en="Amount is in line with the user's normal spending",
        ),
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
        reason_high=Text(
            ru="Сумма отклоняется на {value} стандартных отклонений от обычной для клиента",
            kk="Сома клиенттің әдеттегісінен {value} стандартты ауытқуға ауытқыған",
            en="Amount deviates {value} standard deviations from the user's usual spending",
        ),
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
        reason_high=Text(
            ru="Сумма в {value} раз больше предыдущей операции клиента",
            kk="Сома клиенттің алдыңғы операциясынан {value} есе көп",
            en="Amount is {value}x the user's previous transaction",
        ),
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
        reason_high=Text(
            ru="Круглая сумма — характерна для попыток вывода средств",
            kk="Дөңгелек сома — қаражат шығару әрекеттеріне тән",
            en="Round-number amount, typical of cash-out attempts",
        ),
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
        reason_high=Text(
            ru="Необычно мелкая сумма — характерна для прозвона карты",
            kk="Әдеттен тыс шағын сома — картаны тексеруге тән",
            en="Unusually small amount, typical of card-testing probes",
        ),
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
        reason_high=Text(
            ru="Необычная страна: операция вне домашней страны клиента",
            kk="Әдеттен тыс ел: операция клиенттің үй елінен тыс",
            en="Unusual country: transaction outside the user's home country",
        ),
        reason_low=Text(
            ru="Операция из домашней страны клиента",
            kk="Операция клиенттің үй елінен",
            en="Transaction from the user's home country",
        ),
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
        reason_high=Text(
            ru="Страна изменилась с предыдущей операции",
            kk="Алдыңғы операциядан бері ел өзгерді",
            en="Country changed since the previous transaction",
        ),
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
        reason_high=Text(
            ru="Операция из страны повышенного риска",
            kk="Жоғары тәуекелді елден жасалған операция",
            en="Transaction from a high-risk country",
        ),
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
        reason_high=Text(
            ru="Обнаружено новое устройство",
            kk="Жаңа құрылғы анықталды",
            en="New device detected",
        ),
        reason_low=Text(
            ru="Устройство уже известно для этого клиента",
            kk="Құрылғы бұл клиентке бұрыннан таныс",
            en="Device is already known for this user",
        ),
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
        reason_high=Text(
            ru="У клиента {value} известных устройств",
            kk="Клиентте {value} белгілі құрылғы бар",
            en="User has {value} known devices",
        ),
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
        reason_high=Text(
            ru="IP-адрес изменился с предыдущей операции",
            kk="Алдыңғы операциядан бері IP-мекенжай өзгерді",
            en="IP address changed since the previous transaction",
        ),
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
        reason_high=Text(
            ru="Сеть изменилась: другая подсеть, чем у предыдущей операции",
            kk="Желі өзгерді: алдыңғы операциядан басқа ішкі желі",
            en="Network changed: different IP subnet than the previous transaction",
        ),
        reason_low=Text(
            ru="Та же сеть, что и у предыдущей операции",
            kk="Алдыңғы операциямен бірдей желі",
            en="Same network as the previous transaction",
        ),
        is_flag=True,
    ),
    FeatureSpec(
        name="is_vpn_ip",
        section=SECTION_IP,
        description=Text(
            ru="Адрес похож на VPN, прокси или дата-центр",
            kk="Мекенжай VPN, прокси немесе дата-орталыққа ұқсайды",
            en="The address looks like a VPN, proxy or datacenter",
        ),
        # Сам по себе VPN — не улика: им пользуются в поездках, в офисах
        # и просто из осторожности. Поэтому формулировка говорит о том,
        # что видно, а не о том, что за этим стоит, а вес признаку
        # назначает модель, а не список.
        reason_high=Text(
            ru="Подключение с адреса VPN, прокси или дата-центра",
            kk="VPN, прокси немесе дата-орталық мекенжайынан қосылу",
            en="Connection from a VPN, proxy or datacenter address",
        ),
        reason_low=Text(
            ru="Подключение из обычной пользовательской сети",
            kk="Кәдімгі тұтынушы желісінен қосылу",
            en="Connection from a regular consumer network",
        ),
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
        reason_high=Text(
            ru="{value} операций за последние 24 часа",
            kk="Соңғы 24 сағатта {value} операция",
            en="{value} transactions in the last 24 hours",
        ),
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
        reason_high=Text(
            ru="Частота операций в {value} раз выше обычной для клиента",
            kk="Операция жиілігі клиенттің әдеттегісінен {value} есе жоғары",
            en="Transaction frequency is {value}x the user's normal rate",
        ),
        reason_low=Text(
            ru="Частота операций обычная для этого клиента",
            kk="Операция жиілігі бұл клиент үшін қалыпты",
            en="Transaction frequency is normal for this user",
        ),
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
        reason_high=Text(
            ru="{value} операций за последний час",
            kk="Соңғы сағатта {value} операция",
            en="{value} transactions in the last hour",
        ),
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
        reason_high=Text(
            ru="Высокая частота операций для этого клиента",
            kk="Бұл клиент үшін операция жиілігі жоғары",
            en="High transaction frequency for this user",
        ),
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
        reason_high=Text(
            ru="Операция в {value} км от предыдущей",
            kk="Операция алдыңғысынан {value} км қашықтықта",
            en="Transaction {value} km away from the previous one",
        ),
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
        reason_high=Text(
            ru="Всего {value} часов с предыдущей операции",
            kk="Алдыңғы операциядан бері небәрі {value} сағат",
            en="Only {value} hours since the previous transaction",
        ),
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
        reason_high=Text(
            ru="Требуемая скорость перемещения между операциями — {value} км/ч",
            kk="Операциялар арасындағы қажетті жылдамдық — {value} км/сағ",
            en="Implied travel speed of {value} km/h between transactions",
        ),
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
        reason_high=Text(
            ru="Невозможное перемещение: до этой точки не добраться за прошедшее время",
            kk="Мүмкін емес орын ауыстыру: өткен уақытта бұл жерге жету мүмкін емес",
            en="Impossible travel: this location cannot be reached in the elapsed time",
        ),
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
        reason_high=Text(
            ru="Операция в {value}:00",
            kk="Операция сағат {value}:00-де",
            en="Transaction at {value}:00",
        ),
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
        reason_high=Text(
            ru="Операция в ночное время",
            kk="Түнгі уақыттағы операция",
            en="Night-time transaction",
        ),
        reason_low=Text(
            ru="Операция в обычное дневное время",
            kk="Күндізгі қалыпты уақыттағы операция",
            en="Transaction during normal daytime hours",
        ),
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
        reason_high=Text(
            ru="Операция в выходной день",
            kk="Демалыс күнгі операция",
            en="Weekend transaction",
        ),
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
        reason_high=Text(
            ru="Возраст счёта — {value} дней",
            kk="Шот жасы — {value} күн",
            en="Account age is {value} days",
        ),
        reason_low=Text(
            ru="Давно открытый счёт",
            kk="Бұрыннан ашылған шот",
            en="Long-standing account",
        ),
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
        reason_high=Text(
            ru="Недавно открытый счёт",
            kk="Жақында ашылған шот",
            en="Recently opened account",
        ),
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
        reason_high=Text(
            ru="Категория мерчанта повышенного риска (crypto, gambling, переводы, ATM)",
            kk="Жоғары тәуекелді мерчант санаты (crypto, gambling, аударымдар, ATM)",
            en="High-risk merchant category (crypto, gambling, transfers or ATM)",
        ),
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
