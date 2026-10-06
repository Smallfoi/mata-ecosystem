# Единый контракт данных экосистемы МАТА

> **Единый источник правды** для трёх продуктов: «Квартал» (Runner App), Sport Store (App) и Сайт.
> Все три приложения и backend реализуют ОДНИ и те же сущности, эндпоинты и потоки.
> Менять контракт — только здесь, синхронно во всех проектах. Связанные документы: `RECOMMENDATION.md`, `ECOSYSTEM.md`.
>
> Статус: контракт согласован с уже реализованными в Sport Store моделями (DTO) и репозиториями
> (`mata_store/lib/data/repositories/*`, `mata_store/lib/models/*`). Backend пока не поднят
> (`ApiConfig.useMock = true`). При запуске backend все три приложения переключаются на эти эндпоинты.

---

## 0. Принципы

1. **Один аккаунт (SSO).** Один пользователь = один `userId`. Логин/регистрация в любом приложении → единый JWT работает во всех трёх.
2. **Один баланс баллов.** Баллы начисляются в любом продукте (бег в «Квартале», покупка в Store), баланс общий.
3. **Одни данные.** Товары, заказы, уведомления, кроссовки — одни и те же сущности во всех приложениях.
4. **Формат.** REST + JSON. Все даты — ISO 8601 (UTC). Деньги — рубли (число). `id` — строка.
5. **Авторизация.** Заголовок `Authorization: Bearer <JWT>` на всех приватных эндпоинтах.
6. **Источник цен/остатков — 1С.** Описания/фото/теги/видео — admin-панель. Контракт — то, что отдаёт backend наружу (не внутреннее представление 1С).

---

## 1. Сервисы (микро-домены)

| Сервис | Назначение | Кто пишет | Кто читает |
|---|---|---|---|
| **Auth** | SSO, JWT, профиль | все три | все три |
| **Catalog** | товары, категории, баннеры | admin/1С → backend | Store, Сайт |
| **Order** | заказы, статусы | Store, Сайт | Store, Сайт, admin |
| **Loyalty** | баллы (единый баланс) | Квартал, Store, Сайт | все три |
| **Shoes** | кроссовки пользователя (трекер износа) | Store (покупка), Квартал (км) | Квартал, Store |
| **Notification** | пуш/лента (FCM) | backend | все три |

---

## 2. Сущности (общие модели)

> JSON-формы совпадают с DTO Sport Store (`toJson`/`fromJson`). Новые приложения используют их 1-в-1.

### 2.1 User (Auth)
```json
{
  "id": "u_123",
  "name": "Алексей Иванов",
  "email": "alex@mail.ru",
  "phone": "+79990000000",
  "provider": "email | google | apple",
  "avatarPath": "https://cdn.mata-club.ru/u/123.jpg",
  "addresses": [ /* SavedAddress[] */ ]
}
```
`SavedAddress`:
```json
{ "label": "Дом", "city": "Москва", "street": "ул. Ленина", "house": "12А", "apartment": "45", "postalCode": "101000" }
```

### 2.2 Category / Product (Catalog)
```json
// Category
{ "id": "shoes", "name": "Кроссовки", "emoji": "👟", "imageUrl": "https://cdn.mata-club.ru/cat/shoes.jpg" }
```
```json
// Product
{
  "id": "3",
  "name": "Кроссовки Air Runner X1",
  "brand": "МАТА",
  "categoryId": "shoes",
  "price": 12990,
  "oldPrice": 15990,
  "imageUrls": ["https://cdn.mata-club.ru/p/3_0.jpg", "..."],
  "description": "…",
  "sizes": ["41","42","43"],
  "colors": ["Чёрный/Серый"],
  "isNew": true,
  "isFeatured": true,
  "rating": 4.7,
  "reviewCount": 203,
  "inStock": true,
  "stockBySize": { "41": 0, "42": 7, "43": 3 }
}
```
> `stockBySize` — остаток по размерам из 1С. **Пустой объект = разбивки нет**
> (товар заведён руками или 1С прислала общий остаток); тогда витрина считает
> доступными все размеры. Размер с нулём — показываем, но купить нельзя.
>
> Расширения на будущее (из RECOMMENDATION ч.3): `subcategoryId`, `videoUrl`, `shortDescription`, `isBestseller`, `stockCount`, `materialComposition`, `careInstructions`, `weight`.

```json
// ModelCard — то, что видит покупатель (GET /models). D-94
{
  "key": "FRSM007",
  "name": "Шорты мужские BMAI",
  "brand": "BMAI", "article": "FRSM007", "categoryId": "clothes",
  "price": 3990, "oldPrice": null,
  "imageUrl": "https://cdn.mata-club.ru/p/frsm007.webp",
  "description": "…",
  "rating": 4.7, "reviewCount": 12,
  "thumbUrl": "https://cdn.mata-club.ru/p/frsm007-t.webp",
  "isNew": false, "isFeatured": false, "inStock": true,
  "variantCount": 6,
  "sizes": ["S","M","L"],
  "colors": [
    { "name": "ЧЁРНЫЙ", "imageUrl": "…", "thumbUrl": "…", "inStock": true,
      "photos": [ { "url": "…-1.webp", "thumb": "…-1-t.webp" } ],
      "sizes": [ { "size": "S", "productId": "p1", "price": 3990, "oldPrice": null, "inStock": true } ] }
  ]
}
```
> **Одна модель — одна карточка, но заказ уходит на позицию склада.** В 1С каждый
> размер и цвет — отдельная карточка (так печатают этикетки), покупателю это
> показывать нельзя. Клиент выбирает цвет и размер и кладёт в корзину
> `colors[].sizes[].productId` — именно его ждёт склад.
>
> **Фотографии — у цвета, до шести** (D-99): `colors[].photos` в порядке показа, первый
> снимок он же обложка. `thumb` (400 px) — для ленты каталога и кружков выбора цвета,
> `url` (webp 1600) — для галереи. Цвет без снимков отдаёт пустой список: чужие
> фотографии подставлять нельзя.
>
> Размер и цвет берутся ТОЛЬКО из полей 1С (D-95): строка пуста — выбора на
> витрине нет, заполнили — появился сам, без правок в коде.

