/**
 * Три языка интерфейса (брифинг §6, Положение §1.6).
 *
 * Брифинг §6: «Мультиязычный интерфейс: русский, казахский, английский».
 * Положение §1.6: рабочие языки хакатона — русский и казахский.
 *
 * ## Что переведено, а что нет — и почему
 *
 * Интерфейс состоит из двух разных по назначению слоёв.
 *
 * **Продуктовая поверхность** — заголовки, кнопки, подписи плиток,
 * названия решений, столбцы таблиц. Это то, чем человек пользуется,
 * и оно переведено полностью на все три языка.
 *
 * **Инженерный комментарий** — длинные абзацы, объясняющие, зачем
 * панель существует и что значат её числа. Их 230 штук примерно на
 * десять тысяч слов, и написаны они как объяснение читателю, а не как
 * текст продукта. Они остаются русскими, а в казахском и английском
 * режимах убираются под переключатель: неполный перевод технической
 * прозы читался бы хуже, чем честное её отсутствие.
 *
 * Причина названа прямо, а не спрятана. Двадцать тысяч слов машинного
 * казахского на жюри, у которого казахский рабочий, — это хуже, чем
 * русский комментарий, о котором сказано, что он русский.
 *
 * ## Почему без библиотеки
 *
 * Словарь плоский, строк три сотни, подстановка одна — `{name}` в шесть
 * строк кода. `i18next` добавил бы к сборке больше, чем весит весь этот
 * файл, а плюрализацией и форматами дат здесь никто не пользуется: числа
 * приходят с backend уже посчитанными (ТЗ §11) и форматируются локалью
 * в `format.ts`.
 */

export type Language = 'ru' | 'kk' | 'en'

export const LANGUAGES: readonly Language[] = ['ru', 'kk', 'en'] as const

/** Как язык называется на самом себе — так их подписывают в переключателях. */
export const LANGUAGE_NAMES: Record<Language, string> = {
  ru: 'Рус',
  kk: 'Қаз',
  en: 'Eng',
}

export const DEFAULT_LANGUAGE: Language = 'ru'

const STORAGE_KEY = 'shin.language'

/** Один перевод: три варианта одной строки. */
type Entry = Record<Language, string>

function entry(ru: string, kk: string, en: string): Entry {
  return { ru, kk, en }
}

/**
 * Словарь.
 *
 * Ключ — путь вида `panel.key`, чтобы строку можно было найти по месту,
 * где она показывается. Три перевода лежат рядом: так видно, что ни один
 * не забыт, и это проверяется тестом.
 */
