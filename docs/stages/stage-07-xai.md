# Этап 07 — Explainable AI

**Статус:** `DONE`
**Дата:** 2026-09-17
**Пункты ТЗ:** §7 (Risk Score, Decision, 3–5 факторов риска, влияние каждого)

---

## Что построено

```
features + RiskAssessment
        │
        ▼
ContributionEngine        ← выбирается лучший доступный
        │                   shap -> lightgbm_native -> ablation
   вклады признаков
        │
        ▼
   отбор топ-N (3..5)
        │
        ▼
     narrator             ← подставляет значение в шаблон из реестра
        │
        ▼
   Explanation
   ├── factors        вклад каждого признака с направлением
   ├── policy_reasons сработавшие политики Risk Engine
   ├── reasons        плоский список причин без повторов
   └── summary        одна фраза про решение целиком
```

| Файл | Назначение |
|---|---|
| `backend/app/xai/contributions.py` | три движка вкладов и выбор лучшего доступного |
| `backend/app/xai/narrator.py` | перевод признака в формулировку для человека |
| `backend/app/xai/explainer.py` | отбор факторов, сборка объяснения |
| `backend/tests/test_xai.py` | 23 теста |

> Отступление от плана: вместо двух файлов (`explainer.py`, `narrator.py`)
> сделано три. Движки вкладов вынесены отдельно, потому что их три штуки
> с разными зависимостями, и смешивать их с логикой отбора факторов
> означало бы держать в одном файле две несвязанные ответственности.

---

## Решения

### Объяснение показывает и модель, и политики

Это главное решение этапа. Показывать только вклады признаков было бы
неполно, а местами прямо обманчиво. В сценарии «новое устройство» модель
даёт **1 балл**, а итоговые 35 — целиком заслуга правила `new_device`.
Объяснение, которое перечисляет только признаки, оставило бы пользователя
в недоумении: почему при таких слабых вкладах решение CHALLENGE.

Поэтому `Explanation` содержит два независимых источника: `factors`
(вклады модели) и `policy_reasons` (сработавшие политики), а плоский
список `reasons` ставит политики первыми — они детерминированы и обычно
и определяют решение.

### Три движка вкладов вместо одного

| Движок | Что считает | Когда используется |
|---|---|---|
| `shap` | точные значения Шепли (`shap.TreeExplainer`) | установлен пакет `shap` |
| `lightgbm_native` | те же значения Шепли, встроенные в LightGBM | модель LightGBM, `shap` не установлен |
| `ablation` | изменение вероятности при замене признака на эталон | любая модель |

Средний вариант появился не для полноты картины: LightGBM умеет считать
TreeSHAP сам (`pred_contrib=True`). Это значит, что **объяснения остаются
точными даже в минимальной установке без пакета `shap`** — а не деградируют
до приближения. Проверено тестом: числа обоих движков совпадают до `1e-6`.

### Честность про единицы измерения

SHAP и встроенный расчёт LightGBM объясняют **логит базовой модели до
калибровки**, а не итоговую вероятность. Это не дефект, но умолчать
об этом нельзя, поэтому результат несёт поле `units`.

Калибровка сигмоидой монотонна, поэтому порядок и знак вкладов сохраняются:
признак, повышающий логит, повышает и Risk Score. Абсолютные величины при
этом в единицах логита.

`ablation` наоборот работает с итоговой калиброванной вероятностью —
подставляет вместо признака его эталонное значение и смотрит, насколько
изменилась вероятность. Метод грубее (не учитывает взаимодействия
признаков), зато объясняет ровно то число, из которого считается Risk Score.

### Эталон берётся из данных, а не выдумывается

Для `ablation` нужен эталон «типичной безопасной транзакции». Задавать его
руками означало бы завести ещё один источник правды, который разойдётся
с признаками. Вместо этого в артефакт модели добавлено поле
`feature_baseline` — **медианы признаков по легальным строкам обучающей
выборки**. Версия формата модели поднята до `1.1`.

---

## Найденный дефект

Первый прогон дал в сценарии 3 такой список причин:

```
- Transaction from a high-risk country      <- от политики high_risk_country
- Transaction from an unusual country ...
- Implied travel speed of 396 km/h ...
- Unusual country: transaction outside ...
- Transaction from a high-risk country      <- от признака is_high_risk_country
```