### 2.3 Order (Order)
```json
{
  "id": "SS-61439",
  "userId": "u_123",
  "items": [
    { "productId": "2", "productName": "Худи Essential Fleece", "productBrand": "МАТА",
      "imageUrl": "…", "price": 5990, "size": "L", "color": "Тёмно-синий", "quantity": 1 }
  ],
  "subtotal": 5990,
  "deliveryCost": 300,
  "pointsRedeemed": 430,
  "total": 5860,
  "checkoutData": {
    "name": "Алексей Иванов", "phone": "+7…", "email": "alex@mail.ru",
    "deliveryType": "pickup | courier | cdek | russianPost",
    "city": "Москва", "street": "…", "house": "…", "apartment": "…", "postalCode": "…",
    "paymentType": "card | cash | sbp"
  },
  "status": "pending | processing | shipped | delivered | cancelled",
  "createdAt": "2026-06-05T13:09:00Z",

  // ↓ добавляет сервер в ответах /orders (аудит B08) — актуальное состояние
  "serverId": 5812,                 // глобальный номер заказа на сервере
  "serverStatus": "pending | paid | shipped | delivered | cancelled",
  "paymentStatus": "pending | paid | canceled | refunded | partially_refunded | none",
  "onecStatus": "'' | accepted | assembled | shipped | delivered | canceled",
  "onecStatusAt": "2026-06-06T10:00:00+00:00",   // null, пока статусов из 1С не было
  "onecNumber": "УТ-000123",        // номер документа в 1С, '' если нет
  "courierNote": "Иван, +7…, к 18:00" // кто везёт и когда, '' если нет
}
```
> **Актуальное состояние (B08).** Сервер хранит присланный при оформлении payload и
> отдаёт его поля как есть, но `status` берёт из своего состояния (оплата, отмена,
> статусы 1С). Серверный `paid` в `status` отдаётся как `processing` — это словарь
> приложения; сырой серверный статус — в `serverStatus`. Клиент должен считать
> серверные поля главнее локальной копии заказа.
> В Sport Store уже есть всё, кроме `userId` и `pointsRedeemed` — добавить при подключении backend (см. §6 Пробелы).

### 2.4 Loyalty (Loyalty) — ЯДРО ЭКОСИСТЕМЫ
```json
// LoyaltyAccount
{ "userId": "u_123", "balance": 430, "level": "basic | silver | gold | platinum" }
```
```json
// LoyaltyTransaction (общая для Квартала и Store)
{
  "id": "tx_1",
  "userId": "u_123",
  "amount": 120,            // + начисление, − списание
  "source": "runnerRun | runnerTerritory | runnerCompetition | purchase | review | registration | birthday | referral | redeem",
  "description": "Пробежка 12.0 км",
  "orderId": "SS-61439",    // null если не покупка
  "runId": "run_88",        // null если не Runner App
  "createdAt": "2026-06-05T08:00:00Z"
}
```
**Правила (RECOMMENDATION ч.11.5):** 1 балл = 1 ₽; списание макс 30% заказа; мин остаток для списания 50; срок 12 мес.
**Уровни:** basic 0–199 (1%) · silver 200–499 (2%) · gold 500–999 (3%) · platinum 1000+ (5%).
**Начисление:** бег 1 км = 10 · захват территории = 50 · победа = 200 · покупка = 1/10 ₽ · первый заказ +50 · отзыв с фото +10 · регистрация +20.

### 2.5 ShoeAsset (Shoes) — связка Store ↔ Квартал
> Реализует идею «трекер износа кроссовок» из `docs/IDEAS.md`. Купил в Store → зарегистрировались в Квартале.
```json
{
  "id": "shoe_1",
  "userId": "u_123",
  "productId": "3",
  "orderId": "SS-61439",
  "model": "Air Runner X1",
  "imageUrl": "…",
  "purchasedAt": "2026-06-05T13:09:00Z",
  "totalKm": 0,
  "maxKm": 600,
  "retired": false
}
```

### 2.6 Notification (Notification)
```json
{ "id": "n_1", "userId": "u_123", "title": "Заказ №SS-61439 доставлен",
  "body": "…", "type": "order | promo | system", "orderId": "SS-61439",
  "read": false, "createdAt": "2026-06-05T14:00:00Z" }
```

### 2.7 LegalDocument / UserConsent (Legal) — единые документы и аудит согласий
Версионируемые документы (тип+версия) и факт согласия пользователя — для launch-gate
(`docs/LAUNCH_READINESS.md` §3/§13). Текст документов заполняет юрист.
```json
// LegalDocument
{ "id": "1", "type": "terms | privacy | pd_consent | marketing | offer | loyalty | club",
  "version": "1.0", "title": "Пользовательское соглашение", "body": "…",
  "required": true, "publishedAt": "2026-06-21T00:00:00Z", "accepted": false }
// UserConsent (в /legal/consents)
{ "id": "10", "type": "terms", "version": "1.0", "acceptedAt": "…",
  "source": "kvartal", "revokedAt": null, "active": true }
```

---

## 3. Эндпоинты

> Базовый URL: `ApiConfig.baseUrl` (пример: `https://api.mata-club.ru/v1`). Реализованы в Sport Store как `Api*Repository`.