export const DICTIONARY = {
  // --- оболочка ---
  'app.title': entry('Shin — Anti-Fraud System', 'Shin — Anti-Fraud System', 'Shin — Anti-Fraud System'),
  'app.dashboard': entry('Дашборд', 'Бақылау тақтасы', 'Dashboard'),
  'app.simulator': entry('Симулятор', 'Симулятор', 'Simulator'),
  'app.modelLoaded': entry('модель загружена', 'модель жүктелді', 'model loaded'),
  'app.modelMissing': entry('модель не загружена', 'модель жүктелмеген', 'model not loaded'),
  'app.commentary': entry(
    'Показать пояснения (по-русски)',
    'Түсіндірмелерді көрсету (орысша)',
    'Show commentary (in Russian)',
  ),
  'app.commentaryNote': entry(
    'Подробные пояснения к панелям написаны по-русски и на другие языки не переведены.',
    'Панельдерге арналған толық түсіндірмелер орыс тілінде жазылған және басқа тілдерге аударылмаған.',
    'The detailed commentary for each panel is written in Russian and is not translated.',
  ),

  // --- решения ---
  'decision.APPROVE': entry('Разрешить', 'Рұқсат ету', 'Approve'),
  'decision.CHALLENGE': entry('Доп. проверка', 'Қосымша тексеру', 'Challenge'),
  'decision.BLOCK': entry('Заблокировать', 'Бұғаттау', 'Block'),

  'level.LOW': entry('низкий', 'төмен', 'low'),
  'level.MEDIUM': entry('средний', 'орташа', 'medium'),
  'level.HIGH': entry('высокий', 'жоғары', 'high'),
  'level.CRITICAL': entry('критический', 'сыни', 'critical'),

  // --- дашборд: поток ---
  'dash.flow': entry('Поток транзакций', 'Транзакциялар ағыны', 'Transaction flow'),
  'dash.total': entry('Всего транзакций', 'Барлық транзакциялар', 'Total transactions'),
  'dash.fraudRows': entry('Из них фрод', 'Оның ішінде алаяқтық', 'Fraudulent among them'),
  'dash.fraudStopped': entry('Фрод остановлен', 'Алаяқтық тоқтатылды', 'Fraud stopped'),
  'dash.fraudSaved': entry(
    'Спасённый бюджет (Fraud Loss Saved)',
    'Сақталған бюджет (Fraud Loss Saved)',
    'Fraud Loss Saved',
  ),
  'dash.fraudMissed': entry('Фрод пропущен', 'Алаяқтық өткізілді', 'Fraud missed'),
  'dash.fpr': entry(
    'Процент ложных срабатываний (False Positive Rate)',
    'Жалған дабыл пайызы (False Positive Rate)',
    'False Positive Rate',
  ),
  'dash.turnover': entry('Оборот в выборке', 'Іріктемедегі айналым', 'Volume in the sample'),
  'dash.ofAtRisk': entry('из', 'барлығы', 'of'),
  'dash.atRisk': entry('под угрозой', 'қауіп астында', 'at risk'),
  'dash.withoutPolicies': entry('без политик', 'саясаттарсыз', 'without policies'),
  'dash.botheredInVain': entry(
    'честных клиентов побеспокоено зря',
    'адал клиент бекер мазаланды',
    'honest clients bothered for nothing',
  ),
  'dash.approvedFor': entry('ушли с решением APPROVE, на', 'APPROVE шешімімен өтті, сомасы', 'approved, worth'),
  'dash.allTransactions': entry('сумма всех транзакций', 'барлық транзакциялар сомасы', 'sum of all transactions'),

  // --- дашборд: кривая ---
  'dash.tradeOff': entry(
    'Fraud Loss против Customer Inconvenience',
    'Fraud Loss пен Customer Inconvenience',
    'Fraud Loss vs Customer Inconvenience',
  ),
  'dash.threshold': entry('Порог чувствительности', 'Сезімталдық шегі', 'Sensitivity threshold'),
  'dash.current': entry('текущий', 'ағымдағы', 'current'),
  'dash.optimalByCost': entry(
    'оптимальный по стоимости',
    'құны бойынша оңтайлы',
    'cost-optimal',
  ),
  'dash.optimal': entry('оптимальный', 'оңтайлы', 'optimal'),
  'dash.decisions': entry('Решения системы', 'Жүйенің шешімдері', 'System decisions'),
  'dash.legit': entry('Легальных', 'Заңды', 'Legitimate'),
  'dash.fraud': entry('Мошеннических', 'Алаяқтық', 'Fraudulent'),

  // --- политики ---
  'rules.title': entry('Политики поверх модели', 'Модель үстіндегі саясаттар', 'Policies on top of the model'),
  'rules.policy': entry('Политика', 'Саясат', 'Policy'),
  'rules.minScore': entry('Мин. балл', 'Ең төменгі балл', 'Min. score'),
  'rules.precision': entry('Точность', 'Дәлдік', 'Precision'),
  'rules.gained': entry('+ поймано', '+ ұсталды', '+ caught'),
  'rules.friction': entry('+ трение', '+ кедергі', '+ friction'),
  'rules.pricePerFraud': entry('Цена одного фрода', 'Бір алаяқтықтың бағасы', 'Cost per fraud'),
  'rules.noUse': entry('ноль пользы', 'пайдасы жоқ', 'no benefit'),
  'rules.checks': entry('проверок', 'тексеру', 'checks'),
  'rules.costPure': entry('Стоимость: чистая модель', 'Құны: таза модель', 'Cost: model alone'),
  'rules.costWith': entry('Стоимость: модель + политики', 'Құны: модель + саясаттар', 'Cost: model + policies'),
  'rules.payOff': entry('Политики окупаются', 'Саясаттар ақталады', 'Policies pay off'),
  'rules.costMore': entry(
    'Политики дороже, чем экономят',
    'Саясаттар үнемдегеннен қымбат',
    'Policies cost more than they save',
  ),

  // --- адаптивный порог ---
  'adaptive.title': entry(
    'Адаптивный порог по категории мерчанта',
    'Мерчант санаты бойынша бейімделгіш шек',
    'Adaptive threshold by merchant category',
  ),
  'adaptive.mode': entry('Режим', 'Режим', 'Mode'),
  'adaptive.on': entry('включён', 'қосулы', 'on'),
  'adaptive.off': entry('выключен', 'өшірулі', 'off'),
  'adaptive.segments': entry('Сегментов', 'Сегменттер', 'Segments'),
  'adaptive.fallback': entry('Общий запасной порог', 'Жалпы қосалқы шек', 'Shared fallback threshold'),
  'adaptive.forOthers': entry(
    'для категорий без своего',
    'өз шегі жоқ санаттар үшін',
    'for categories without their own',
  ),
  'adaptive.worth': entry('Чего это стоит', 'Бұл не тұрады', 'What it is worth'),
  'adaptive.gain': entry(
    'Выигрыш против одного порога',
    'Бір шекпен салыстырғандағы ұтыс',
    'Gain over a single threshold',
  ),
  'adaptive.worstFold': entry('Худшая часть проверки', 'Тексерудің ең нашар бөлігі', 'Worst validation fold'),
  'adaptive.lostThere': entry('там режим проиграл', 'онда режим ұтылды', 'the mode lost there'),
  'adaptive.wonEverywhere': entry('выиграл везде', 'барлық жерде ұтты', 'won everywhere'),
  'adaptive.frictionVs': entry('Трение против настройки', 'Баптаумен салыстырғандағы кедергі', 'Friction vs configured'),
  'adaptive.fraudCaught': entry('Пойманный фрод', 'Ұсталған алаяқтық', 'Fraud caught'),
  'adaptive.fitted': entry('Подобранные пороги', 'Таңдалған шектер', 'Fitted thresholds'),
  'adaptive.category': entry('Категория', 'Санат', 'Category'),
  'adaptive.thresholdColumn': entry('Порог', 'Шек', 'Threshold'),
  'adaptive.rows': entry('Операций', 'Операциялар', 'Transactions'),
  'adaptive.fraudRows': entry('Из них фрод', 'Оның ішінде алаяқтық', 'Fraudulent'),
  'adaptive.shared': entry('общий', 'жалпы', 'shared'),

  // --- поток ---
  'stream.title': entry('Прогон потока операций', 'Операциялар ағынын өткізу', 'Run a transaction stream'),
  'stream.run': entry('Прогнать', 'Өткізу', 'Run'),
  'stream.running': entry('Идёт прогон', 'Өтуде', 'Running'),
  'stream.processed': entry('Операций прогнано', 'Операциялар өткізілді', 'Transactions processed'),
  'stream.fraudIn': entry('Фрода в потоке', 'Ағындағы алаяқтық', 'Fraud in the stream'),
  'stream.stopped': entry('Фрод остановлен', 'Алаяқтық тоқтатылды', 'Fraud stopped'),
  'stream.missed': entry('пропущено', 'өткізілді', 'missed'),
  'stream.falsePositives': entry('Ложных срабатываний', 'Жалған дабылдар', 'False positives'),
  'stream.averageScore': entry('Средний Risk Score', 'Орташа Risk Score', 'Average Risk Score'),
  'stream.failed': entry('Не удалось прогнать поток', 'Ағынды өткізу мүмкін болмады', 'Could not run the stream'),

  // --- симулятор ---
  'sim.scenarios': entry('Сценарии', 'Сценарийлер', 'Scenarios'),
  'sim.transaction': entry('Транзакция', 'Транзакция', 'Transaction'),
  'sim.analyze': entry('Проанализировать', 'Талдау', 'Analyze Transaction'),
  'sim.analyzing': entry('Анализ…', 'Талдау…', 'Analyzing…'),
  'sim.saving': entry('Сохраняю…', 'Сақталуда…', 'Saving…'),
  'sim.units': entry('единицы вклада', 'үлес бірліктері', 'contribution units'),
  'sim.persist': entry(
    'Сохранять в истории',
    'Тарихта сақтау',
    'Save to history',
  ),
  'sim.scoreCaption': entry('Risk Score / 100', 'Risk Score / 100', 'Risk Score / 100'),
  'sim.riskLevel': entry('Уровень риска', 'Тәуекел деңгейі', 'Risk level'),
  'sim.modelGave': entry('модель дала', 'модель берді', 'the model gave'),
  'sim.raisedTo': entry('политики подняли до', 'саясаттар көтерді', 'policies raised it to'),
  'sim.probability': entry('вероятность', 'ықтималдық', 'probability'),
  'sim.thresholds': entry('пороги', 'шектер', 'thresholds'),
  'sim.reasons': entry('Причины', 'Себептер', 'Reasons'),
  'sim.policiesFired': entry('Сработавшие политики', 'Іске қосылған саясаттар', 'Policies triggered'),
  'sim.topFactors': entry('Основные факторы риска', 'Негізгі тәуекел факторлары', 'Main risk factors'),
  'sim.noFactors': entry(
    'Ни один признак заметно не повышает риск.',
    'Бірде-бір белгі тәуекелді айтарлықтай арттырмайды.',
    'No feature raises the risk noticeably.',
  ),
  'sim.contributions': entry('Вклады признаков', 'Белгілердің үлесі', 'Feature contributions'),
  'sim.method': entry('Метод', 'Әдіс', 'Method'),
  'sim.feature': entry('Признак', 'Белгі', 'Feature'),
  'sim.value': entry('Значение', 'Мән', 'Value'),
  'sim.meaning': entry('Что означает', 'Нені білдіреді', 'What it means'),
  'sim.features': entry('Признаки операции', 'Операция белгілері', 'Transaction features'),

  // --- отчёт и ассистент ---
  'report.title': entry('Отчёт по операции', 'Операция бойынша есеп', 'Transaction report'),
  'report.show': entry('Показать отчёт', 'Есепті көрсету', 'Show report'),
  'report.rebuild': entry('Пересобрать', 'Қайта жинау', 'Rebuild'),
  'report.building': entry('Собираю…', 'Жинау…', 'Building…'),
  'report.copy': entry('Скопировать', 'Көшіру', 'Copy'),
  'report.copied': entry('Скопировано', 'Көшірілді', 'Copied'),
  'report.failed': entry('Отчёт не получен', 'Есеп алынбады', 'Report not received'),
  'report.copyFailed': entry(
    'Скопировать не вышло — выделите текст и скопируйте вручную',
    'Көшіру мүмкін болмады — мәтінді бөлектеп, қолмен көшіріңіз',
    'Copying failed — select the text and copy it manually',
  ),

  'assistant.title': entry('Что сказать клиенту', 'Клиентке не айту керек', 'What to tell the client'),
  'assistant.explain': entry('Объяснить клиенту', 'Клиентке түсіндіру', 'Explain to the client'),
  'assistant.rewrite': entry('Переписать', 'Қайта жазу', 'Rewrite'),
  'assistant.writing': entry('Пишу…', 'Жазу…', 'Writing…'),
  'assistant.failed': entry('Объяснение не получено', 'Түсіндірме алынбады', 'Explanation not received'),
  'assistant.writtenBy': entry('Написала языковая модель', 'Тілдік модель жазды', 'Written by the language model'),
  'assistant.noModel': entry(
    'Текст собран без языковой модели.',
    'Мәтін тілдік моделсіз жиналды.',
    'The text was assembled without the language model.',
  ),
  'assistant.whatGoesOut': entry(
    'Что именно уходит языковой модели',
    'Тілдік модельге не жіберіледі',
    'What exactly is sent to the language model',
  ),

  // --- разметка аналитика ---
  'feedback.title': entry('Разметка аналитика', 'Талдаушы белгілеуі', 'Analyst labelling'),
  'feedback.correct': entry('Вердикт верный', 'Шешім дұрыс', 'Verdict correct'),
  'feedback.incorrect': entry('Вердикт ошибочный', 'Шешім қате', 'Verdict wrong'),

  // --- теневая конфигурация ---
  'shadow.compared': entry('Операций сравнено', 'Салыстырылған операциялар', 'Transactions compared'),
  'shadow.agreed': entry('Решения совпали', 'Шешімдер сәйкес келді', 'Decisions agreed'),
  'shadow.frictionRemoved': entry('Трение снялось бы', 'Кедергі азаяр еді', 'Friction would drop'),
  'shadow.frictionAdded': entry('Трение добавилось бы', 'Кедергі артар еді', 'Friction would grow'),
  'shadow.primaryLive': entry(
    'Основная — работает',
    'Негізгі — жұмыс істейді',
    'Primary — live',
  ),
  'shadow.shadowOnlyCounts': entry(
    'Теневая — только считает',
    'Көлеңкелі — тек санайды',
    'Shadow — counts only',
  ),
  'shadow.whoDecided': entry('Кто что решил', 'Кім не шешті', 'Who decided what'),
  'shadow.primary': entry('Основная', 'Негізгі', 'Primary'),
  'shadow.shadow': entry('Теневая', 'Көлеңкелі', 'Shadow'),
  'shadow.lastDisagreements': entry(
    'Последние расхождения',
    'Соңғы алшақтықтар',
    'Latest disagreements',
  ),
  'shadow.sameConfig': entry(
    'Теневая конфигурация совпадает с основной — сравнивать нечего.',
    'Көлеңкелі конфигурация негізгімен бірдей — салыстыратын ештеңе жоқ.',
    'The shadow configuration matches the primary one — nothing to compare.',
  ),

  // --- граф связей ---
  'graph.scanned': entry('Просмотрено операций', 'Қаралған операциялар', 'Transactions scanned'),
  'graph.users': entry('Клиентов в них', 'Ондағы клиенттер', 'Clients in them'),
  'graph.deviceGroups': entry(
    'Групп с общим устройством',
    'Ортақ құрылғылы топтар',
    'Groups sharing a device',
  ),
  'graph.subnetGroups': entry(
    'Групп только по подсети',
    'Тек ішкі желі бойынша топтар',
    'Groups by subnet only',
  ),
  'graph.weakLink': entry('связь слабая', 'байланыс әлсіз', 'weak link'),
  'graph.badLink': entry('связь объясняется плохо', 'байланысты түсіндіру қиын', 'hard to explain'),
  'graph.clients': entry('Клиенты', 'Клиенттер', 'Clients'),
  'graph.link': entry('Связь', 'Байланыс', 'Link'),
  'graph.through': entry('Через что', 'Не арқылы', 'Through what'),
  'graph.flagged': entry('Помечено', 'Белгіленді', 'Flagged'),
  'graph.maxRisk': entry('Макс. риск', 'Ең жоғары тәуекел', 'Max risk'),

  // --- дрейф ---
  'drift.overall': entry('Общая картина', 'Жалпы көрініс', 'Overall picture'),
  'drift.observed': entry(
    'Наблюдений с запуска',
    'Іске қосылғаннан бергі бақылаулар',
    'Observations since start',
  ),
  'drift.overLimit': entry('Признаков за границей', 'Шектен шыққан белгілер', 'Features past the limit'),
  'drift.baselineRows': entry('Эталон снят по', 'Эталон алынған', 'Baseline taken from'),
  'drift.datasetRows': entry('строкам датасета', 'датасет жолдары', 'dataset rows'),
  'drift.worstFeature': entry(
    'по самому разошедшемуся признаку',
    'ең көп ауытқыған белгі бойынша',
    'by the most divergent feature',
  ),
  'drift.howSplit': entry(
    'как разложился поток',
    'ағын қалай бөлінді',
    'how the stream split up',
  ),
  'drift.state': entry('Состояние', 'Күйі', 'State'),

  // --- разметка аналитика ---
  'feedback.labeled': entry('Размечено операций', 'Белгіленген операциялар', 'Transactions labelled'),
  'feedback.verdictRight': entry(
    'Вердикт признан верным',
    'Шешім дұрыс деп танылды',
    'Verdict confirmed right',
  ),
  'feedback.measuredPrecision': entry(
    'Точность на подтверждённом',
    'Расталғандағы дәлдік',
    'Precision on confirmed',
  ),
  'feedback.falsePositives': entry('Ложных срабатываний', 'Жалған дабылдар', 'False positives'),
  'feedback.fraudMissed': entry('Пропущено фрода', 'Өткізілген алаяқтық', 'Fraud missed'),
  'feedback.botheredInVain': entry(
    'честных клиентов побеспокоили зря',
    'адал клиенттер бекер мазаланды',
    'honest clients bothered for nothing',
  ),
  'feedback.marked': entry('Размечено', 'Белгіленді', 'Labelled'),
  'feedback.turnedFraud': entry('Оказалось фродом', 'Алаяқтық болып шықты', 'Turned out fraudulent'),
  'feedback.turnedHonest': entry('Оказалось честным', 'Адал болып шықты', 'Turned out honest'),
  'feedback.policiesOnConfirmed': entry(
    'Политики на подтверждённых операциях',
    'Расталған операциялардағы саясаттар',
    'Policies on confirmed transactions',
  ),
  'feedback.firedInLabels': entry(
    'Срабатываний в разметке',
    'Белгілеудегі іске қосылулар',
    'Fired in labelled data',
  ),
  'feedback.confirmedFraud': entry('Подтверждённый фрод', 'Расталған алаяқтық', 'Confirmed fraud'),

  // --- общее для таблиц и состояний ---
  'common.decision': entry('Решение', 'Шешім', 'Decision'),
  'common.legit': entry('Легальные', 'Заңды', 'Legitimate'),
  'common.fraud': entry('Фрод', 'Алаяқтық', 'Fraud'),
  'common.amount': entry('Сумма', 'Сома', 'Amount'),
  'common.forAmount': entry('На сумму', 'Сомасы', 'For amount'),
  'common.transaction': entry('Операция', 'Операция', 'Transaction'),
  'common.operations': entry('Операций', 'Операциялар', 'Transactions'),
  'common.yes': entry('да', 'иә', 'yes'),
  'common.no': entry('нет', 'жоқ', 'no'),
  'common.loading': entry('Загружаю…', 'Жүктелуде…', 'Loading…'),

  'error.analyticsTitle': entry('Аналитика недоступна', 'Талдау қолжетімсіз', 'Analytics unavailable'),
  'error.analyticsLoading': entry('Загружаю аналитику', 'Талдау жүктелуде', 'Loading analytics'),
  'error.scenariosTitle': entry(
    'Сценарии не загрузились',
    'Сценарийлер жүктелмеді',
    'Scenarios failed to load',
  ),
  'error.scenariosFailed': entry(
    'Не удалось загрузить сценарии',
    'Сценарийлерді жүктеу мүмкін болмады',
    'Could not load the scenarios',
  ),
  'error.title': entry('Ошибка', 'Қате', 'Error'),
  'error.backendAddress': entry('Адрес backend', 'Backend мекенжайы', 'Backend address'),
  'error.staleAnalytics': entry('Аналитика устарела', 'Талдау ескірген', 'Analytics are stale'),
  'error.modelInfo': entry(
    'Сведения о модели не получены',
    'Модель туралы мәліметтер алынбады',
    'Model details not received',
  ),
  'error.panelUnavailable': entry('Панель недоступна', 'Панель қолжетімсіз', 'Panel unavailable'),

  // --- симулятор, продолжение ---
  'sim.expectation': entry('Ожидание по ТЗ', 'ТЗ бойынша күтілетіні', 'Expected per the spec'),
  'sim.clientContext': entry(
    'Контекст клиента — что система знает о нём до этой операции',
    'Клиент контексті — жүйе бұл операцияға дейін не біледі',
    'Client context — what the system knows before this transaction',
  ),
  'sim.labelling': entry('Разметка', 'Белгілеу', 'Labelling'),
  'sim.systemRight': entry('Система права?', 'Жүйе дұрыс па?', 'Was the system right?'),
  'sim.rawJson': entry(
    'Исходный JSON-ответ API',
    'API-дің бастапқы JSON жауабы',
    'Raw JSON response from the API',
  ),

  'curve.fraudMissed': entry('Пропущено фрода', 'Өткізілген алаяқтық', 'Fraud missed'),
  'curve.frictionHit': entry('Задето честных', 'Адалдар қозғалды', 'Honest clients hit'),
  'curve.fraudLoss': entry('Потери от фрода', 'Алаяқтықтан шығын', 'Fraud loss'),
  'curve.checksCost': entry('Стоимость проверок', 'Тексерулер құны', 'Cost of checks'),
  'curve.total': entry('Итого', 'Жиыны', 'Total'),

  // Метрика, по которой посчитана кривая (брифинг §5.C). Без неё
  // деньги на графике появляются ниоткуда.
  'cost.metric': entry('Метрика', 'Метрика', 'Metric'),
  'cost.missedFraud': entry(
    'пропущенный фрод — {ratio} суммы плюс {fixed}',
    'өткізілген алаяқтық — соманың {ratio} үлесі және {fixed}',
    'missed fraud — {ratio} of the amount plus {fixed}',
  ),
  'cost.extraCheck': entry(
    'лишняя проверка — {amount}',
    'артық тексеру — {amount}',
    'an unnecessary check — {amount}',
  ),
  'cost.tunedAt': entry(
    'настроена в рантайме',
    'жұмыс кезінде бапталған',
    'tuned at runtime',
  ),
  'curve.precision': entry('Точность (Precision)', 'Дәлдік (Precision)', 'Precision'),
  'curve.recall': entry('Полнота (Recall)', 'Толықтық (Recall)', 'Recall'),
  'curve.precisionNote': entry(
    'доля настоящего фрода среди помеченного',
    'белгіленгендер ішіндегі нағыз алаяқтық үлесі',
    'share of real fraud among flagged',
  ),
  'curve.recallNote': entry(
    'доля пойманного фрода от всего',
    'барлық алаяқтықтан ұсталғаны',
    'share of all fraud that was caught',
  ),
  'curve.chartLabel': entry('Кривая компромисса', 'Ымыра қисығы', 'Trade-off curve'),
  'curve.qualityLabel': entry(
    'Точность и полнота по порогу',
    'Шек бойынша дәлдік пен толықтық',
    'Precision and recall by threshold',
  ),
  'model.algorithm': entry('Алгоритм', 'Алгоритм', 'Algorithm'),

  'sim.contribution': entry('Вклад', 'Үлес', 'Contribution'),
  'sim.direction': entry('Направление', 'Бағыты', 'Direction'),

  'shadow.identical': entry(
    'Теневая конфигурация совпадает с основной — сравнивать нечего.',
    'Көлеңкелі конфигурация негізгімен бірдей — салыстыратын ештеңе жоқ.',
    'The shadow configuration matches the primary one — nothing to compare.',
  ),
  'feedback.falseOnes': entry('Ложные', 'Жалған', 'False'),

  // --- карта аномалий ---
  'map.title': entry('Карта аномалий', 'Ауытқулар картасы', 'Anomaly map'),
  'map.lowFraud': entry('фрода мало', 'алаяқтық аз', 'little fraud'),
  'map.someFraud': entry('фрод заметен', 'алаяқтық байқалады', 'noticeable fraud'),
  'map.mostlyFraud': entry('почти всё фрод', 'дерлік бәрі алаяқтық', 'mostly fraud'),
  'map.highRiskCountry': entry(
    'страна повышенного риска',
    'жоғары тәуекелді ел',
    'high-risk country',
  ),
  'map.ordinaryCountry': entry('обычная страна', 'қарапайым ел', 'ordinary country'),
  'map.hovered': entry('Под курсором', 'Меңзер астында', 'Under the cursor'),
  'map.worst': entry('Самая тревожная', 'Ең алаңдатарлық', 'Most alarming'),
  'map.operations': entry('Операций', 'Операциялар', 'Transactions'),
  'map.fraudShare': entry('Доля фрода', 'Алаяқтық үлесі', 'Fraud share'),
  'map.flaggedShare': entry('Задержано системой', 'Жүйе ұстады', 'Flagged by the system'),

  // --- остальные панели ---
  'graph.title': entry('Связи между клиентами', 'Клиенттер арасындағы байланыс', 'Links between clients'),
  'shadow.title': entry('Теневая конфигурация', 'Көлеңкелі конфигурация', 'Shadow configuration'),
  'drift.title': entry('Сдвиг распределения', 'Таралымның ығысуы', 'Distribution drift'),
  'model.title': entry('Модель', 'Модель', 'Model'),

  // --- сноски под плитками и подписи на графиках ---
  //
  // Эти строки прошлая правка пропустила: она перевела заголовки
  // и подписи, но не то, что написано под ними мелким шрифтом.
  // Видно их на каждой вкладке, поэтому непереведёнными они заметнее
  // многого другого.

  'common.outOf': entry('{shown} из {total}', '{total} ішінен {shown}', '{shown} of {total}'),
  'common.notMeasured': entry('не измерено', 'өлшенбеген', 'not measured'),
  'common.noteOperations': entry('операций', 'операция', 'operations'),
  'common.noteForAmount': entry('на {amount}', '{amount} сомаға', 'for {amount}'),

  'cost.fraudLoss': entry('потери от фрода', 'алаяқтықтан шығын', 'fraud losses'),
  'cost.checkCost': entry('стоимость проверок', 'тексеру құны', 'cost of checks'),
  'cost.total': entry('итого', 'барлығы', 'total'),
  'cost.cheapest': entry('дешевле всего ({score})', 'ең арзаны ({score})', 'cheapest ({score})'),
  'cost.sameAsNow': entry('как сейчас', 'қазіргідей', 'same as now'),
  'cost.cheaperBy': entry(
    'на {amount} дешевле текущего',
    'қазіргіден {amount} арзан',
    '{amount} cheaper than now',
  ),
  'cost.dearerBy': entry(
    'на {amount} дороже текущего',
    'қазіргіден {amount} қымбат',
    '{amount} dearer than now',
  ),
  'cost.markNow': entry('сейчас', 'қазір', 'now'),
  'cost.markOptimum': entry('оптимум', 'оңтайлы', 'optimum'),
  'cost.atThreshold': entry('порог {score}', '{score} шегі', 'threshold {score}'),

  'quality.precisionLegend': entry('точность (Precision)', 'дәлдік (Precision)', 'precision'),
  'quality.recallLegend': entry('полнота (Recall)', 'толықтық (Recall)', 'recall'),
  'quality.precisionShort': entry('точность {value}', 'дәлдік {value}', 'precision {value}'),
  'quality.recallShort': entry('полнота {value}', 'толықтық {value}', 'recall {value}'),

  'dashboard.raisedByRules': entry(
    'оценка поднята политиками у {count} операций',
    '{count} операцияда бағаны саясат көтерді',
    'policies raised the score on {count} operations',
  ),

  'adaptive.appliedNote': entry(
    'пороги применяются к решениям',
    'шектер шешімдерге қолданылады',
    'thresholds are applied to decisions',
  ),
  'adaptive.commonNote': entry(
    'решения на общем пороге',
    'шешімдер ортақ шекте',
    'decisions use the common threshold',
  ),
  'adaptive.ownThreshold': entry(
    'свой порог у {count}',
    '{count} сегментте өз шегі бар',
    'own threshold for {count}',
  ),
  'adaptive.foldsNote': entry(
    'в среднем; положительных частей {positive} из {folds}',
    'орташа есеппен; {folds} бөліктің {positive} оң',
    'on average; {positive} of {folds} folds positive',
  ),
  'adaptive.frictionNote': entry(
    '{before} → {after} задержанных честных операций',
    '{before} → {after} ұсталған адал операция',
    '{before} → {after} delayed legitimate operations',
  ),
  'adaptive.operationsNote': entry(
    '{before} → {after} операций',
    '{before} → {after} операция',
    '{before} → {after} operations',
  ),

  'feedback.fraudOfFlagged': entry(
    '{hits} фрода из {flagged} помеченных',
    'белгіленген {flagged} ішінен {hits} алаяқтық',
    '{hits} fraud of {flagged} flagged',
  ),
  'feedback.noLabels': entry('Разметки пока нет', 'Әзірге белгілеу жоқ', 'No labels yet'),
  'feedback.headline': entry(
    'Размечено операций: {total} — система права в {correct} из {total}',
    'Белгіленген операция: {total} — жүйе {total} ішінен {correct} рет дұрыс',
    'Labeled operations: {total} — the system was right {correct} of {total} times',
  ),

  'drift.statusStable': entry('стабильно', 'тұрақты', 'stable'),
  'drift.statusModerate': entry('умеренный сдвиг', 'шамалы ығысу', 'moderate drift'),
  'drift.statusSignificant': entry('существенный сдвиг', 'елеулі ығысу', 'significant drift'),
  'drift.statusNotMeasurable': entry('несравним', 'салыстырылмайды', 'not comparable'),
  'drift.statusCollecting': entry('копим наблюдения', 'бақылау жинақталуда', 'collecting data'),
  'drift.minObservations': entry('минимум {count}', 'кемінде {count}', 'at least {count}'),
  'drift.notCountedYet': entry('пока не считаем', 'әзірге есептемейміз', 'not computed yet'),

  'shadow.policiesOn': entry('политики включены', 'саясат қосулы', 'policies on'),
  'shadow.policiesOff': entry('политики выключены', 'саясат өшірулі', 'policies off'),

  'graph.linkDevice': entry('общее устройство', 'ортақ құрылғы', 'shared device'),
  'graph.linkSubnet': entry('только подсеть', 'тек ішкі желі', 'subnet only'),

  'sim.formInvalid': entry(
    'Форма заполнена неверно — запрос не отправлен',
    'Форма дұрыс толтырылмаған — сұрау жіберілмеді',
    'The form is invalid — the request was not sent',
  ),
  'sim.network': entry('Сеть', 'Желі', 'Network'),
  'sim.labelNotSaved': entry(
    'Метку не удалось сохранить',
    'Белгіні сақтау мүмкін болмады',
    'The label could not be saved',
  ),
  'sim.confirmedFraud': entry(
    'операция подтверждена как мошенническая',
    'операция алаяқтық деп расталды',
    'the operation was confirmed as fraud',
  ),
  'sim.confirmedLegit': entry(
    'операция подтверждена как добросовестная',
    'операция адал деп расталды',
    'the operation was confirmed as legitimate',
  ),
  'sim.raises': entry('повышает', 'арттырады', 'raises'),
  'sim.lowers': entry('понижает', 'төмендетеді', 'lowers'),

  // Имена полей — технические и одинаковы на всех языках (ТЗ §3).
  // Переводится только уточнение в скобках.
  'form.commaSeparated': entry('через запятую', 'үтір арқылы', 'comma-separated'),

  'app.modelUnavailable': entry(
    'Сведения о модели недоступны',
    'Модель туралы мәлімет қолжетімсіз',
    'Model details are unavailable',
  ),

  // Сообщения об отказах, которые придумывает сам клиент. То, что
  // прислал backend, всегда предпочтительнее: он знает точнее.
  'api.notFound': entry(
    'Адрес не найден на backend',
    'Мекенжай backend-те табылмады',
    'The address was not found on the backend',
  ),
  'api.methodNotAllowed': entry(
    'Метод не поддерживается',
    'Әдіс қолдалмайды',
    'The method is not supported',
  ),
  'api.tooSlow': entry(
    'Backend не успел ответить',
    'Backend жауап беріп үлгермеді',
    'The backend did not answer in time',
  ),
  'api.serverError': entry(
    'Backend ответил ошибкой',
    'Backend қатемен жауап берді',
    'The backend returned an error',
  ),
  'api.rejected': entry('Запрос отклонён', 'Сұрау қабылданбады', 'The request was rejected'),
  'api.timedOut': entry(
    'Backend не ответил за {seconds} секунд. Столько не занимает даже пробуждение уснувшего сервиса — похоже, он недоступен. Попробуйте обновить страницу.',
    'Backend {seconds} секундта жауап бермеді. Ұйқыдағы сервисті ояту да сонша уақыт алмайды — қолжетімсіз сияқты. Бетті жаңартып көріңіз.',
    'The backend did not answer within {seconds} seconds. Even waking a sleeping service takes less — it appears to be unavailable. Try reloading the page.',
  ),
  'api.notJson': entry(
    'Backend ответил не в формате JSON. Между браузером и backend может стоять прокси.',
    'Backend JSON форматында жауап бермеді. Браузер мен backend арасында прокси тұруы мүмкін.',
    'The backend did not answer with JSON. There may be a proxy between the browser and the backend.',
  ),
  'drift.observations': entry(
    'Наблюдений: {count}',
    'Бақылау саны: {count}',
    'Observations: {count}',
  ),
  'drift.observationsShort': entry(
    'Наблюдений: {observed} из {minimum} — нужно ещё {left}, чтобы называть числа',
    'Бақылау саны: {minimum} ішінен {observed} — сандарды атау үшін тағы {left} керек',
    'Observations: {observed} of {minimum} — {left} more are needed before quoting numbers',
  ),
  'drift.binTraining': entry('обучающее: {share}', 'оқыту: {share}', 'training: {share}'),
  'drift.binNow': entry('сейчас: {share}', 'қазір: {share}', 'now: {share}'),

  'stream.ofProcessed': entry(
    'из {total} операций',
    '{total} операциядан',
    'of {total} operations',
  ),
  'stream.raisedByPolicies': entry(
    'оценку подняли политики у {count}',
    '{count} операцияда бағаны саясат көтерді',
    'policies raised the score on {count}',
  ),

  'form.expectedNumber': entry(
    '{field}: ожидалось число, введено «{value}»',
    '{field}: сан күтілді, енгізілгені «{value}»',
    '{field}: a number was expected, got “{value}”',
  ),

  'api.unreachable': entry(
    'Backend недоступен по адресу {url}. Поднят ли он?',
    '{url} мекенжайында backend қолжетімсіз. Ол іске қосылған ба?',
    'The backend is unreachable at {url}. Is it running?',
  ),
  'api.noAnswerIn': entry(
    'Backend не ответил за {seconds} секунд',
    'Backend {seconds} секундта жауап бермеді',
    'The backend did not answer within {seconds} seconds',
  ),

  'api.wakeUp': entry(
    'Сервис мог уснуть после простоя — первый запрос его будит. Это занимает до минуты, страницу перезагружать не нужно.',
    'Сервис тоқтап тұрып ұйықтап қалуы мүмкін — алғашқы сұрау оны оятады. Бұл бір минутқа дейін уақыт алады, бетті жаңартудың қажеті жоқ.',
    'The service may have gone to sleep after idling — the first request wakes it. This takes up to a minute; there is no need to reload the page.',
  ),
} as const

