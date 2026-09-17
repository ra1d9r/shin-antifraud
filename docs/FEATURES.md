# Справочник признаков

> **Этот файл сгенерирован автоматически.** Не редактируйте его руками —
> измените `backend/app/features/definitions.py` и выполните:
>
> ```bash
> python backend/scripts/export_features.py
> ```

Всего признаков: **27**. Порядок ниже — это порядок колонок вектора,
который сохраняется вместе с моделью.


## §4.1 Отклонение суммы от обычной

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 0 | `amount_log` | число | Логарифм суммы транзакции | Large transaction amount in absolute terms |
| 1 | `amount_deviation_ratio` | число | Во сколько раз сумма отличается от обычной суммы клиента | Transaction amount is {value}x the user's normal amount |
| 2 | `amount_zscore` | число | Отклонение суммы от обычной в стандартных отклонениях клиента | Amount deviates {value} standard deviations from the user's usual spending |
| 3 | `amount_vs_previous_ratio` | число | Отношение суммы к сумме предыдущей транзакции | Amount is {value}x the user's previous transaction |
| 4 | `is_round_amount` | флаг | Круглая сумма — характерна для попыток вывода средств | Round-number amount, typical of cash-out attempts |
| 5 | `is_micro_amount` | флаг | Необычно мелкая сумма — характерна для прозвона карты | Unusually small amount, typical of card-testing probes |

## §4.2 Необычная страна

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 6 | `is_unusual_country` | флаг | Транзакция вне домашней страны клиента | Unusual country: transaction outside the user's home country |
| 7 | `country_changed_from_previous` | флаг | Страна изменилась относительно предыдущей транзакции | Country changed since the previous transaction |
| 8 | `is_high_risk_country` | флаг | Страна входит в список повышенного риска | Transaction from a high-risk country |

## §4.3 Новый device

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 9 | `is_new_device` | флаг | Устройство ранее не встречалось у этого клиента | New device detected |
| 10 | `known_device_count` | число | Сколько устройств известно для клиента | User has {value} known devices |

## §4.4 Изменение IP

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 11 | `ip_changed` | флаг | IP-адрес отличается от предыдущего | IP address changed since the previous transaction |
| 12 | `ip_subnet_changed` | флаг | Сменилась подсеть /24 — другой провайдер или сеть | Network changed: different IP subnet than the previous transaction |

## §4.5 / §4.8 Частота и количество за период

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 13 | `transaction_frequency` | число | Количество транзакций клиента за последние 24 часа | {value} transactions in the last 24 hours |
| 14 | `frequency_ratio` | число | Во сколько раз текущая частота выше обычной для клиента | Transaction frequency is {value}x the user's normal rate |
| 15 | `txn_count_last_hour` | число | Количество транзакций за последний час | {value} transactions in the last hour |
| 16 | `is_high_frequency` | флаг | Частота транзакций существенно выше обычной | High transaction frequency for this user |

## §4.6 Резкое изменение геолокации

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 17 | `geo_distance_km` | число | Расстояние до места предыдущей транзакции, км | Transaction {value} km away from the previous one |
| 18 | `hours_since_previous` | число | Часов прошло с предыдущей транзакции | Only {value} hours since the previous transaction |
| 19 | `travel_speed_kmh` | число | Требуемая скорость перемещения между транзакциями, км/ч | Implied travel speed of {value} km/h between transactions |
| 20 | `is_impossible_travel` | флаг | Перемещение физически невозможно за прошедшее время | Impossible travel: this location cannot be reached in the elapsed time |

## §4.7 Время транзакции

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 21 | `hour_of_day` | число | Час суток | Transaction at {value}:00 |
| 22 | `is_night` | флаг | Ночное время (00:00–05:59) | Night-time transaction |
| 23 | `is_weekend` | флаг | Выходной день | Weekend transaction |

## §4.9 Прочее поведение

| # | Признак | Тип | Описание | Формулировка для XAI |
|---|---|---|---|---|
| 24 | `account_age_days` | число | Возраст счёта в днях | Account age is {value} days |
| 25 | `is_new_account` | флаг | Счёт открыт недавно (моложе 60 дней) | Recently opened account |
| 26 | `is_high_risk_merchant` | флаг | Категория мерчанта повышенного риска (crypto, gambling, переводы, ATM) | High-risk merchant category (crypto, gambling, transfers or ATM) |