### Auth
```
POST /auth/register            { name, email, password } → { token, user }
POST /auth/login               { email, password }       → { token, user }
                                                           ({ phone, password } — основной путь). 429 { detail, retryAfter }
                                                           + Retry-After — 8 неудач за 15 мин на один телефон/почту с любых
                                                           адресов (аудит D03); удачный вход обнуляет счётчик
POST /auth/phone/request       { phone }                 → { ok, smsEnabled, channel }   (шлёт код; dev — всегда 1234)
                                                           429 { detail, retryAfter } + Retry-After — лимит (D-76):
                                                           90 с между кодами на номер, 3 кода на номер в сутки,
                                                           с адреса 30 в час и 100 в сутки; клиент показывает detail
POST /auth/phone/channel       { phone }                 → { type, status, codeType, attemptsLeft }   (канал текущей сессии; 404 — сессии нет)
                                                           клиент опрашивает раз в 3 с, пока ждёт код (лимит otp_poll 300/мин);
                                                           codeType=codeless → поля кода нет: ждём status=confirmed и шлём
                                                           verify/register/password-reset с ПУСТЫМ code (D-78)
POST /auth/phone/verify        { phone, code, referralCode? } → { token, user, signupBonus?, referral? }
                                                           (создаёт аккаунт при первом входе)
                                                           Программа лояльности v1 (этап 2), новые поля:
                                                           signupBonus — бонус за регистрацию (75), только
                                                           новому аккаунту и один раз на телефон (переживает
                                                           удаление аккаунта); referralCode (опц.) — код
                                                           пригласившего; referral { ok, detail } — результат
                                                           (плохой код регистрацию НЕ ломает). То же для
                                                           POST /auth/register { phone, code, …, referralCode? }.
POST /auth/password/forgot     { email }                 → 200
POST /auth/password/reset      { password }              → 200
PUT  /auth/password            { old, new }              → 200
GET  /auth/me                                            → user   (incl. privacy)
```

### Account (приватность и удаление, LAUNCH_READINESS §2/§13)
```
GET   /account/privacy                                   → { profilePublic, routePublic, realtimePublic }
PATCH /account/privacy   { routePublic, ... }            → privacy   (по умолчанию всё закрыто)
GET   /account/export                                    → JSON-файл со ВСЕМИ ПДн юзера (портируемость, §2)
POST  /account/delete    { confirm: true }               → { ok, deleted{...} }  (необратимо, Bearer)
```

### Catalog
```
GET /categories                         → Category[]
GET /products                           → Product[]
GET /products?category=:id              → Product[]
GET /products?featured=true             → Product[]
GET /products?new=true                  → Product[]
GET /products/:id                       → Product
GET /products/search?q=:q               → Product[]   (позициями; витрина ищет через /models?q=)
GET /models                             → ModelCard[] ← ВИТРИНА: один товар = одна карточка (D-94)
GET /models?category=:id|featured|new   → ModelCard[]
GET /models?q=:q                        → ModelCard[] (поиск карточками, а не позициями)
GET /models/:key                        → ModelCard   (:key — ключ модели; id позиции тоже принимается)
GET /products/:id/reviews               → отзывы МОДЕЛИ (:id — ключ модели или позиция)
GET /brands                             → string[]
GET /sizes                              → string[]
GET /products/price-range               → { min, max }
GET /banners                            → Banner[]
```

**Витрина `/models`: размер ответа и страницы (аудит F01).** Замер прода 27.09.2026:
208 карточек (780 складских позиций), ~190 КБ JSON одним ответом (gzip — ~15 КБ).
- Без параметров — **весь список массивом, как раньше** (выпущенные сборки Store и сайт
  читают его целиком; ломать нельзя).
- `?limit=N&offset=M` (или `page=K` с 1) — страница карточек, тот же массив `ModelCard[]`.
  Режется по моделям (размеры одной модели не делятся). `limit` ≤ 100; неверные
  значения → 400 `{error: "bad_paging"}`. Сочетается с `category`/`q`/`new`/`featured`/`platform`.
- Заголовки: `X-Total-Count` — всего моделей с учётом фильтров (всегда), `X-Offset`/`X-Limit` —
  при странице; открыты для сайта через CORS (`Access-Control-Expose-Headers`).
- `ETag` + `If-None-Match` → 304 без тела; gzip при `Accept-Encoding: gzip`.
- Бюджет: **2 запроса к БД** (позиции + фото страницы) при любом размере каталога —
  закреплено тестом `catalog/tests_models_paging.py`.
- Следующий шаг (клиенты пока не переведены): лента Store и сайт — подгрузка по `limit=24`
  с `offset` при прокрутке, поиск — первая страница; `X-Total-Count` для «ещё N».

### Обмен с 1С (D-62) — приём номенклатуры

1С шлёт данные сама, мы у неё ничего не запрашиваем. Авторизация — постоянный
`Authorization: Bearer <токен>` (без 2FA: у робота нет телефона). Пустой токен в
настройках = приём выключен, любой запрос получает 401.

```
POST /integrations/1c/categories  { categories: [...] }  → { received, created, updated, errors }
POST /integrations/1c/catalog     { products: [...] }    → { received, created, updated, skipped, keptByOwner, unknownCategories, errors }
POST /integrations/1c/prices      { prices: [...] }      → { received, updated, keptByOwner, errors }
GET  /integrations/1c/status                             → { status, service, enabled, time }
```
Вместо объекта принимается и голый массив, и `{"items": [...]}`, и `{"data": [...]}`.

**Порядок важен: категории → каталог → цены.** Товар с незаведённой категорией
сохранится, но не попадёт ни в один раздел витрины — такие категории возвращаются
в `unknownCategories` и попадают в журнал обмена как замечание.

Элемент категории: `{ id, name, parentId?, sort? }`. 1С ведёт название, порядок и
родителя; эмодзи и фото категории — наши, импорт их не трогает. Пропавшие из
выгрузки категории НЕ удаляем: на них ссылаются товары.

Элемент товара: `{ id, article, name, categoryId, brand?, active?, updatedAt?,
price?, oldPrice?, description?, sizes?, colors?, images? }`.

Элемент цены: `{ id | article, price, oldPrice?, stock? }` либо
`{ ..., variants: [{ variantId, size, stock }] }` — тогда остаток раскладывается
по размерам (`stockBySize`), а общий остаток считается суммой. Общий `stock` без
вариантов очищает разбивку: она уже неправда.

**Право вето владельца.** Поля `price`, `oldPrice`, `description`, `sizes`,
`colors`, `images` владелец может вести сам в Конструкторе — тогда импорт их не
перезаписывает и возвращает в `keptByOwner`. Остаток переопределять нельзя.

**Размер выгрузки.** За один запрос принимаем до 20 000 позиций; больше — 413 с
просьбой прислать частями. Внутри всё пишется пачками, число обращений к базе не
зависит от числа позиций.

