# Подключение Suunto — пошагово

Suunto приняли нас в **Partner Program** 05.10.2026 (заявка от 29.08). Открыт доступ к
**Suunto Cloud API**: тренировки с GPS-треком, маршруты НА часы, контент во время бега
(SuuntoPlus Guides), суточные данные.

Эти шаги делает **владелец** — это личный аккаунт разработчика и ключи. Код на нашей стороне
пишется после, часы ждут запуска магазина (D-75).

---

## Шаг 1. Принять приглашение (ссылка одноразовая)

Письмо **«You're invited to join Suunto API Zone»** от `apimgmt-noreply@mail.windowsazure.com`.
Нажать ссылку из письма → завести аккаунт разработчика на `smallfoistas21@gmail.com`.

Пароль придумать и сразу сохранить в менеджер паролей.

> Ссылка одноразовая и повторно не работает. Сгорела или потерялась — написать на
> **partners@suunto.com**, выпустят новую (это прямо сказано в письме о приёме).

## Шаг 2. Настроить приложение (OAuth)

Войти в [API Zone](https://apizone.suunto.com) → свой профиль → **OAuth settings**.
Заполняются три поля ([их инструкция](https://apizone.suunto.com/how-to-start)):

| Поле | Что вписать |
|---|---|
| Название приложения | `MATA Квартал` |
| Client secret | длинная случайная строка (или кнопка «сгенерировать») — **сохранить сразу** |
| Redirect URL | `https://api.mata-club.ru/v1/integrations/suunto/callback` |

**Client ID** создаётся сам — он не секретный, его можно прислать в переписке.

Наши адреса подняты и отвечают с 05.10.2026:

| Назначение | Адрес |
|---|---|
| Возврат после разрешения доступа | `https://api.mata-club.ru/v1/integrations/suunto/callback` |
| Вебхук с тренировками | `https://api.mata-club.ru/v1/integrations/suunto/push` |
| Проверка «сервис жив» | `https://api.mata-club.ru/v1/integrations/suunto/status` |

## Шаг 3. Подписаться на Development API

В разделе продуктов выбрать **Development / Starter API** — тот, что для разработки.
Production пока НЕ нужен: его просят, когда интеграция готова.

После подписки ключи появятся в профиле, раздел **«Your subscriptions»**. Нужен
`Ocp-Apim-Subscription-Key` — он идёт в каждом запросе к их API вместе с токеном пользователя.

> У Development API ограничено число вызовов. Для разработки этого хватает, у Production
> ограничений нет.

## Шаг 4. Ключи — в Lockbox, не в переписку

Репозиторий публичный, поэтому секреты не попадают ни в код, ни в чат. В секрет
`mata-prod-secrets` (Yandex Lockbox) добавить:

| Ключ | Что это |
|---|---|
| `SUUNTO_CLIENT_ID` | идентификатор приложения (не секретный, но пусть лежит рядом) |
| `SUUNTO_CLIENT_SECRET` | секрет приложения из шага 2 |
| `SUUNTO_SUBSCRIPTION_KEY` | ключ подписки из шага 3 |

Применить на проде: `sudo bash /opt/mata/backend/deploy/refresh-env.sh` (из Cloud Shell или
по SSH) — скрипт пересоберёт `.env` из Lockbox и перезапустит сервисы.

---

## Что делает дальше Claude

1. Обмен кода на токен и хранение токенов по пользователям (OAuth 2.0).
2. Проверка подписи вебхука (HMAC-SHA256 от тела запроса) — без неё чужим данным верить нельзя.
3. Приём тренировки: скачать [FIT](https://apizone.suunto.com/api-details#api=suunto-workout-api&operation=export-workout-fit),
   разобрать трек, прогнать через оценку достоверности (D-108) и засчитать.
4. Кнопка «Подключить Suunto» в Квартале.
5. Позже — то, ради чего это интереснее COROS: отправка **круга захвата на часы**
   ([маршрут GPX](https://apizone.suunto.com/api-details#api=route-api&operation=import-gpx-route))
   и наш контент во время бега ([SuuntoPlus Guides](https://apizone.suunto.com/suuntoplus)).

## Выход в бой (когда интеграция готова)

1. Подписаться на [Production API](https://suunto-api.developer.azure-api.net/product-details#product=unlimited)
   и обновить профиль приложения.
2. Заполнить [форму материалов для партнёров](https://survey.alchemer.eu/s3/90553909/Suunto-Content-submit-for-Partners).
3. Опубликовать совместимость с Suunto у себя, используя
   [их материалы и правила](https://media.suunto.com/login).

## Справочники (пригодятся при разработке)

- [Как начать](https://apizone.suunto.com/how-to-start) — настройка приложения, авторизация, вебхуки
- [Частые вопросы](https://apizone.suunto.com/faq)
- [Описание FIT-файла](https://apizone.suunto.com/fit-description)
- [Загрузка тренировок к ним](https://apizone.suunto.com/how-to-workout-upload)
- [Суточные данные](https://apizone.suunto.com/api-details#api=new-247-api&operation=daily-activity-samples)
- [Маршруты: описание](https://apizone.suunto.com/route-description)
- [SuuntoPlus Guides: описание](https://apizone.suunto.com/suuntoplus-guide-description)

Отдельно: данные и инфраструктура Suunto **в Китае живут отдельно** — для китайского рынка нужен
отдельный доступ. Нас это не касается.
