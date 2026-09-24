# Часы: Apple, Garmin, Suunto — что подаём и что готовим

Как «Квартал» получает тренировки с часов. Для каждого источника: нужна ли заявка, что в ней
писать, сколько ждать и что делаем мы. Тексты заявок — готовые, их остаётся вставить в форму.

Дата: 29.08.2026. Смежное: `docs/LEAGUE_PLAN.md` §5 (место в плане), `docs/TESTFLIGHT.md` (Apple).

---

## 1. Коротко: четыре источника — четыре разных истории

| Источник | Нужна заявка? | Статус | Срок ответа | Что даёт |
|---|---|---|---|---|
| **COROS** | да | **подана 29.08.2026** | очередь смотрят **раз в месяц**, ответят только если выберут | тренировки, дневные показатели, маршруты, планы |
| **Garmin Connect** | да, партнёрская | **подана 29.08.2026** | 2 рабочих дня | активности (30+ видов), пульс, сон, нагрузка |
| **Suunto Cloud API** | да, партнёрская | **подана 29.08.2026** | до 2 недель | тренировки с GPS-треком, пульс, круги |
| **Apple Health / Apple Watch** | **нет** | ждёт аккаунта разработчика | — | тренировки, пульс, шаги с iPhone и Apple Watch |
| **Health Connect (Android)** | **нет** | делаем сами | — | тренировки со всех часов, чьи приложения туда пишут |

**Главный вывод после подачи всех трёх заявок.** COROS отвечает прямым текстом:
«we limit approvals to integrations with the best market and business fit… we review
the queue monthly and will reach out if you are selected». То есть очередь смотрят
раз в месяц, отвечают только выбранным, а молчание и есть отказ. Мы сейчас —
приложение в закрытом тестировании без аудитории, и с их стороны это не тот
кандидат, за который держатся.

**Поэтому ставку делаем не на заявки, а на Health Connect.** Приложение COROS
пишет тренировки в Health Connect на Android — как и Samsung, Amazfit, Polar,
Xiaomi и, с 2025 года, Garmin Connect. Это значит: человек включает у себя в
приложении часов синхронизацию с Health Connect, разрешает нам чтение — и его
тренировки у нас, **без чьего-либо одобрения**. Один раз сделали — работают
часы всех производителей сразу.

Партнёрские API останутся нужны для того, чего в Health Connect нет: точный
GPS-трек тренировки, отправка планов на часы, работа на iPhone без Apple Watch.
Но ждать их, ничего не делая, не нужно.

Важное различие, которое надо понимать до подачи:

- **Apple заявки не существует.** HealthKit — это не партнёрская программа, а обычная
  возможность iOS-приложения: включается галочкой в проекте. Никто её не «одобряет».
  Единственное, что нужно, — **аккаунт Apple Developer** (тот самый, что нужен и для
  TestFlight) и корректно описанное использование данных при проверке приложения в App Store.
  Проверка смотрит на три вещи: запрашиваем только те типы данных, которые реально используем;
  спрашиваем разрешение в момент, когда функция нужна, а не пачкой на старте; в политике
  конфиденциальности написано, что за данные и зачем. Данные о здоровье нельзя передавать
  в рекламу и в аналитику.
- **Garmin и Suunto** — партнёрские программы для организаций. Заявку подаёт юридическое лицо
  или ИП, не частное лицо. У нас ИП есть, данные ниже.

## 1б. Как это устроено у других (разбор 30.08.2026)

Проверили по документации самих приложений, а не по слухам. Картина одинаковая
у всех: **платформенные хранилища (Health Connect на Android, Apple Health на iOS)
и прямые партнёрские API решают РАЗНЫЕ задачи**, и большие приложения используют
и то, и другое — но для разного.