### Обмен с 1С — заказы МАТА → 1С (обратный поток)

Направление то же: **1С забирает сама**, её сервер обычно за NAT и достучаться до
него мы не можем.

```
GET  /integrations/1c/orders[?limit=200]              → { orders: [...] }
POST /integrations/1c/orders/ack     { serverIds?: [], orderIds?: [] }
                                     → { acked, unknown[], ambiguous[], unknownServerIds[] }
POST /integrations/1c/orders/status  { orders: [...] }→ { received, updated, errors, ambiguous[] }
```

**Идентификатор заказа (аудит B06).** `orderId` (`SS-xxxxx`) придумывает клиент, он
уникален только вместе с пользователем. Глобальный номер — `serverId` (id заказа на
сервере): он есть в каждом заказе выдачи, по нему 1С подтверждает (`serverIds`) и
присылает статусы (`serverId`). Старый контракт по `orderId` работает, пока номер
однозначен; если под номером несколько заказов, из них берётся тот, что вообще мог
попасть в 1С (оплачен ЮKassa или уже забран). Не удалось однозначно — не трогаем ни
один заказ: номер в `ambiguous` (+ в `errors` у статусов), строка журнала обмена —
«частично», текст «номер неоднозначен — пришлите serverId». Прислали и `serverId`, и
`orderId`, но они от разных заказов — статус не применяется, ошибка в `errors`.

**Заказ остаётся в очереди, пока 1С не подтвердит приём** через `ack`. Оборванная
связь не должна стоить покупателю заказа, поэтому выдача и подтверждение — разные
запросы. Повторный `ack` не ошибка (`acked: 0`).

**В очередь попадают только заказы, готовые к сборке:** оплата подтверждена ЮKassa
(`paid` и есть номер платежа, D-72). Заказ, ждущий оплаты, и «оплаченный» без
настоящего платежа в 1С не уходят — иначе там копятся брошенные корзины.

Заказ отдаётся в виде: `{ orderId, serverId, createdAt, customer{phone,name,email}, items[],
total, deliveryCost, pointsRedeemed, payment, paymentStatus, delivery, address,
postalCode, test }`. Позиция: `{ id, article, productId, name, size, color, qty, price }` —
`id` и `article` подставляются из карточки товара, чтобы склад не сопоставлял позиции
по названию.

**Статусы обратно:** `{ serverId?, orderId?, status, number? }` (нужен хотя бы один из номеров), где `status` — `accepted`,
`assembled`, `shipped`, `delivered`, `canceled`. `shipped`/`delivered`/`canceled`
двигают общий статус заказа; `accepted` и `assembled` — этапы склада: их видно
покупателю отдельной строкой, но общий статус не меняют. Один и тот же статус
повторно ничего не меняет и не шлёт уведомление второй раз. Пришедший статус
снимает заказ с очереди, даже если `ack` потерялся.

### Order
```
POST /orders     { items, checkoutData, pointsRedeemed, total } → Order   (заказ «ждёт оплату»; баллы списывает сервер: от 50, ≤30% заказа с доставкой, ≤ баланса; 400 — нарушены лимиты, сумма ниже каталога или при включённой оплате заказ не сверить с каталогом; + ShoeAsset для обуви)
GET  /orders                                             → Order[] (текущего пользователя)
GET  /orders/:id                                         → Order
POST /orders/:id/pay  { returnUrl? }  → { status, paymentId, confirmationUrl, method: "sbp" }  (только СБП, D-72; 409 — время на оплату истекло; 502 — оплата недоступна; dev без провайдера — status=paid без paymentId, на сборку не уходит)
POST /devices/register { token, platform }               → { ok }   (токен устройства для пушей, D-25)
```

### Loyalty (единый баланс)
```
GET  /loyalty/account                   → { balance, level, code, transactions: LoyaltyTransaction[],
                                            total?, pending?, pendingNextAt?, pendingNextAmount?, frozen? }
     balance            ТРАТИМЫЕ баллы (решение владельца 28.09.2026). Выпущенные сборки Store
                        показывают/списывают его — больше доступного не спишут.
     total              всё на счету (тратимые + pending); по нему считается level
     pending            баллы за активность, которые пока нельзя тратить: созревают 3 дня
                        или заморожены (аккаунт на проверке)
     pendingNextAt      ISO-время ближайшего созревания (null — нечему созревать или frozen)
     pendingNextAmount  сколько созреет в тот же день, что pendingNextAt
     frozen             true — аккаунт на проверке (needs_review): баллы за активность
                        не тратятся до решения модератора
     transactions[].availableAt  с какого момента проводка тратится (null — сразу)
     Созревают (3 дня): runnerRun, runnerTerritory, runnerMilestone, runnerDivision,
     runnerSeason. Покупки, бонусы, возвраты — сразу. Начисленное до 28.09.2026 — созревшее.
     Та же разбивка — GET /me/stats → loyalty { balance (тратимые), pending, earned, spent }.
POST /loyalty/transactions  LoyaltyTransaction → 200   (только redeem/прочее; начисления — серверные)
                            source ∈ {runnerRun, runnerTerritory, purchase, registration} → 403
                            (анти-чит S-04 D-23: начисление считает сервер —
                             бег→/runs, территория→/territories/capture, покупка/рег→/orders)
POST /loyalty/redeem  { amount, orderId, description? }   (прежний адрес Store; баллы списывает
                            сам POST /orders по pointsRedeemed — D-72)
                            → { ok, deduped, balance, spent }  списание по заказу уже есть (обычный путь)
                            → { ok, balance, spent, level }    списал: тот же сервис и правила, что /orders
                               (заказ существует и не отменён, amount == его pointsRedeemed, ≥50, ≤30%)
                            → 400/404 { detail, balance }       нет orderId / заказа / нарушены правила
                               (balance — тратимые; «Сейчас доступно N баллов…» — остальные созревают)
```

