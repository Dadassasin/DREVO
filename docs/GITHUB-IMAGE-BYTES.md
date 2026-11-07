# Изображения через приватный GitHub

Актуальный способ get_image_payload передаёт **байты JPEG**, а не только ссылку. Схема: запрос GitHub → домашний worker → скан с F: → вырезка JPEG → Base64-части в PRIVATE DREVO-Research-Data → декодирование файла → инструмент визуального анализа чата. Vercel и Funnel для получения этих байтов не нужны.

## Запрос

Создать requests/images/<новый UUID>.json:

```json
{
  "request_id": "<новый UUID>",
  "operation": "get_image_payload",
  "delivery": "github_base64",
  "page_id": "e5a194c8f74a08f5d5fe9ce610474d4a",
  "variant": "crop",
  "x": 350,
  "y": 120,
  "width": 900,
  "height": 280,
  "output_max_width": 900,
  "quality": 90,
  "part_bytes": 12288
}
```

Для новых get_image_payload delivery=github_base64 по умолчанию. delivery=https оставляет прежний режим. original/preview означают ограниченную копию полной страницы, crop — вырезку из оригинальных пикселей. Качество 75–95, ширина 64–4096, увеличения с выдумыванием пикселей нет.

## Получение файла

1. Дождаться responses/images/<UUID>.json со status=completed.
2. В image_payload проверить delivery=github_base64_parts, bytes, sha256, source_sha256, part_count и parts.
3. Через подключённый приватный GitHub прочитать **каждый** parts[].path. Это responses/images/<UUID>/part-0000.json и следующие части.
4. Каждый файл содержит request_id, encoding=base64, index, offset, bytes, sha256 и **data с настоящими Base64-байтами**. Декодировать каждую data отдельно; склеивать именно декодированные байты по index, а не строки Base64 с возможным padding.
5. Проверить последовательность index, offset, размер и SHA-256 каждой части, затем размер и SHA-256 полного JPEG.
6. Сохранить результат как .jpg и передать **файл** инструменту визуального анализа. Простое чтение Base64 не является просмотром изображения.

Готовый декодер со стандартной библиотекой Python находится прямо в том же PRIVATE репозитории: outbox/research-context/image-delivery.json, поле decoder_python. Ссылка на этот файл есть в manifest.json → image_delivery.instructions. Поэтому внешний сайт не нужен даже для получения инструкции/декодера.

В исходниках декодер — scripts/decode_image_payload.py. Если части уже скачаны инструментом чата в папку, команда:

```text
python decode_image_payload.py response.json downloaded-parts-folder output.jpg
```

Декодер принимает части по именам part-NNNN.json или по полному пути внутри скачанного репозитория. Проверяет все контрольные суммы, размеры, порядок, привязку к UUID и JPEG-маркеры. Он не выполняет HTTP-запросы. Функцию assemble(response, load_part) можно вызвать непосредственно из инструмента обработки файлов.

Default part_bytes=12288: не более 16384 символов Base64 на часть. Допустимый диапазон 4096–49152 байта. Если GitHub-инструмент обрезал JSON, нужно получить полный файл или создать новый запрос с меньшим part_bytes. Нельзя собирать изображение из обрезанного текстового пересказа инструмента.

## Целостность, повторы и хранение

Ответ и все его части публикуются **одним атомарным Git-коммитом**. При частичной сетевой ошибке повтор не создаёт вторую версию набора. Обновление ветки выполняется без force; параллельные изменения других файлов сохраняются. Существующее отличающееся содержимое image bundle вызывает конфликт.

Одинаковый request_id и JSON возвращают прежний результат. Новый JSON требует нового UUID. Истёкший набор обновляется через renew_image_links в requests/images с новым request_id и renew_request_id исходного запроса. Режим исходной доставки сохраняется: для перехода со старой HTTPS-копии на GitHub нужно создать новый get_image_payload с delivery=github_base64.

