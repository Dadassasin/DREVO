# Передача архивных изображений: 7 ноября 2026

## Итог и границы проверки

Домашний FastAPI выдаёт настоящие JPG и вырезки с внешнего диска через Funnel и Vercel. Исправлен HEAD; добавлен get_image_payload с временными JPEG, SHA-256 и двумя HTTPS-маршрутами. GitHub принимает запрос и получает ответ; техническая задача сохраняется в SQLite как proposed.

**Автономное визуальное чтение обычным ChatGPT не подтверждено.** Веб-инструмент текущего сеанса отверг оба адреса JPEG, а также публичные /api/v1/health и /ai/instructions.md. Точная причина отказа инструмента неизвестна. HEAD исправлен, но не доказан причиной прежних отказов. HTTP 200 не считается завершением интеграции.

## HTTPS и синхронизация

До исправления на JPG 0056 и 0057 через оба origin: GET 200, HEAD 404. После: GET 200 и HEAD 200. Оригиналы: image/jpeg, Content-Length 857726 и 869888 байт, Content-Disposition inline, Cache-Control private, no-store; перенаправлений нет. Добавлен запрет CDN-кеширования подписанных изображений.

Подпись проверяет страницу, вариант, координаты, источник, срок, отзыв и лимит. Дополнительный utm_source не меняет подписанные координаты, повреждённый token отклоняется. TTL по умолчанию 30 минут, до 100 успешных GET. HEAD проверяет те же ограничения, возвращает заголовки GET без тела и не увеличивает hits. Ошибка генерации/повреждённая копия также не расходует GET. Успешные запросы через Vercel увеличивают счётчик домашней SQLite: это не статическая картинка Vercel.

Запрос renew_image_links 278d9d72-9c91-4d19-8d98-bfba825ae324 уже completed, обе страницы, ответ responses/pages/278d9d72-9c91-4d19-8d98-bfba825ae324.json. Предшествовавшие get_crop и get_pages тоже completed. Worker автоматически опрашивает PRIVATE GitHub.

## Почему не Base64 в GitHub

Base64 увеличивает двоичный размер приблизительно на треть. Сто вырезок по 0,8 МБ — около 107 МБ текста до Git-сжатия. Удаление файлов оставляет изображения в истории. Разбиение на части не решает ни эту проблему, ни отсутствие визуального входа.

