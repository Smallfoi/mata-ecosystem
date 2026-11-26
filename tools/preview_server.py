#!/usr/bin/env python3
"""
Preview-сервер Конструктора МАТА: всегда отдаёт СВЕЖУЮ версию.

- Cache-Control: no-store на всё → браузер не кэширует превью (сайт и приложение).
- /flutter_service_worker.js (любой ?v=...) → отдаём «kill-switch» SW: он
  саморазрегистрируется и чистит кэши. Так старый service worker от прежней
  Flutter-сборки перестаёт подсовывать устаревшие ассеты, а новый не появляется.
- /media/* : если файла нет локально (bundled staw-clean) — ПРОКСИРУЕМ на бэкенд
  :8000. Так загруженные в «Конструкторе» фото/видео (лежат в media бэкенда, URL
  относительный /media/…) видны в превью, а сохранённые URL остаются относительными
  (корректно для прод). Range форвардится → перемотка видео работает.

- base href сборки: приложение для прода собирается с --base-href
  /mata-app-preview/ (S3), и тогда локально по корню всё отдавало 404 — белый
  экран превью. Сервер читает base href из index.html и отдаёт сборку И по
  корню, И по её префиксу. Пересобирать ради превью больше не нужно.

Запуск:  python tools/preview_server.py <каталог> <порт>
Сайт:    python tools/preview_server.py "D:/MyProjectsCLAUDE/САЙТ МАТА" 5581
Прилож.: python tools/preview_server.py "D:/MyProjectsCLAUDE/mata_store/build/web" 5579
"""
import os
import re
import sys
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

# Бэкенд для /media/*, /product/* и /sitemap.xml; MATA_PREVIEW_BACKEND — другой порт.
BACKEND = os.environ.get("MATA_PREVIEW_BACKEND", "http://localhost:8000")
BASE_PREFIX = ""   # префикс base href сборки, напр. "/mata-app-preview" (см. заголовок)


def detect_base_prefix(directory):
    """Читаем base href из index.html: сборка под прод живёт не в корне."""
    try:
        with io_open(os.path.join(directory, "index.html")) as f:
            m = re.search(r'<base\s+href="([^"]*)"', f.read())
    except Exception:
        return ""
    href = (m.group(1) if m else "").strip()
    return "" if href in ("", "/") else "/" + href.strip("/")


def io_open(path):
    return open(path, encoding="utf-8", errors="ignore")

# SW, который убивает сам себя и все кэши (kill-switch). Отдаётся вместо
# flutter_service_worker.js — старые регистрации самоуничтожаются.
KILL_SW = b"""self.addEventListener('install', function(){ self.skipWaiting(); });
self.addEventListener('activate', function(e){
  e.waitUntil((async function(){
    var had = false;
    try {
      var keys = await caches.keys();
      had = keys.length > 0;               // had caches = a stale build existed
      await Promise.all(keys.map(function(k){ return caches.delete(k); }));
    } catch (err) {}
    try { await self.clients.claim(); } catch (err) {}
    try { await self.registration.unregister(); } catch (err) {}
    if (had) {                             // reload windows once to get fresh assets
      try {
        var cs = await self.clients.matchAll({ type: 'window' });
        cs.forEach(function(c){ try { c.navigate(c.url); } catch (e) {} });
      } catch (err) {}
    }
  })());
});
// pass-through: no fetch handler, every request hits the network (fresh).
"""


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Медиа (/media/*) — кэшируем (файлы уникальны по имени): так прелоад видео
        # экрана входа реально помогает и открывается мгновенно. Остальное — no-store.
        if getattr(self, "_cacheable", False):
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _serve_kill_sw(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(KILL_SW)))
        self.send_header("Service-Worker-Allowed", "/")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(KILL_SW)

    def _proxy_media(self):
        """Медиа, которого нет локально (загруженные фото/видео), тянем с бэкенда."""
        url = BACKEND + self.path
        req = urllib.request.Request(url, method=self.command)
        rng = self.headers.get("Range")
        if rng:
            req.add_header("Range", rng)
        try:
            resp = urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            return
        except Exception:
            self.send_response(502)
            self.end_headers()
            return
        code = getattr(resp, "status", None) or resp.getcode()
        self.send_response(code)
        for h in ("Content-Type", "Content-Length", "Content-Range",
                  "Accept-Ranges", "Last-Modified", "ETag"):
            v = resp.headers.get(h)
            if v:
                self.send_header(h, v)
        self.end_headers()
        if self.command != "HEAD":
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except Exception:
                    break

    def _route(self):
        p = self.path.split("?", 1)[0]
        if p.endswith("flutter_service_worker.js"):
            self._serve_kill_sw()
            return True
        if p.startswith("/media/") and not os.path.isfile(self.translate_path(self.path)):
            self._proxy_media()
            return True
        # Страница товара и карта сайта — от Django, как на проде (nginx, D-139).
        if p.startswith("/product/") or p == "/sitemap.xml":
            self._proxy_media()
            return True
        return False

    def _strip_base(self):
        """Сборка с base href просит файлы по своему префиксу — снимаем его."""
        if BASE_PREFIX and (self.path == BASE_PREFIX or self.path.startswith(BASE_PREFIX + "/")):
            self.path = self.path[len(BASE_PREFIX):] or "/"

    def do_GET(self):
        self._strip_base()
        self._cacheable = self.path.split("?", 1)[0].startswith("/media/")
        if self._route():
            return
        return super().do_GET()

    def do_HEAD(self):
        self._strip_base()
        self._cacheable = self.path.split("?", 1)[0].startswith("/media/")
        if self._route():
            return
        return super().do_HEAD()

    def log_message(self, *a):
        pass  # тихо


def main():
    global BASE_PREFIX
    directory = sys.argv[1]
    port = int(sys.argv[2])
    BASE_PREFIX = detect_base_prefix(directory)
    handler = partial(NoCacheHandler, directory=directory)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print("preview no-store server on :%d -> %s%s" % (
        port, directory, (" (base href %s/)" % BASE_PREFIX) if BASE_PREFIX else ""), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