#### Программа лояльности v1 (ТЗ 30.09.2026) — **при включённой программе v1**
Выключатель — настройка `LOYALTY_V1_ENABLED` (админка «Настройки лояльности»), по умолчанию
ВЫКЛ: пока выключена, всё выше работает как раньше. Включена — одна валюта «бонус» (1 = 1 ₽),
баланс = лоты с датами сгорания, 4 уровня. Прежние поля и адреса НЕ меняются, добавлены новые:
```
GET  /loyalty/account   + programV1: bool   (false — старые правила; поле есть всегда)
                        при programV1 = true:
     balance   = можно списать сейчас (доступно − замороженная активность, ≥ 0)
     total     = доступно + ожидает (удержание), pending = ожидает
     level     = уровень v1: basic | silver | gold | platinum (по статусным, не по балансу)
     v1: { available (может быть < 0 — долг после возврата товара), redeemable, held,
           statusPoints, purchases365, level, levelIndex 0..3, levelUntil,
           nextLevelThreshold (null у Платины), platinumMinSpend, redeemMin, redeemCeiling,
           heldNextAt, heldNextAmount, expiringAt, expiringAmount,
           lots: [{ id, amount, remaining, state: held|available, source, accruedAt,
                    availableAt (для held; null — ждёт получения заказа), expiresAt }] }
     transactions — прежний реестр: история до v1 и ИГРОВОЙ счёт бега/захвата (км×10 —
           рейтинги, клубы, челленджи). При v1 он в баланс не входит: деньги за активность —
           лоты run / capture / stage (этап 2, ниже).
GET  /loyalty/referral  → { programV1, code, bonus, capMonth, invitedBy, canBind, bindUntil,
                            invited, rewarded }      (code — мой постоянный код приглашения)
POST /loyalty/referral  { code } → 200 { ok: true, detail, …как GET } | 400 { ok: false, detail, … }
                        ввести код пригласившего (для сборок без поля в регистрации): только в
                        первые 7 дней после регистрации, связь одна и навсегда; самоприглашение
                        (тот же телефон или то же устройство) отклоняется.
                        Бонус пригласившему (BONUS_REFERRAL = 100, не больше CAP_REFERRALS_MONTH = 3
                        в месяц) — когда первый заказ приглашённого вышел из удержания без возврата.
POST /loyalty/redeem-preview  { items: [{ productId, quantity }], deliveryCost? }
                        → программа выключена: { programV1: false, available, redeemMin: 50, maxPercent: 30 }
                        → включена: { programV1: true, level, available, eligibleTotal, ceiling,
                                      redeemMax, redeemMin, canRedeem, reason,
                                      lines: [{ index, productId, eligible, reason }] }
                          redeemMax = min(доступно, floor(eligibleTotal × ceiling)); ceiling по уровню
                          0,15/0,20/0,25/0,30 и никогда не выше 0,30. eligibleTotal — цены витрины без
                          исключённых групп 1С (с подгруппами; сертификаты там же), уценки
                          (oldPrice > price), товаров не из каталога; доставка не участвует.
                          reason позиции: excluded_category | markdown | not_in_catalog.
                          canRedeem = redeemMax ≥ redeemMin (300); иначе reason — текст для кнопки.
POST /orders  pointsRedeemed — при v1: от redeemMin и ≤ redeemMax, иначе 400 { detail } с текстом.
              Бонусы блокируются при создании заказа (FIFO по дате сгорания), списываются при
              оплате, возвращаются в свои лоты при отмене/истечении 15-минутного окна оплаты.
              За оплату — лот floor((сумма − бонусы − доставка) × ставка уровня) в удержании
              до max(оплата + 14 дней, получение + 7 дней); не получен — держится.
              Бонус за первый заказ при v1 не начисляется.
Возврат товара (админка): списанные бонусы — в исходные лоты по доле позиции в eligibleTotal;
              начисленные за покупку: в удержании — отменяются, уже доступные — списываются
              (при нехватке баланс уходит в минус и гасится следующими начислениями).
```

#### Программа v1, этап 2 — бонусы за активность (ТЗ §3) — **при включённой программе v1**
Пробежка 10, захват квартала 30, победа в этапе 50 — лот `available` сразу, в статусные входит.
Лимиты — календарный месяц по Якутску (UTC+9): пробежек 12, захватов 3, этапов 1 и общий
260/325/390/520 по уровню (упёрлись в общий посреди бонуса — начисляется остаток). Суточный
потолок 1000 и созревание 3 дня (D-107) при v1 НЕ действуют; заморозка бонусов за активность,
пока аккаунт на проверке, — действует. При лимите событие засчитано в игре, бонуса нет.
Условия бонуса за пробежку: ≥ 3 км и средний темп 3:00–12:00 мин/км — по серверному пересчёту
трека, если он есть (`POST /runs/track`), иначе по итогам `POST /runs` (`validatedBy: summary`);
загружена ≤ 48 ч после финиша; одна пробежка с бонусом в календарный день; одна тренировка
двумя путями (свой забег + импорт, пересечение по времени > 50 %) — один раз. Признаки обмана —
темп быстрее 3:00, отрезок > 200 м быстрее 2:30 (по треку), трек противоречит итогам, трек
совпадает > 80 % с треком другого аккаунта с того же устройства (оба) — без бонуса и в очередь
ручной проверки (админка «Проверка забегов» → «Бонусы на проверке»). Трек пришёл после итогов —
пересчёт по нему; признак обмана → бонус отзывается (событие `cancel`), пробежка на проверку.
Захват — только за валидную пробежку (привязка захват → пробежка, см. Territories); пробежка на
проверке — бонус захвата ждёт решения. Этап — 1-е место в месячном итоге своего дивизиона
(уровень дивизиона в этом месяце, км засчитанных забегов), выдаётся ежедневной задачей в
первый день следующего месяца, один раз.
Поле `bonus` в ответах `/runs`, `/territories/capture` (новое):
```
bonus: { amount, status: granted|capped|day_limit|duplicate|ineligible|suspicious|flagged|waiting|rejected,
         reason, validatedBy: track|summary|null, monthCapReached, message,
         month: "2026-10", runsLeft, capturesLeft, stagesLeft, activityLeft, activityCap,
         resetsAt (1-е число следующего месяца, 00:00 Якутск) }
message — текст для экрана после пробежки: «+10 бонусов» / «Лимит месяца исчерпан, обновится
1 числа» / «Бонус за пробежку — один раз в день» / «Пробежка на проверке — бонус придёт после неё».
```

