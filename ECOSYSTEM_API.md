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
  "createdAt": "2026-06-05T13:09:00Z"
}
```
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
POST /auth/phone/request       { phone }                 → { ok, smsEnabled }   (шлёт код; dev — всегда 1234)
POST /auth/phone/verify        { phone, code }           → { token, user }      (создаёт аккаунт при первом входе)
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
GET /products/search?q=:q               → Product[]
GET /brands                             → string[]
GET /sizes                              → string[]
GET /products/price-range               → { min, max }
GET /banners                            → Banner[]
```

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
POST /integrations/1c/orders/ack     { orderIds: [] } → { acked, unknown[] }
POST /integrations/1c/orders/status  { orders: [...] }→ { received, updated, errors }
```

**Заказ остаётся в очереди, пока 1С не подтвердит приём** через `ack`. Оборванная
связь не должна стоить покупателю заказа, поэтому выдача и подтверждение — разные
запросы. Повторный `ack` не ошибка (`acked: 0`).

**В очередь попадают только заказы, готовые к сборке:** оплата не требуется
(`none`) или уже прошла (`paid`). Заказ, ждущий оплаты, в 1С не уходит — иначе там
копятся брошенные корзины.

Заказ отдаётся в виде: `{ orderId, createdAt, customer{phone,name,email}, items[],
total, deliveryCost, pointsRedeemed, payment, paymentStatus, delivery, address,
postalCode }`. Позиция: `{ id, article, productId, name, size, color, qty, price }` —
`id` и `article` подставляются из карточки товара, чтобы склад не сопоставлял позиции
по названию.

**Статусы обратно:** `{ orderId, status, number? }`, где `status` — `accepted`,
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
GET  /loyalty/account                   → { balance, level, transactions: LoyaltyTransaction[] }
POST /loyalty/transactions  LoyaltyTransaction → 200   (только redeem/прочее; начисления — серверные)
                            source ∈ {runnerRun, runnerTerritory, purchase, registration} → 403
                            (анти-чит S-04 D-23: начисление считает сервер —
                             бег→/runs, территория→/territories/capture, покупка/рег→/orders)
```

### Runs (история пробежек + серверный расчёт очков — анти-чит S-04)
```
GET  /runs                              → Run[]   (сводки забегов пользователя, новые сверху)
POST /runs  { id, distanceMeters, elapsedSeconds, finishedAtMs, capturedTerritory, capturedZones, mockDetected? }
                                        → { ok, duplicate, flagged, flagReason, pointsAwarded, run }
            mockDetected: bool (опц.) — клиент сообщает о подделке геолокации (Android mock-GPS)
            → сервер флагает забег (0 очков); накопление флагов помечает аккаунт «на ревью» (S-04).
```
Сырой GPS-маршрут НЕ передаём/не храним (приватность §2). Сервер сам валидирует забег
(скорость ≤ 40 км/ч, дистанция/время, суточный лимит) и НАЧИСЛЯЕТ очки за бег
(`runnerRun` = км×10), идемпотентно по `id`. Неправдоподобный забег → `flagged`, 0 очков.
Клиент очки за бег больше НЕ присылает.

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
     района, пишет попытки и УДАЛЯЕТ трек через 14 дней (D-60). Выключен тумблер
     «участвовать в тропах» → { attempts: [], skipped: "trailsDisabled" }, трек
     не сохраняется вовсе.

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
POST /workouts/import  { source, items[] }  → { imported, duplicates, skipped, points, items[] }
GET  /workouts[?source=]                    → { items[] }
DELETE /workouts/source/:source             → { removed }   (человек отключил источник)
```
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
В корзине применяет → заказ с pointsRedeemed → POST /loyalty/transactions {source:"redeem", amount:-430}
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
