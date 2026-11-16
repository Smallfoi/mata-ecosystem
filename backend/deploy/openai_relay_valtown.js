// Посредник к OpenAI. Выкладывается вручную на val.town (новый HTTP val),
// живёт вне России и вне сети Cloudflare.
//
// ЗАЧЕМ. Прод в РФ, а OpenAI отвечает российским адресам
// `unsupported_country_region_territory` — ещё до проверки ключа. С 27.09.2026
// это обходил HTTP-прокси (tinyproxy) на VPS Timeweb в Амстердаме. У той схемы
// два изъяна, из-за которых она и встала: прокси пускает по списку адресов, и
// в списке остался IP прода эпохи Yandex Cloud (158.160.12.117), а прод с тех
// пор переехал дважды — Beget, затем Cloud.ru (87.242.100.147); и VPS стоит
// денег (на 10.11.2026 баланса Timeweb оставалось дней на пять).
//
// ПОЧЕМУ НЕ CLOUDFLARE. Проверено 27.09.2026 и записано в WORKLOG: ни AI
// Gateway, ни воркер, ни привязка к региону не помогают. OpenAI сам за
// Cloudflare, и внутри их сети едет страна исходного клиента — с прода даже
// заведомо неверный ключ получал отказ по стране. val.town снаружи тоже за
// Cloudflare, но это только вход: наружу запрос уходит с её собственных
// серверов. Проверено делом — так уже работает релей к Anthropic для Pareta.
//
// ЗАЩИТА. Ключ проходит насквозь и здесь не хранится. Заголовок добавить
// неоткуда — клиент шлёт свои, — поэтому пропуском служит сам адрес: база с
// секретным путём. На бесплатном тарифе val.town код публичен, поэтому секрет
// берётся из переменной окружения, а не из файла.
//
// КАК ВЫЛОЖИТЬ:
//   1. Секрет: openssl rand -hex 16
//   2. val.town → New → HTTP → вставить этот файл
//   3. Settings → Environment Variables → RELAY_SECRET = эта строка
//   4. В Lockbox `mata-eco-image`: OPENAI_BASE_URL=https://<адрес>/<секрет>/v1
//      и УБРАТЬ OPENAI_PROXY — иначе запрос пойдёт прежним путём, мимо релея.
//   5. Выкатить секреты на прод и прогнать `photo_test`.

const SECRET = (globalThis.Deno?.env?.get("RELAY_SECRET") ?? "").trim();
const UPSTREAM = "https://api.openai.com";

// Наверх уходит только нужное API: белый список, а не чёрный, чтобы ничто
// лишнее не рассказало о происхождении запроса. content-type обязателен —
// в нём граница multipart, без неё картинка не доедет.
const PASS = (name) =>
  name === "authorization" || name === "content-type" || name === "accept" ||
  name === "user-agent" || name.startsWith("openai-") || name.startsWith("x-stainless-");

async function handler(request) {
  const url = new URL(request.url);
  const prefix = "/" + SECRET;
  if (!SECRET || !url.pathname.startsWith(prefix + "/")) {
    return new Response("not found", { status: 404 });
  }

  const headers = new Headers();
  for (const [name, value] of request.headers) {
    if (PASS(name.toLowerCase())) headers.set(name, value);
  }

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.arrayBuffer();

  const upstream = await fetch(
    UPSTREAM + url.pathname.slice(prefix.length) + url.search,
    { method: request.method, headers, body },
  );

  // Поток отдаём как есть: генерация картинки идёт минутами и приходит
  // событиями (SSE) — собрав ответ целиком, мы бы ждали конца молча и рисковали
  // упереться в таймаут.
  const out = new Headers(upstream.headers);
  out.delete("content-encoding");
  out.delete("content-length");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

// val.town — эта строка. На Deno Deploy заменить на: Deno.serve(handler);
export default handler;
