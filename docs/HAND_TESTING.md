# Hand Testing — сценарии ТЗ §9

> **Этот файл сгенерирован автоматически.** Не редактируйте его руками —
> измените сценарии в `backend/app/services/scenarios.py` и выполните:
>
> ```bash
> python backend/scripts/export_hand_testing.py
> ```

Все числа ниже — фактические ответы системы, полученные прогоном сценариев
через приложение.

## Как воспроизвести

**Через Swagger.** Поднимите backend и откройте <http://localhost:8000/docs>:

```bash
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

Разверните `POST /scenarios/{key}/run`, нажмите *Try it out*, выберите
сценарий и *Execute*.

**Через curl:**

```bash
curl -X POST "http://localhost:8000/scenarios/multiple_anomalies/run"
```

**Через автотесты:**

```bash
pytest backend/tests/test_scenarios.py -v
```

## Почему сценарии сравнимы между собой

Все пять описывают **одного и того же клиента**: обычная сумма 100, дом —
Казахстан, два известных устройства, три операции в сутки, счёту 800 дней.
Меняется ровно то, что заявлено в названии сценария.

Профиль передаётся в каждом запросе явно, а метки времени зафиксированы
абсолютными значениями. Поэтому результат не зависит ни от накопленной
истории, ни от времени запуска демонстрации.

---

## Сводка

| # | Сценарий | Ожидание по ТЗ | Risk Score | Решение | Уровень |
|---|---|---|---|---|---|
| 1 | Normal transaction | низкий Risk Score, решение APPROVE | **0** | `APPROVE` | `LOW` |
| 2 | New device | Risk Score заметно выше, чем в сценарии 1 | **35** | `CHALLENGE` | `MEDIUM` |
| 3 | Unusual country | повышенный риск | **55** | `CHALLENGE` | `MEDIUM` |
| 4 | Large amount | повышенный риск | **73** | `BLOCK` | `HIGH` |
| 5 | Multiple anomalies | высокий Risk Score, решение BLOCK | **100** | `BLOCK` | `CRITICAL` |
| 6 | High frequency | повышенный риск | **60** | `CHALLENGE` | `MEDIUM` |

**Проверки:**

- рост риска монотонный от сценария 1 к сценарию 5: **да**
- сценарий 1 разрешён (`APPROVE`): **да**
- сценарии 2–4 выше базового: **да**
- сценарий 5 заблокирован (`BLOCK`): **да**
- сценарий 6 выше базового: **да**

Монотонность проверяется на сценариях 1–5: они образуют шкалу нарастания
риска от безобидной покупки к явной атаке. Сценарий 6 в эту шкалу не входит —
он изолирует один признак, а не усиливает предыдущий, и по величине встаёт
в середину.

В разборе каждого сценария ниже строка «Оценка модели без правил» показывает,
что дала **только модель**, до применения политик Risk Engine. Разница между
ней и итоговым Risk Score — вклад правил.

---

## 1. Normal transaction — `normal`

Обычная покупка в продуктовом: привычная сумма, знакомое устройство, домашняя страна, нормальная частота операций.

**Ожидание по ТЗ:** низкий Risk Score, решение APPROVE

| Показатель | Значение |
|---|---|
| Risk Score | **0** |
| Оценка модели без правил | 0 |
| Вероятность фрода | 0.0002 |
| Decision | **`APPROVE`** |
| Risk Level | `LOW` |
| Поднято политиками | нет |

**Политики не сработали** — оценку целиком дала модель.

**Причины:**

- 3 transactions in the last 24 hours
- Large transaction amount in absolute terms

**Вклады признаков** (`shap`, единицы: `logit`):

| Признак | Значение | Вклад | Направление |
|---|---|---|---|
| `travel_speed_kmh` | 1 | -1.1884 | понижает |
| `geo_distance_km` | 3 | -0.7068 | понижает |
| `transaction_frequency` | 3 | +0.6610 | повышает |
| `amount_zscore` | 0.0 | -0.5139 | понижает |
| `amount_log` | 4.62 | +0.4499 | повышает |

---

## 2. New device — `new_device`

Та же покупка, но с незнакомого устройства и из незнакомой сети. Именно такая пара сигналов — сигнатура входа злоумышленника; новый телефон в домашней сети система намеренно не считает поводом для проверки.

**Ожидание по ТЗ:** Risk Score заметно выше, чем в сценарии 1

**Отличия от обычной транзакции:** `device_id`, `ip_address`

| Показатель | Значение |
|---|---|
| Risk Score | **35** |
| Оценка модели без правил | 1 |
| Вероятность фрода | 0.0096 |
| Decision | **`CHALLENGE`** |
| Risk Level | `MEDIUM` |
| Поднято политиками | да |

**Сработавшие политики:**

- `new_device` (минимум 35) — Unrecognized device on an unrecognized network

**Причины:**

- Unrecognized device on an unrecognized network
- New device detected
- Network changed: different IP subnet than the previous transaction
- 3 transactions in the last 24 hours

**Вклады признаков** (`shap`, единицы: `logit`):

| Признак | Значение | Вклад | Направление |
|---|---|---|---|
| `is_new_device` | yes | +4.5276 | повышает |
| `ip_subnet_changed` | yes | +1.3360 | повышает |
| `travel_speed_kmh` | 1 | -0.8366 | понижает |
| `geo_distance_km` | 3 | -0.7305 | понижает |
| `transaction_frequency` | 3 | +0.6580 | повышает |

---

## 3. Unusual country — `unusual_country`

Клиент обычно платит из Казахстана, а операция идёт из Нигерии. Прошло 20 часов — долететь можно, так что невозможного перемещения здесь нет. IP местный: человек физически находится в другой стране.

**Ожидание по ТЗ:** повышенный риск

**Отличия от обычной транзакции:** `country`, `latitude`, `longitude`, `ip_address`, `previous_timestamp`

| Показатель | Значение |
|---|---|
| Risk Score | **55** |
| Оценка модели без правил | 6 |
| Вероятность фрода | 0.0585 |
| Decision | **`CHALLENGE`** |
| Risk Level | `MEDIUM` |
| Поднято политиками | да |

**Сработавшие политики:**

- `high_risk_country` (минимум 55) — Transaction from a high-risk country
- `unusual_country` (минимум 40) — Transaction from an unusual country on an unfamiliar connection

**Причины:**

- Transaction from a high-risk country
- Transaction from an unusual country on an unfamiliar connection
- Implied travel speed of 396 km/h between transactions
- Unusual country: transaction outside the user's home country
- Transaction 7921 km away from the previous one

**Вклады признаков** (`shap`, единицы: `logit`):

| Признак | Значение | Вклад | Направление |
|---|---|---|---|
| `travel_speed_kmh` | 396 | +2.6998 | повышает |
| `is_unusual_country` | yes | +1.0957 | повышает |
| `is_high_risk_country` | yes | +0.8406 | повышает |
| `geo_distance_km` | 7921 | +0.7645 | повышает |
| `hours_since_previous` | 20.00 | -0.7203 | понижает |

---

## 4. Large amount — `large_amount`

Сумма в 25 раз выше обычной для клиента. Всё остальное привычно: своё устройство, домашняя страна, своя сеть.

**Ожидание по ТЗ:** повышенный риск

**Отличия от обычной транзакции:** `amount`

| Показатель | Значение |
|---|---|
| Risk Score | **73** |
| Оценка модели без правил | 73 |
| Вероятность фрода | 0.7321 |
| Decision | **`BLOCK`** |
| Risk Level | `HIGH` |
| Поднято политиками | нет |

**Политики не сработали** — оценку целиком дала модель.

**Причины:**

- Amount deviates 50.0 standard deviations from the user's usual spending
- Transaction amount is 25.0x the user's normal amount
- Large transaction amount in absolute terms
- 3 transactions in the last 24 hours

**Вклады признаков** (`shap`, единицы: `logit`):

| Признак | Значение | Вклад | Направление |
|---|---|---|---|
| `amount_zscore` | 50.0 | +5.8281 | повышает |
| `amount_deviation_ratio` | 25.0 | +3.2486 | повышает |
| `amount_log` | 7.82 | +0.8158 | повышает |
| `travel_speed_kmh` | 1 | -0.8110 | понижает |
| `transaction_frequency` | 3 | +0.5932 | повышает |

---

## 5. Multiple anomalies — `multiple_anomalies`

Захват аккаунта ночью: крупная сумма, незнакомое устройство и сеть, чужая страна повышенного риска, всплеск частоты операций и физически невозможное перемещение — операция в Нигерии через 22 минуты после операции в Казахстане.

**Ожидание по ТЗ:** высокий Risk Score, решение BLOCK

**Отличия от обычной транзакции:** `amount`, `device_id`, `ip_address`, `country`, `latitude`, `longitude`, `transaction_frequency`, `txn_count_last_hour`, `merchant`, `merchant_category`, `timestamp`, `previous_timestamp`

| Показатель | Значение |
|---|---|
| Risk Score | **100** |
| Оценка модели без правил | 100 |
| Вероятность фрода | 0.9997 |
| Decision | **`BLOCK`** |
| Risk Level | `CRITICAL` |
| Поднято политиками | нет |

**Сработавшие политики:**

- `impossible_travel` (минимум 75) — Impossible travel: location cannot be reached in the elapsed time
- `velocity_burst` (минимум 60) — Abnormal transaction velocity
- `high_risk_country` (минимум 55) — Transaction from a high-risk country
- `unusual_country` (минимум 40) — Transaction from an unusual country on an unfamiliar connection
- `new_device` (минимум 35) — Unrecognized device on an unrecognized network

**Причины:**

- Impossible travel: location cannot be reached in the elapsed time
- Abnormal transaction velocity
- Transaction from a high-risk country
- Transaction from an unusual country on an unfamiliar connection
- Unrecognized device on an unrecognized network
- Implied travel speed of 21602 km/h between transactions

**Вклады признаков** (`shap`, единицы: `logit`):

| Признак | Значение | Вклад | Направление |
|---|---|---|---|
| `travel_speed_kmh` | 21602 | +4.0541 | повышает |
| `is_impossible_travel` | yes | +2.9658 | повышает |
| `amount_zscore` | 50.0 | +2.7068 | повышает |
| `txn_count_last_hour` | 12 | +2.0357 | повышает |
| `is_new_device` | yes | +1.8008 | повышает |

---

## 6. High frequency — `high_frequency`

Всплеск числа операций при прочих привычных параметрах: та же сумма, своё устройство, домашняя страна, своя сеть. Изолирует признак частоты — так выглядит начало автоматизированного перебора, когда сумма ещё не выросла.

**Ожидание по ТЗ:** повышенный риск

**Отличия от обычной транзакции:** `transaction_frequency`, `txn_count_last_hour`, `previous_timestamp`

| Показатель | Значение |
|---|---|
| Risk Score | **60** |
| Оценка модели без правил | 5 |
| Вероятность фрода | 0.0503 |
| Decision | **`CHALLENGE`** |
| Risk Level | `MEDIUM` |
| Поднято политиками | да |

**Сработавшие политики:**

- `velocity_burst` (минимум 60) — Abnormal transaction velocity

**Причины:**

- Abnormal transaction velocity
- 9 transactions in the last hour
- Transaction frequency is 7.3x the user's normal rate
- Only 0.10 hours since the previous transaction

**Вклады признаков** (`shap`, единицы: `logit`):

| Признак | Значение | Вклад | Направление |
|---|---|---|---|
| `txn_count_last_hour` | 9 | +4.4220 | повышает |
| `frequency_ratio` | 7.3 | +2.5207 | повышает |
| `transaction_frequency` | 22 | -1.0394 | понижает |
| `hours_since_previous` | 0.10 | +0.5978 | повышает |
| `amount_zscore` | 0.0 | -0.5290 | понижает |

---

## Как менялся Risk Score

```
1. Normal transaction       0  
2. New device              35  ###########
3. Unusual country         55  ##################
4. Large amount            73  ########################
5. Multiple anomalies     100  #################################
6. High frequency          60  ####################
```

Пороги: APPROVE <= 30 < CHALLENGE <= 70 < BLOCK