| Приложение | Откуда берёт тренировки | Health Connect | Apple Health |
|---|---|---|---|
| **Strava** | ~50 прямых партнёрских интеграций (Garmin, COROS, Suunto, Polar, Wahoo, Zwift…) | только ПИШЕТ туда свои активности; принимает обратно лишь вес | ПИШЕТ; читает **только** тренировки штатного приложения Apple Watch, чужие — нет |
| **Runna** | прямые подключения (вход в COROS, OAuth Garmin) **плюс** платформенные хранилища | да, партнёр Health Connect с 2025 | читает завершённые тренировки, есть ручной импорт |
| **COROS (приложение часов)** | свои часы | ПИШЕТ тренировки и пульс | ПИШЕТ тренировки, пульс, дистанции |
| **Garmin Connect** | свои часы | **ПИШЕТ с 2025** (15 типов данных, одностороннее: обратно Garmin ничего не принимает) | ПИШЕТ |
| **Suunto** | свои часы | пишет | пишет («Save to Apple Health») |

Что из этого следует для нас:

1. **Мы выбрали ту же схему, что и Runna, а не что Strava.** Strava может позволить себе
   жить на прямых интеграциях: у неё их полсотни и она сама — та платформа, к которой
   подключаются. Нам, пока нас никто не знает, ровно наоборот: платформенное хранилище
   даёт часы всех производителей сразу и без чьего-либо одобрения.
2. **Да, платформы разные, и это нормально.** Android → Health Connect, iOS → Apple Health.
   Это два разных API, но модель одна: человек разрешает чтение, приложения часов пишут
   туда сами. У нас код уже разведён на источники (`source` в `POST /workouts/import`),
   так что iOS добавится адаптером, а не переделкой.
3. **Strava НЕ читает чужие тренировки из Apple Health — и это её осознанное решение,
   а не запрет Apple.** Читать чужие записи HealthKit разрешает (этим живут RunGap,
   HealthFit). Значит, на iPhone мы сможем забирать тренировки COROS и Garmin из
   Apple Health так же, как на Android из Health Connect.
4. **Зачем тогда вообще партнёрские API.** Ровно за тем, чего в хранилищах нет:
   - **отправить тренировку НА часы** (план недели, интервалы, цель по тропе) — Health
     Connect и Apple Health так не умеют, Garmin вообще ничего не принимает обратно;
     именно ради этого Runna держит прямые подключения к Garmin и COROS;
   - **точный GPS-трек** тренировки (для троп это важно);
   - работа на iPhone у человека **без** Apple Watch, но с Garmin/COROS.
5. **Подводный камень:** в приложении часов синхронизацию с Health Connect надо один раз
   включить руками — сама она не включается. Это надо будет объяснить человеку в
   подсказке, иначе он решит, что не работает наше приложение.