### Runs (история пробежек + серверный расчёт очков — анти-чит S-04)
```
GET  /runs                              → Run[]   (сводки забегов пользователя, новые сверху)
POST /runs  { id, distanceMeters, elapsedSeconds, finishedAtMs, capturedTerritory, capturedZones, mockDetected? }
                                        → { ok, duplicate, flagged, flagReason, pointsAwarded, run,
                                            dailyCapReached?, pointsCapped?, capReason?,
                                            bonus?, monthCapReached? }
            Программа лояльности v1 включена: pointsAwarded = начисленный БОНУС за пробежку
            (то, что попало в кошелёк; «+N» на экране финиша выпущенных сборок), bonus — см.
            «Программа v1, этап 2»; при исчерпанном лимите monthCapReached: true и capReason =
            «Лимит месяца исчерпан, обновится 1 числа». Суточного потолка (dailyCap*) при v1 нет.
            dailyCapReached/pointsCapped/capReason (новые, 28.09.2026) — суточный потолок баллов:
            не больше 1000 в сутки (UTC) на свои забеги + импорт с часов + захваты вместе.
            Сверх — забег засчитан (не 400, не flagged), pointsAwarded урезан, pointsCapped — сколько
            срезано, capReason — текст для человека. Дубль отдаёт те же поля.
            mockDetected: bool (опц.) — клиент сообщает о подделке геолокации (Android mock-GPS)
            → сервер флагает забег (0 очков); накопление флагов помечает аккаунт «на ревью» (S-04).
```
Сырой GPS-маршрут НЕ передаём/не храним (приватность §2). Сервер сам валидирует забег
(скорость ≤ 40 км/ч, дистанция/время, суточный лимит) и НАЧИСЛЯЕТ очки за бег
(`runnerRun` = км×10), идемпотентно по `id`. Неправдоподобный забег → `flagged`, 0 очков.
Клиент очки за бег больше НЕ присылает.
Забег и начисление пишутся одной транзакцией; повтор того же `id` доводит начисление,
если оно когда-то не дошло (ровно один раз). `id` чужого забега/трека → 409.
Некорректные числа (не число, NaN/∞, отрицательные, время вне 1970…2100) → 400,
ничего не сохраняется.
Проверка суточных лимитов и запись идут под блокировкой на пользователя (общей с
импортом тренировок): параллельные забеги не обходят потолок (аудит C06).

### Territories · захват (анти-чит — docs/ANTICHEAT_TRUST.md)
```
POST /territories/capture { points: [[lat,lng],...], captureId, distanceMeters?, elapsedSeconds?, runId? }
     → { ok, areaM2, points, blocksGained, blocksTotal, geojson, holdHoursLeft, unverified?,
         pointsPending?, pendingReason?, dailyCapReached?, pointsCapped?, capReason?,
         bonus?, monthCapReached? }
     программа лояльности v1: points = начисленный бонус за захват (30, лимиты месяца), bonus —
     см. «Программа v1, этап 2»; бонус и тогда, когда новой площади нет, но кварталы перешли
     (blocksGained > 0, скорость проверена).
     дубль captureId → { ok, duplicate: true, areaM2, geojson }
```
Скорость = max(distanceMeters, длина маршрута по points) / elapsedSeconds; > 40 км/ч → 400.
Без `elapsedSeconds` (нет / не число / ≤ 0) скорость не проверить: зона засчитывается,
но `points` = 0 и `unverified: true` (аудит C06; mata_kvartal шлёт оба поля).
Суточный потолок — 20 захватов за 24 ч (начисленные + ждущие пробежку; 429), под блокировкой
на пользователя.
**Баллы только за засчитанную пробежку** (решение владельца 28.09.2026, `territories/awards.py`):
зона на карте засчитывается сразу, баллы — если есть принятая (не помеченная) пробежка этого
захвата. `runId` (новые сборки Квартала) — id сводки `POST /runs` той же пробежки; без него
(старые сборки) пробежка ищется по цифрам: время ±max(60 с, 5 %), дистанция ±max(100 м, 5 %),
контур не длиннее пробежки, пробежка завершилась в окне [получение захвата − 7 сут; + 12 ч].
Одна пробежка — один оплаченный захват. Пробежки ещё нет (захват пришёл раньше сводки —
гонка на финише, офлайн-очередь) → `points` = 0, `pointsPending` = N, `pendingReason`; баллы
начисляются ровно один раз, когда придёт сводка. Пробежка помечена → ждёт модератора
(одобрил — баллы приходят, признал нарушением — не приходят/отзываются).
Баллы за захват входят в общий суточный потолок 1000 (см. `/runs`).

### League (зачёты лиги и профиль бегуна — docs/LEAGUE_PLAN.md)
```
GET  /league/boards?board=<absolute|consistency|mylane|personal|club>&period=<week|month|q90>
                                        → { board, period, unit, top[], me{...}, group? }
     absolute     сумма километров за период — для быстрых и выносливых
     consistency  число пробежек за период — скорость не решает, решает регулярность
     mylane       «своя лига»: только ровесники своего пола (нужен профиль,
                  иначе { needsProfile: true } и пустая таблица)
     personal     я против себя же в прошлом периоде: { value, prevValue, delta, improved }
     club         сумма километров участников клуба (top[] по клубам)

     me: { place, of, value, aheadOf, behindNext? }
         aheadOf — сколько человек позади. Показываем всегда: «ты обошёл 47 из 63»
         держит в игре тех, кто никогда не будет первым.

GET  /runner/profile                    → { birthYear, gender, level, weeklyGoalKm, group }
POST /runner/profile  { birthYear?, gender?, level?, weeklyGoalKm? }  → тот же объект
     Все поля необязательные; пришло null или "" — поле стирается.
     gender: m|f|"" · level: novice|amateur|advanced|""
     group  — группа сравнения { age, gender, label }, считается на лету из года
              рождения (в базе устарела бы в ближайший день рождения); null, если
              год или пол не заданы.
```
Зачёты считаются по `runs` (сводки забегов), помеченные античитом не участвуют.
Возраст спрашиваем необязательно: без профиля человек видит все зачёты, кроме «своей лиги».