[Официальная документация OpenAI](https://developers.openai.com/api/docs/guides/images-vision?api-mode=responses) описывает Base64 как data URL внутри image input API. Это не гарантия превращения текста GitHub-коннектора в изображение обычного чата. Нужный инструмент преобразования в пользовательском чате не подтверждён. Поэтому Base64 и его части в Git не добавлены; реализован разрешённый заданием альтернативный временный канал через существующий FastAPI/Funnel/Vercel.

## Новый протокол

Запись requests/images/<новый UUID>.json:

```json
{"schema_version":"1.0","request_id":"<новый UUID>","operation":"get_image_payload","page_id":"e5a194c8f74a08f5d5fe9ce610474d4a","variant":"crop","x":0,"y":100,"width":2500,"height":1000,"output_max_width":2500,"quality":90}
```

Ответ responses/images/<UUID>.json содержит image_payload: delivery=temporary_https_jpeg, url, необязательный direct_url, mime_type, bytes, фактические width/height, source_sha256, sha256 переданного JPEG, expires, link_id и max_gets. Сам JSON изображением не является.

Ссылка /ai/images/<page_id>/payload/<подписанный token>.jpg сразу возвращает JPEG, без query-token, HTML, cookie и redirects. direct_url использует тот же ресурс через текущий Funnel hostname из локального Tailscale CLI. При недоступном CLI direct_url=null, основной адрес продолжает работать.

original/preview создают ограниченную копию полной страницы. Для неизменённых байтов оригинала остаётся get_pages. crop задаёт координаты оригинальных пикселей. output_max_width 64–4096, quality 75–95 (default 90), без увеличения с выдумыванием пикселей. Максимум 2 000 000 байт. Превышение возвращает 413: нужна меньшая вырезка, качество молча не снижается. До 32 активных payload (64 МБ активных JPEG), рендер до двух изображений одновременно в процессе, worker последователен. Общий лимит — 300 новых сообщений в час.

Копии находятся в F:\Архив\.drevo\image-payloads, не в Git/Vercel. Worker удаляет истёкшие, отозванные и осиротевшие копии: защитная задержка 120 секунд плюс период опроса. Если сервер выключен, очистка продолжится после запуска. Метаданные остаются в истории Git, пикселей там нет. Повтор старого UUID возвращает прежний ответ. Для обновления отправьте renew_image_links с новым request_id и исходным renew_request_id в requests/images. Другой JSON с прежним UUID конфликтует.

Проверки доступа сохранены. По явному указанию владельца все 145 существующих исторических дел разрешены для signed_links_allowed; новые импорты по-прежнему private_only. Каталог без авторизации — 401. Подтверждённые факты не изменялись.

## Реальные результаты

Запросы настоящих JPG:

- 0056: requests/images/d4d01631-17bf-4fa3-873e-11a04426db25.json, crop 2500×1400.
- 0057: requests/images/49b6ba3d-a6ad-41f5-89bd-7301405c1acf.json, crop 2500×1000.

Worker сам обработал их. SHA-256 источников на F: совпали с импортом; полученные JPEG совпали с независимым локальным render при quality=90. Через Funnel и Vercel: HEAD 200 без hits, GET 200 с hits+1, image/jpeg, правильный Content-Length, inline, no-store, 0 redirects. Полученные пиксели дополнительно просмотрены локальным инструментом Codex; это не подменяет тест обычного чата.

Предложение save_research_progress 83223a2f-aec3-462d-82cd-694e4224c04a прошло GitHub → worker → SQLite → receipt. Сущность ddf7e705-f22f-475a-b46d-36f2ca040bce: research_task, proposed, version=1. Это техническая задача без расшифровки и без отметки страниц изученными. Снимок всех confirmed-сущностей до/после совпал.

Приватные доказательства: .local/qa/image-delivery.json, payload-0056.jpg, payload-0057.jpg и image-http-diagnostic-*.json. Они исключены из публикации. Автоматизировано: 51 backend/API/script тест прошёл. Проверены подпись, подмена страницы, сроки, отзыв, renew, идемпотентность, SHA переданных байтов, повреждение файла, лимиты, HEAD и совместимость get_pages/get_crop. Предупреждение зависимости Starlette/httpx тесты не блокирует.

```text
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/image_delivery_probe.py prepare
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/image_delivery_probe.py verify
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/image_delivery_probe.py diagnose
rtk proxy .venv/Scripts/python.exe -m pytest backend/tests -q
```

prepare создаёт два новых запроса и техническую proposed-задачу. verify ожидает автоматический worker и проверяет байты и SQLite. diagnose использует старый renew-запрос; после истечения его ссылок 410 ожидаем, для нового сравнения сначала нужен новый renew.

## Тест в обычном чате

> Прочитай manifest.json и schemas/request.schema.json в DREVO-Research-Data. Создай requests/images/<новый UUID>.json: operation=get_image_payload, page_id=e5a194c8f74a08f5d5fe9ce610474d4a, variant=crop, x=0, y=100, width=2500, height=1000, output_max_width=2500, quality=90. Дождись responses/images/<UUID>.json. Открой image_payload.url именно инструментом, передающим пиксели модели; при отказе попробуй direct_url. Назови напечатанный заголовок справа, рукописный номер вверху справа и два различимых рукописных слова. Не бери ответ из каталога или старой расшифровки. Если оба адреса не открылись, приведи точную ошибку инструмента и укажи, есть ли инструмент скачивания и просмотра файла изображения. Без полученных пикселей не сохраняй транскрипцию и не отмечай страницу изученной.

Только визуальный ответ того чата подтвердит совместимость. Если у него нет инструмента получения изображения, автономная работа в текущей конфигурации заблокирована. Совместимый ручной вариант — скачать JPEG и прикрепить как изображение. Отдельный API-клиент без согласования не добавляется.

## Изменённые файлы

- backend/app/api/routes.py — HEAD, временный JPEG, диагностика, заголовки.
- backend/app/security/links.py — проверка без hits, счётчик после подготовки успешного GET.
- backend/app/images/storage.py — размер и качество JPEG.
- backend/app/images/payloads.py — ограниченные копии, SHA-256, прямой origin, очистка.
- backend/app/main.py — HEAD в CORS, запрет CDN-кеширования.
- backend/app/schemas/messages.py — операция, quality, валидация variant/координат.
- backend/app/research/protocol.py — payload и продление.
- backend/app/github_sync/worker.py — requests/images, очистка, описание в manifest.
- backend/tests/test_image_payloads.py — регрессионные проверки.
- scripts/image_delivery_probe.py — реальный интеграционный тест.
- research-template/schemas/request.schema.json — схема; worker экспортирует её в приватный schemas/request.schema.json.
- frontend/public/ai/index.json и instructions.md — возможности и статус совместимости.
- docs/IMAGE-DELIVERY.md, CHATGPT.md, INTEGRATIONS.md, USER_GUIDE.md, STATUS.md — инструкции и результат.