Источники: [Strava · Health Connect](https://support.strava.com/en-us/articles/15401554-health-connect-and-strava),
[Strava · Apple Health](https://support.strava.com/en-us/articles/15402024-apple-health-and-strava),
[Runna · Apple Health и часы](https://support.runna.com/en/articles/14302433-using-your-smart-watch-with-runna),
[COROS · Apple Health](https://support.coros.com/hc/en-us/articles/360041549551-Connecting-Apple-Health-with-COROS-App),
[Garmin · что уходит в Health Connect](https://www.androidcentral.com/wearables/garmin/heres-everything-garmin-will-and-wont-share-with-google-health-connect).

## 2. Что нужно сделать до подачи заявок

| Что | Зачем | Статус |
|---|---|---|
| Публичная страница политики конфиденциальности по постоянному адресу | обе формы просят ссылку; раньше `mata-club.ru/legal/privacy` открывал главную | **готово:** `mata-club.ru/legal/?doc=privacy` |
| Публичная страница пользовательского соглашения | там же | **готово:** `mata-club.ru/legal/?doc=terms` |
| Короткое описание приложения на английском | все формы — на английском | готово, §4 |
| Почта для партнёров | на неё придут ключи доступа | ✅ `bmairussia@gmail.com` + `smallfoistas21@gmail.com` |

## 3. Данные организации для форм

Берутся из публичных документов сайта (раздел «Контакты»):

```
Организация:  Индивидуальный предприниматель Татаринова Алена Анатольевна
              (в англоязычных формах: Individual Entrepreneur Alena Tatarinova)
ОГРНИП:       325140000028101
ИНН:          143524274080
Адрес:        Республика Саха (Якутия), г. Якутск, Россия
Сайт:         https://mata-club.ru
Email:        bmairussia@gmail.com
Вторая почта: smallfoistas21@gmail.com  (COROS просит две, пункты 3 и 4 анкеты)
Телефон:      +7 914 222 59 69
Приложение:   МАТА Квартал (MATA Kvartal), Android — в тестировании, iOS — готовится
```

## 4. Описание приложения на английском (для всех форм)

**Short (одна строка):**

> MATA Kvartal — a running app where every run counts in several leaderboards at once, so runners
> of any speed and age have their own league.

**Full (абзац, годится в поле «describe your application»):**

> MATA Kvartal is a running application built by MATA, a Russian sportswear brand. Runners record
> their runs in the app, earn points for activity and spend those points on the brand's gear —
> one account and one balance across our running app, our store and our website. The product is
> built around the idea that a single run should count in several leaderboards at once: absolute
> results, personal bests, consistency over 90 days, and an age- and gender-adjusted league, so
> that slower, older and beginner runners are not pushed out of competition. Many of our users
> train with a sports watch and do not carry a phone in their hand, so their activity is currently
> not counted at all. We need read access to completed workouts (start time, duration, distance,
> heart rate, GPS track where available) to award points for those sessions and include them in
> our leaderboards. We do not resell data, do not use it for advertising and do not share it with
> third parties.

**Use case (одна фраза, если поле отдельное):**

> Import completed workouts recorded on the user's watch so they receive activity points and
> appear in our leaderboards without carrying a phone.

**Data we request:** workout start time, duration, distance, activity type, average and maximum
heart rate, calories, GPS track where available.

**Expected volume (спрашивают в обеих формах):** до 5 000 подключённых устройств в первый год,
приложение работает в России.

## 5. Заявка в Garmin — что именно заполнять

**Формы заявки на сайте программы больше нет** — вместо неё висит «Stay tuned for
more updates on the program». Проверено 29.08.2026 на
<https://developer.garmin.com/gc-developer-program/overview/>. Единственный рабочий
путь — форма обращения к разработчикам:

**<https://www.garmin.com/en-US/forms/developercontactus/>**

Полей всего шесть, вся заявка — три минуты. Значения (звёздочкой отмечены
обязательные):

| Поле формы | Что вписать |
|---|---|
| Name * | `Mikhail Tatarinov` |
| Company name * | `MATA (IE Mikhail Tatarinov)` |
| Email address * | `bmairussia@gmail.com` |
| Country & State/Province/Region * | `Russia` |
| **Which developer program are you interested in?** * | **`Garmin Connect Developer Program`** — это ключевой выбор, в списке есть похожие (Connect IQ SDK, Garmin Health SDKs), они не про то |
| Message | текст ниже |
| reCAPTCHA | пройти самому — это то, чего не может сделать автоматика |

**Текст в поле Message** (копировать целиком):

```
Hello,

We would like to request access to the Garmin Connect Developer Program
(Activity API, and Health API if it fits our use case).

MATA Kvartal is a running application built by MATA, a Russian sportswear brand.
Runners record their runs in the app, earn points for activity and spend those
points on the brand's own gear — one account and one balance across our running
app, our store and our website. A single run counts in several leaderboards at
once: total distance, personal bests, consistency over 90 days, and an age- and
gender-adjusted league, so that slower, older and beginner runners are not pushed
out of competition.

Many of our users train with a Garmin watch and do not carry a phone in their
hand, so their activity is currently not counted at all. We are asking for read
access to completed activities (start time, duration, distance, activity type,
heart rate, GPS track where available) in order to award activity points for those
sessions and include them in our leaderboards.

We do not resell data, do not use it for advertising and do not share it with
third parties. Data is stored on our own servers and is deleted when the user
disconnects the integration.

Company: Individual Entrepreneur Alena Tatarinova (OGRNIP 325140000028101,
INN 143524274080), Yakutsk, Russia
Website: https://mata-club.ru
Application: MATA Kvartal — Android in testing, iOS in preparation
Expected volume: up to 5,000 connected devices in the first year
Privacy policy: https://mata-club.ru/legal/?doc=privacy
Terms: https://mata-club.ru/legal/?doc=terms

Thank you,
Mikhail Tatarinov
```

Ответ обещают в течение двух рабочих дней. Лицензионных платежей нет, но программа
только для делового использования — поэтому подаём от ИП.

## 6. Заявка в Suunto — что именно заполнять

Анкета живёт не на сайте Suunto, а отдельно:

**<https://survey.alchemer.eu/s3/90553908/PARTNER-Become-a-Suunto-Partner>**
(со страницы <https://www.suunto.com/partners/welcome-partners/> — кнопка «Apply now»)

Заполнять **на английском**, займёт около пяти минут, ответ в течение двух недель.
Важно знать заранее: **при отправке подписывается API Agreement** (юридическое
соглашение с Suunto Oy) и оформляется подписка на их рассылку для партнёров —
отписаться можно потом.

Анкета из шести шагов. Что отвечать:

**Шаг 1 — вводный.** Просто «Next».

**Шаг 2 — Contact information.**

| Поле | Значение |
|---|---|
| First Name / Last Name | `Mikhail` / `Tatarinov` |
| Title | `Founder` |
| Company Name | `MATA (IE Mikhail Tatarinov)` |
| City / Country | `Yakutsk` / `Russia` |
| Email Address | `bmairussia@gmail.com` |
| Phone Number | `+7 914 222 59 69` |
| Company website | `https://mata-club.ru` |

**Шаг 3 — про продукт.**

- *Name for this:* `MATA Kvartal — running app`
- *Where to learn more:* `https://mata-club.ru`
- *Describe the tools/app you are working with:*
  `A running app by MATA, a Russian sportswear brand. Runners record runs, earn
  points for activity and spend them on the brand's gear — one account and one
  balance across the running app, the store and the website. A single run counts
  in several leaderboards at once: distance, personal bests, consistency over
  90 days, and an age- and gender-adjusted league.`
- *Key benefits:* `Runners of any speed and age have a leaderboard they can win.
  Activity converts into real gear instead of abstract points.`
- *Describe your customers:* `Amateur runners in Russia, from beginners to
  competitive age-groupers. A typical user runs 2–4 times a week in their own
  neighbourhood; many train with a sports watch and do not carry a phone.`
- *Size of customer base:* `Early stage: Android build in closed testing, up to
  5,000 connected users expected in the first year.`
- *Which countries:* `Russia (primary market), CIS`
- *Прошлый опыт с Suunto:* отметить `Other` → `No prior integration with Suunto`

**Шаг 4 — направления сотрудничества.** Отметить **только**
`I want to have access to Suunto Cloud Api`. Остальные блоки (Value Pack,
Movesense, SuuntoPlus Sport apps) — не наша история, лишние галочки затянут
рассмотрение.

- *What type of data would you like to use and for what purpose:*
  `Completed workouts (start time, duration, distance, sport type, heart rate and
  GPS track where available). We use them to award activity points and include
  the workout in our leaderboards, so that users who train with a Suunto watch
  and without a phone are not left out. We do not resell data and do not use it
  for advertising.`

**Шаг 5 — API Agreement и права доступа.** Здесь читается и принимается соглашение,
перечисляются разработчики (имя, фамилия, email — можно только себя) и отмечается,
какие данные нужны. **Отмечать только `Get workout data`** — просить минимум и
правильно, и быстрее рассматривается. Остальное (шаги, сон, маршруты, планы) нам
сейчас не нужно; если понадобится — расширим.

**Шаг 6** — отправка.

## 6б. Заявка в COROS — что именно заполнять

**Куда:** анкета <https://coros-teams.feishu.cn/share/base/form/shrcnLqSduZsaNhbvDJTO2x0Vlf>
(ссылка со страницы поддержки «Submit an API Application»). Параллельно COROS просит
написать на **api@coros.com** — короткое письмо с теми же данными.

**Чем COROS отличается от Garmin и Suunto.** Здесь не просто «дайте доступ»: анкета
из 24 пунктов, к ней **обязательно прикладываются логотипы**, и часть вопросов —
про адреса на нашем сервере, которые должны существовать заранее. Плюс два условия,
которые надо принять осознанно:

- **партнёр обязан завести у себя страницу входа в интеграцию и страницу поддержки**,
  чтобы человек мог подключить часы и написать, если сломалось. У нас этого пока нет —
  сделаем к моменту, когда выдадут ключи;
- **COROS отбирает заявки**: смотрят размер аудитории и то, как будут использованы
  данные. Отказ возможен, и это не формальность. Денег за интеграцию не берут.

### Логотипы (без них не одобрят)

Готовы, лежат в `Презентации/COROS-заявка/`:

| Файл | Когда нужен |
|---|---|
| `MATA-logo-144x144.png` | всегда |
| `MATA-logo-102x102.png` | всегда |
| `MATA-logo-120x120.png` | если просим синхронизацию тренировок — а мы просим |
| `MATA-logo-300x300.png` | то же |

Собираются командой `python tools/brand/make_partner_logos.py` из эталона знака
`mata_kvartal/build/mark_icon_1024.png` — того самого, из которого делаются иконка
приложения и заставка. Логотип в каталоге партнёра должен совпадать с тем, что
человек видит на телефоне.

**Чего делать нельзя:** брать `assets/brand/kvartal-app-icon.png`. Это старая
иконка (карта с маршрутом), она давно не стоит на приложении — я один раз уже
приложил её к заявке по ошибке.

### Адреса на нашем сервере (уже работают)

| Пункт анкеты | Что вписать |
|---|---|
| 12. Authorized Callback Domain | `https://api.mata-club.ru/v1/integrations/coros/callback` |
| 13. Workout data receiving endpoint | `https://api.mata-club.ru/v1/integrations/coros/push` |
| 14. Service status check URL | `https://api.mata-club.ru/v1/integrations/coros/status` |

Эти три адреса отвечают прямо сейчас — COROS проверяет их до выдачи ключей, поэтому
они сделаны заранее. Разбор данных появится вместе с Client ID и Secret: пока подпись
запроса проверить нечем.

### Ответы по пунктам анкеты

| № | Вопрос | Ответ |
|---|---|---|
| 1 | Platform / Application Name | `MATA` |
| 2 | Company Name | `Individual Entrepreneur Mikhail Tatarinov (MATA)` |
| 3 | Primary Contact Email | `bmairussia@gmail.com` |
| 4 | Secondary Contact Email | `smallfoistas21@gmail.com` |
| 5 | Privacy Officer Email | `bmairussia@gmail.com` |
| 6 | Company Owner Name and Title | `Mikhail Tatarinov, Founder` |
| 7 | Platform / Application URL | `https://mata-club.ru` |
| 8 | Description (**до 100 знаков**, покажут на их сайте) | `Running app where every run counts in several leaderboards, so any runner has a league.` |
| 9 | Total Active Users | `0-150` — честно: приложение в закрытом тестировании |
| 10 | Primary Region | `Russia` |
| 11 | Какие функции API нужны | **только** `Activity / Workout Data Sync (one way, COROS to your platform)` |
| 12 | Authorized Callback Domain | адрес из таблицы выше |
| 13 | Workout data receiving endpoint | адрес из таблицы выше |
| 14 | Service status check URL | адрес из таблицы выше |
| 15 | Bluetooth / ANT+ протокол | `N/A` |
| 16 | Personal или Public | `Public` |
| 17 | Commercial или Non-Commercial | `Commercial` |
| 18 | Intended use of data | текст ниже |
| 19 | Expected Integration Launch Date | ориентир — через 2–3 месяца после выдачи ключей |
| 20 | Согласие с Application Terms | `Yes` |
| 21 | Согласие с COROS API Agreement | прочитать PDF по ссылке в анкете, затем `Yes` |
| 22 | Ваше имя | `Mikhail Tatarinov` |
| 23 | Submit Date | дата подачи |
| 24 | Логотипы | четыре файла из `Презентации/COROS-заявка/` |

**Пункт 18 — Intended use of data:**

```
Users connect their COROS account so that workouts recorded on their watch are
counted in our app. For each completed workout we read start time, duration,
distance, sport type, heart rate and GPS track where available. We use this to
award activity points and to place the workout in our leaderboards: total
distance, personal bests, consistency over 90 days, and an age- and
gender-adjusted league.

Data is stored on our own servers in Russia, is never resold, never used for
advertising and never shared with third parties. When a user disconnects the
integration, imported workouts are deleted. GPS tracks are kept only long enough
to match a run against our route segments and are deleted after 14 days.
```

**Про пункт 11.** Просим одну функцию — тренировки из COROS к нам. Обратная
синхронизация, планы тренировок, маршруты и дневные показатели нам сейчас не нужны,
а каждая лишняя галочка — повод разбираться дольше и вопрос «зачем вам это».

## 7. Что делаем мы, не дожидаясь ответов

Ни одна из заявок не блокирует работу. Порядок реализации:

1. **Health Connect (Android)** — ✅ СДЕЛАНО 30.08.2026. Системное хранилище здоровья
   на Android: заявка не нужна, а тренировки приходят с часов COROS, Samsung, Amazfit,
   Polar и прочих — со всех, чьи приложения туда пишут. Человеку достаточно разрешить
   чтение. В «Лиге»: Профиль → Настройки → «Часы и приложения».
   Подробности — `docs/LEAGUE_PLAN.md` §5, «Что уже сделано».
2. **Импорт файлов GPX / TCX / FIT** — тоже ни от кого не зависит. Закрывает перенос
   истории из ушедших сервисов: Strava, Nike Run Club и adidas Running отдают архив
   тренировок файлами.
3. **Apple Health** — как только появится аккаунт Apple Developer.
4. **Garmin / Suunto** — по мере одобрения; адаптеры втыкаются в общий механизм импорта,
   который к тому моменту уже будет работать (`external_workout`, `docs/LEAGUE_PLAN.md` §5).

## 8. О чём договориться заранее

- **Пульс — это данные о здоровье.** Нужен отдельный экран согласия при подключении часов
  и упоминание в политике конфиденциальности: какие данные, зачем, сколько храним, как отключить.
- **Отключение = удаление.** Пользователь отключил часы — удаляем импортированные тренировки.
  Это требование и Garmin, и Apple, и здравого смысла. Сделано: `DELETE /workouts/source/:source`.
  Начисленные баллы при этом остаются — они заработаны, отзывать их нечестно.
- **Никакой рекламы на данных о здоровье.** Прямой запрет Apple; нарушение — снятие приложения.
- **Двойной учёт.** Тренировка с часов и наш собственный забег в те же минуты — одно и то же
  событие. Очки начисляем один раз, иначе получится дыра для накрутки.

## 9. Источники

- [Garmin Connect Developer Program — обзор](https://developer.garmin.com/gc-developer-program/)
- [Garmin Connect Developer Program — FAQ (сроки, платежи, деловое использование)](https://developer.garmin.com/gc-developer-program/program-faq/)
- [Garmin Activity API](https://developer.garmin.com/gc-developer-program/activity-api/)
- [Suunto APIzone — FAQ (как получить доступ, что отдаёт API)](https://apizone.suunto.com/faq)
- [Suunto — партнёрская программа](https://www.suunto.com/partners/welcome-partners/)
- [Apple — Health and Fitness для разработчиков](https://developer.apple.com/health-fitness/)
- [COROS — Submit an API Application](https://support.coros.com/hc/en-us/articles/17085887816340-Submit-an-API-Application)
- [COROS — анкета заявки](https://coros-teams.feishu.cn/share/base/form/shrcnLqSduZsaNhbvDJTO2x0Vlf)