### Trails (тропы — docs/LEAGUE_PLAN.md §6, решение D-60)
```
POST /runs/track  { runId, points: [[lat, lon, ms], ...] }
                                        → { attempts: [ {trailId, trailName, durationS, ...} ] }
     Телефон шлёт прорежённый трек (≈точка в 5 с). Сервер сверяет его с тропами
     района, пишет попытки и УДАЛЯЕТ трек через 30 дней (D-60; было 14, решение 28.09.2026). Выключен тумблер
     «участвовать в тропах» → { attempts: [], skipped: "trailsDisabled" }, трек
     не сохраняется вовсе.
     Трек может прийти раньше сводки POST /runs. Если runId уже занят забегом,
     треком или попыткой тропы ДРУГОГО пользователя → 409 «Конфликт id» (владелец
     трека не меняется); повтор своего — идемпотентен. Точки с мусором (не число,
     NaN/∞, вне диапазона, время вне 1970…2100) отбрасываются; меньше двух — 400.

GET  /trails?lat=&lon=                  → { items: [ {id, name, lengthM, points,
                                            createdByMe, attemptedByMe} ] }
POST /trails  { name, points: [[lat, lon], ...], city? }   → тропа
     Линия прореживается, длина 200 м … 42 195 м.

GET  /trails/:id/boards?board=<fastest|mine|frequent|mylane>
     fastest   лучшее время каждого
     mine      мои попытки по времени + лучшая
     frequent  кто прошёл чаще за 90 дней — «местная легенда» по-нашему
     mylane    только ровесники своего пола (нужен профиль бегуна)
     → { trail, board, unit, me: {place, of, value, aheadOf}, top[], group? }
```
Одна и та же пробежка не даёт две попытки на одной тропе. Невозможная скорость,
бег в обратную сторону и срезанные углы не засчитываются.

### Integrations (подключение часов)
```
GET  /integrations/coros/callback   → куда COROS возвращает человека после разрешения доступа
POST /integrations/coros/push       → сюда COROS присылает завершённые тренировки
GET  /integrations/coros/status     → проверка «сервис жив», её COROS опрашивает сам
```
Адреса нужны в заявке к COROS ДО выдачи ключей, поэтому существуют заранее.
Разбор данных появится вместе с Client ID и Secret: пока проверить подпись
запроса нечем, а принимать неподписанные данные о чужих тренировках нельзя.

### Workouts (тренировки извне: часы, Health Connect, файлы)
```
POST /workouts/import  { source, items[] }  → { imported, duplicates, skipped, points, items[],
                                                dailyCapReached?, pointsCapped?, capReason? }
                       программа лояльности v1: points = начисленные бонусы за эти тренировки;
                       items[].bonus { amount, status, reason } — решение по бонусу (дубль своего
                       забега, одна в день, лимиты месяца — см. «Программа v1, этап 2»)
                       (суточный потолок баллов общий со своими забегами и захватами — 1000/сутки;
                        сверх — тренировка сохраняется, items[].pointsAwarded урезан; 28.09.2026)
GET  /workouts[?source=]                    → { items[] }
DELETE /workouts/source/:source             → { removed }   (человек отключил источник)
```
Отключение стирает данные тренировок, но не реестр учтённых (`workout_awards`:
хэш ключа + баллы): переподключение возвращает тренировки в список без повторного
начисления. Элемент с нечисловыми/бесконечными/гигантскими числами пропускается
(`skipped`), остальные принимаются.
`source`: `healthconnect` | `applehealth` | `file` | `garmin` | `suunto` | `coros`.
Элемент: `{ sourceId, startedAtMs, durationS, distanceM, sport?, avgHr?, maxHr?, calories? }`.

Три правила, на которых всё держится:
- повторная присылка той же тренировки (`source` + `sourceId`) не создаёт вторую
  и не начисляет очки заново — источники присылают одно и то же по многу раз;
- тренировка с часов и наш собственный забег в те же минуты — ОДНО событие
  (пересечение по времени ±20 мин и близкая дистанция): очки платим один раз,
  в ответе такая тренировка помечена `duplicateOfRun: true`;
- импорт проходит тот же античит, что и свой забег, а суточный лимит считается
  по своим забегам и импорту ВМЕСТЕ — иначе второй источник обходил бы лимит.

Очки начисляем только за беговые виды (`run`, `trail_running`, `walking`, …);
велосипед и плавание импортируем и показываем, но в баллы не превращаем.
Отключение источника стирает его данные; начисленные баллы остаются — они заработаны.

### Shoes (трекер износа)
```
GET  /shoes                             → ShoeAsset[]            (Квартал показывает ресурс)
POST /shoes/:id/distance  { km }        → ShoeAsset              (Квартал добавляет км после пробежки)
```

### Notification
```
GET  /notifications                     → Notification[]
POST /notifications/read  { ids: [] }   → 200
POST /devices  { fcmToken, platform }   → 200                    (регистрация устройства для пуша)
```

### Legal / Consents (единые документы и согласия)
```
GET  /legal/documents                   → LegalDocument[]   (текущие опубликованные; accepted — если Bearer)
POST /legal/consent     { accept:[type], source } | { type, source } → { recorded }   (Bearer)
GET  /legal/consents                    → UserConsent[]     (аудит согласий пользователя, Bearer)
POST /legal/consent/revoke  { type }    → { revoked }       (отзыв необязательного согласия, Bearer)
```

---

## 4. Потоки обмена между приложениями

### 4.1 Единый аккаунт (SSO)
```
Регистрация в любом приложении → POST /auth/register → { token, user }
JWT сохраняется → работает в Квартале, Store и на Сайте. Профиль/баллы/заказы общие.
```