Лимиты: до 2 000 000 двоичных байт на JPEG, до 32 активных локальных копий, до 20 000 000 двоичных байт за скользящие 24 часа для GitHub. Превышение возвращает ошибку; качество автоматически не снижается. Предпочтительны небольшие читаемые вырезки. Разрешение на дело и источник проверяются перед подготовкой и перед публикацией частей. Архив в публичный DREVO не загружается.

Через 30 минут (или срок из expires) worker удаляет части из **текущей ветки**; также очищает их после отзыва разрешения. Manifest/receipt остаются. Если сервер выключен или GitHub недоступен, очистка продолжится после восстановления работы. Уже переданные байты и копии в истории Git удалением ветки не отзываются. Владелец явно выбрал этот транспорт; это осознанное отличие от временной HTTPS-ссылки.

## Проверка

```text
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/image_delivery_probe.py prepare
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/image_delivery_probe.py verify-bytes
```

prepare отправляет реальные запросы JPG 0056–0057 в PRIVATE GitHub и техническую proposed-задачу. verify-bytes получает части только через GitHub API, собирает JPEG, сравнивает с локальной вырезкой и SHA-256 скана, проверяет proposed receipt в SQLite и неизменность confirmed-сущностей. Не обращается к URL изображений Vercel/Funnel.

Доказательства: .local/qa/image-delivery.json; собранные JPEG github-payload-0056.jpg и github-payload-0057.jpg; исходные JSON в github-parts-0056 и github-parts-0057. Эти диагностические файлы не публикуются в исходниках.

Реальный результат 7 ноября 2026:

| JPG | request_id | Части | Собранные байты | GET к URL изображения |
|---|---|---|---|---|
| 0056 | 95d881b2-8ade-4754-86ff-4fbcbec4c0a7 | 68 | 832585 | 0 |
| 0057 | be3ba5d8-2c66-468f-a1e3-393ac4e2e42f | 50 | 609072 | 0 |

Оба JPEG полностью получены через GitHub JSON; SHA-256 каждой части и полного изображения проверены, полный результат совпал с вырезкой из скана на F:. Собранный из GitHub JPG 0057 открыт визуальным инструментом Codex. Это подтверждает файл и байты, но отдельный пользовательский чат должен передать их своему инструменту самостоятельно.

Техническая proposed-задача: entity_id=f7cf2ba9-2cbe-49f1-a2fa-d51b2ac11fbf, version=1, receipt операции 5f3d4cfb-91f1-40ea-b74d-5cafe7d8f6c1. Данные confirmed до/после совпали. Пройдено 54 backend/API/script теста: включая сборку частей, обнаружение повреждения/перестановки, квоту, повторы без новых коммитов, сохранение параллельных файлов при изменении ветки, запрет публикации в public repo и очистку частей после отзыва.

Изменения реализации: backend/app/images/payloads.py, schemas/messages.py, research/protocol.py, github_sync/client.py, github_sync/worker.py, api/routes.py; scripts/decode_image_payload.py и image_delivery_probe.py; тесты test_github_image_bytes.py, test_github.py и test_image_payloads.py; JSON Schema в research-template/schemas/request.schema.json; AI-инструкции frontend/public/ai и документация. Схемы, инструкция и декодер автоматически экспортированы в PRIVATE DREVO-Research-Data. Архивные пиксели отсутствуют в публичном коде.

## Готовый тест чата

> Прочитай manifest.json → image_delivery.instructions в DREVO-Research-Data. Создай новый get_image_payload с delivery=github_base64 для page_id=e5a194c8f74a08f5d5fe9ce610474d4a, variant=crop, x=350, y=120, width=900, height=280, output_max_width=900, quality=90. Прочитай ответ и все parts[].path через GitHub. Декодируй data каждой части, собери JPEG, проверь sha256 и передай файл своему инструменту визуального анализа. Внешние URL изображений не открывай. Назови два действительно видимых рукописных слова; если инструмент не получил файл, сообщи точную ошибку и не утверждай, что видел изображение.

Передача байтов и способность конкретного чата передать файл в vision — две отдельные проверки. Исторические выводы сохраняются только после фактического просмотра пикселей и остаются proposed до проверки человеком.