export type TranslationKey = keyof typeof DICTIONARY

/** Что подставляется в строку вида «свой порог у {count}». */
export type Substitutions = Record<string, string | number>

/**
 * Перевод по ключу.
 *
 * Неизвестный ключ возвращается как есть — это видно. Незаполненная
 * подстановка тоже остаётся на месте текстом `{count}`: показать её
 * заметнее, чем тихо подставить пустоту и оставить в интерфейсе
 * фразу с дырой посередине.
 *
 * Подстановки нужны там, где в строке есть число. Склеивать такие
 * фразы из кусков нельзя: «свой порог у 13» по-английски «own
 * threshold for 13», а по-казахски число уходит в начало — порядок
 * слов разный, и конкатенация даёт ломаный язык хотя бы в одном
 * из трёх.
 */
export function translate(
  key: TranslationKey,
  language: Language,
  values?: Substitutions,
): string {
  const found = DICTIONARY[key]
  if (!found) return key
  const text = found[language] ?? found[DEFAULT_LANGUAGE]
  if (values === undefined) return text
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? String(values[name]) : whole,
  )
}

/** Переводчик, связанный с выбранным языком. */
export type Translator = (key: TranslationKey, values?: Substitutions) => string

/**
 * Язык, выбранный раньше.
 *
 * Чтение обёрнуто: в приватном окне и при запрещённых данных сайта
 * обращение к `localStorage` бросает, а язык интерфейса не та вещь,
 * ради которой стоит падать.
 */
export function storedLanguage(): Language {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && (LANGUAGES as readonly string[]).includes(saved)) {
      return saved as Language
    }
  } catch {
    // Недоступное хранилище — это язык по умолчанию, а не ошибка.
  }
  return DEFAULT_LANGUAGE
}

export function rememberLanguage(language: Language): void {
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Выбор не переживёт перезагрузку — это всё, что случится.
  }
}