Одна и та же фраза дважды. Причина в том, что политика и признак описывают
один сигнал и формулировки совпали дословно. Для пользователя это выглядит
как ошибка системы.

**Решение.** `Explanation.reasons` убирает повторы без учёта регистра,
сохраняя порядок: политики первыми, затем факторы модели. Зафиксировано
тестом `test_reasons_have_no_duplicates`.

Побочно убрано предупреждение SHAP о смене формата вывода — оно печаталось
на **каждый** запрос. Оба формата в коде обрабатываются, так что это был
чистый шум в логах.

---

## Результат на сценариях ТЗ §9

Сценарий 3 — оценку подняли политики, и это видно:

```
3 Unusual country   Risk Score: 55   Decision: CHALLENGE   (MEDIUM)
  Risk score 55/100 resulted in CHALLENGE. 2 policy rule(s) applied on top
  of the model, and 5 model factor(s) contributed to the score.
  Reasons:
    - Transaction from a high-risk country
    - Transaction from an unusual country on an unfamiliar connection
    - Implied travel speed of 396 km/h between transactions
    - Unusual country: transaction outside the user's home country
    - Transaction 7922 km away from the previous one
  Feature contributions (logit):
    travel_speed_kmh      = 396   +2.6998  INCREASES_RISK
    is_unusual_country    = yes   +1.0957  INCREASES_RISK
    is_high_risk_country  = yes   +0.8406  INCREASES_RISK
    geo_distance_km       = 7922  +0.7645  INCREASES_RISK
    hours_since_previous  = 20.00 -0.7203  DECREASES_RISK
```

Последняя строка показательна: «прошло 20 часов» **понижает** риск —
за такое время долететь можно, так что дальняя страна перестаёт быть
невозможным перемещением. Объяснение показывает не только обвинение,
но и оправдание.

Сценарий 5 — сработало всё сразу:

```
5 Multiple anomalies   Risk Score: 100   Decision: BLOCK   (CRITICAL)
  Reasons:
    - Impossible travel: location cannot be reached in the elapsed time
    - Abnormal transaction velocity
    - Transaction from a high-risk country
    - Transaction from an unusual country on an unfamiliar connection
    - Unrecognized device on an unrecognized network
    - Implied travel speed of 23765 km/h between transactions
  Feature contributions (logit):
    travel_speed_kmh      = 23765  +4.0328
    is_impossible_travel  = yes    +3.0160
    amount_zscore         = 50.0   +2.8165
    txn_count_last_hour   = 12     +2.0790
    is_new_device         = yes    +1.8471
```

---

## Производительность

Объяснение лежит в пути каждого запроса `/predict`, поэтому замерено:

| Движок | Время на одно объяснение |
|---|---|
| `shap` | 3.63 мс |
| `lightgbm_native` | 3.61 мс |
| `ablation` | 4.21 мс |

`ablation` делает 29 предсказаний вместо одного (исходное, эталонное и по
одному на каждый из 27 признаков), но все они идут одним батчем, поэтому
проигрыш небольшой. Для батчевой обработки метод не предназначен.

---

## Проверка DoD

| # | Критерий | Результат |
|---|---|---|
| 1 | В ответе не менее 3 и не более 5 факторов | ✅ `test_factor_count_within_required_range` |
| 2 | У каждого фактора есть направление и величина вклада | ✅ `test_each_factor_has_direction_and_magnitude` |
| 3 | При изменении входа меняется состав факторов | ✅ `test_changing_input_changes_explanation` |

Требование о минимум трёх факторах выполняется даже для ничем не
примечательной транзакции: если значимых вкладов меньше трёх, список
дополняется следующими по величине.

Отдельно проверяется согласованность движков: `test_shap_and_native_agree`
сверяет SHAP и встроенный расчёт LightGBM до `1e-6`, а
`test_engines_agree_on_leading_anomaly` требует, чтобы все три движка
сходились хотя бы на одном ведущем признаке.

Автотесты — `backend/tests/test_xai.py`, **23 passed**.
Полный прогон: **119 passed**.

---

## Следующий этап

[Этап 08 — FastAPI](../STAGES.md#этап-08--fastapi): HTTP-слой, который
соберёт цепочку целиком — признаки, модель, Risk Engine, XAI — и вернёт
её одним JSON-ответом.