### 4.2 Баллы: Квартал → Store
```
Пробежал 12 км в Квартале → POST /runs {id, distanceMeters:12000, elapsedSeconds, ...}
              ↓ сервер валидирует забег и САМ начисляет runnerRun = км×10 = 120 (анти-чит S-04)
              ↓ единый баланс на backend
Открыл Store → GET /loyalty/account → видит 430 баллов
В корзине применяет → POST /orders {pointsRedeemed:430, ...} — сервер сам списывает (≥50, ≤30%)
```

### 4.3 Покупка → кроссовки (Store → Квартал)
```
Купил кроссовки в Store → POST /orders → backend создаёт ShoeAsset {productId, userId, maxKm}
              ↓
Квартал → GET /shoes → показывает "Осталось ~230/600 км"
Каждая пробежка → POST /shoes/:id/distance {km} → ресурс убывает
Ресурс на исходе → пуш + рекомендация новой модели из Store (POST /notifications backend)
```

### 4.4 Статус заказа → пуш во все приложения
```
Backend меняет статус заказа → создаёт Notification → FCM-пуш
Все три приложения: GET /notifications → единая лента
```

---

## 5. Реализация в Sport Store (уже есть)

| Слой | Файлы |
|---|---|
| DTO | `lib/models/{product,category,order,auth_user,loyalty,app_notification}.dart` (`toJson`/`fromJson`) |
| Контракты | `lib/data/repositories/{product,auth,order,loyalty}_repository.dart` (abstract + Mock + **Api**) |
| Переключатель | `lib/data/api/api_config.dart` (`useMock`), `api_client.dart` (JWT, timeout) |

Переход на backend: поднять API по этому контракту → `ApiConfig.baseUrl` + `useMock = false`. Экраны не меняются.

---

## 6. Пробелы / TODO для полной согласованности

- [ ] Добавить `userId` в Order и Loyalty при подключении backend (сейчас локально не нужен).
- [ ] Добавить `pointsRedeemed` в модель `Order` Sport Store (сейчас списание считается отдельно в Loyalty).
- [x] Сервис **Shoes** + модель `ShoeAsset` — **backend готов**: авто-создание при заказе обуви (`POST /orders` → `store_shoes`), `GET /shoes`, `POST /shoes/:id/distance`. Осталось: UI трекера в Квартале (GET /shoes) и начисление км после пробежки.
- [ ] `runId` в LoyaltyTransaction (для Runner-источников).
- [ ] Расширить `Product` полями из RECOMMENDATION ч.3 (видео, остатки по вариантам, состав).
- [ ] Эндпоинт `/auth/me` + хранение `userId` для всех сущностей.

## Квартал 2.0 — дивизионы, сезоны, вехи, война (добавлено 2026-08-31)

Новые эндпоинты аддитивны — старые контракты не менялись.

- `GET /v1/league/division` — дивизион недели (группа ≤30 бегунов одного
  уровня; уровень = пожизненные км). Ответ: `division{id,tier,tierLabel,roman,
  name,size,resetAtMs}`, `me{place,of,km,movement}`, `members[{userId,name,club,
  km,runs,place,movement,isMe}]`, `zones{up,down}`. Назначение и закрытие
  прошлой недели — ленивые; топ-3 недели получают 50/30/20 баллов
  (`source=runnerDivision`, дедуп `run_id="div:<division>:<uid>"`).
- `GET /v1/league/season/latest` — итог прошлого месяца: `month`, `me{place,of,
  km,runs}|null`, `top[3]`, `currentMonth`. Закрытие ленивое одноразовое
  (SeasonClose); топ-3 сезона: 100/60/30 (`source=runnerSeason`).
- `GET /v1/me/stats` — добавлены `milestone{atKm,leftKm,reward}|null` и
  `streak{weeks,thisWeekDone,frozenWeeks[]}` (недельный стрик, авто-заморозка
  1 пустая неделя/календарный месяц).
- Вехи пожизненных км: сервер начисляет +50 при пересечении (25…20000 км),
  `source=runnerMilestone`, дедуп `run_id="ms:<км>"`.
- `GET /v1/me/digest` — итоги недели: `weekKm`, `weekRuns`, `earnedPoints`,
  `territories{count,areaM2,expiringSoon[{areaM2,hoursLeft}]}`.
- `GET /v1/clubs/war` — «война района»: `standings[{clubId,name,areaM2,pieces,
  place,isMine}]` (top-6 по земле) + `threats[{attackerName,victimName,mine,
  areaM2,atMs}]` за 7 дней (события `territory_events` пишутся при захвате).
- `GET /v1/territories` — добавлены `ownerName`, `capturedAtMs` (паспорт
  квартала и видимое выцветание в приложении).
- `GET /v1/trails/` — добавлены `myBestS`, `myAttempts`,
  `frequentLeader{name,count,isMe}|null` (мотивация прямо в списке).


## Награды «Штамп МАТА» (добавлено 2026-09-02, D-64)

Дизайн-эталон: `docs/design/medals/` (44 награды, утверждено 01.09.2026).
Каталог (названия/ранги/критерии-тексты/ассеты) живёт в клиенте; сервер —
единственный судья и хранит только состояние.

- `GET /v1/me/medals` — состояние всех наград. Ответ: `items[44]`, `earned`,
  `total`. Элемент: `{id, available, earnedAtMs|null, new, engraving{v,u,sub}|null,
  progress{cur,target}?}`.
  - Выдача ленивая и вечная: первый запрос с выполненным критерием пишет
    строку `medal_awards` (уникальность `user_id+medal_id`); удаление исходных
    данных медаль не отбирает.
  - `engraving` — личная гравировка реверса, фиксируется на момент получения
    (значение, подпись, дата — «медали именные»).
  - `new` — три дня после получения (лаймовый кант в клиенте).
  - `available=false` — критерий пока не судится сервером (дневная цель,
    температура, город из GPS, районы, клубный сезон, маппинг дивизионов) —
    клиент показывает такие закрытыми без прогресса.
  - Все «дни» (серии, рассвет/полночь, праздники) — по Asia/Yakutsk.
