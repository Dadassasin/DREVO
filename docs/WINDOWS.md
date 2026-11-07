# Windows: установка и обслуживание

Подробное руководство владельца — USER_GUIDE.md. Основной архив и рабочая SQLite находятся на внешнем диске F:, программа установлена отдельно на каждом ПК. Не размещайте SQLite WAL в сетевой папке. Второй ПК автоматически готовится файлом «Установить ДРЕВО на этом ПК.bat» в корне архива; подробности — TWO-PCS.md.

## Команды

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_online.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_health.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_all.ps1
```

start_online запускает API и GitHub-worker, подключает существующий Funnel и переключает Vercel на текущий ПК. start_server.bat запускает только локальную часть. Остановка завершает WAL и сохраняет резервную копию на внутреннем диске. Автозапуск сервера Windows отключён; после перезагрузки запуск вручную. Никаких служб Cloudflare для ДРЕВО нет.

Нужны Python 3.12 и Node.js 22.12+; установщик второго ПК устанавливает зависимости через winget. Для исходного проекта install.bat создаёт .venv, выполняет миграции и собирает frontend. Сначала требуется корректная приватная .env с путями к существующей базе. Коды и ключи не копируются в публичный код.

Логи и PID-файл находятся в .local папки программы. Данные, ключ и кеш — в настроенном DREVO_DATA_DIR. Код администратора не встраивается в frontend. Доступ к локальным .env и .local ограничивается текущим Windows-пользователем и SYSTEM. PowerShell-скрипты имеют UTF-8 BOM для Windows PowerShell 5.1.

## Импорт и контроль

Reference-mode читает существующий каталог или ZIP без копирования оригиналов. Managed-mode копирует разрешённые изображения в data_dir/managed. Обычный запуск сервера не переиндексирует архив. Изменение буквы диска не заменяется повторным импортом: текущая переносная конфигурация рассчитана на F:.

```powershell
cd backend
..\.venv\Scripts\python.exe -X utf8 -m app.cli check
..\.venv\Scripts\python.exe -X utf8 -m app.cli verify-integrity --limit 10
..\.venv\Scripts\python.exe -X utf8 -m app.cli set-code --role admin
```

Полный verify-integrity читает все оригиналы и занимает время; без необходимости достаточно выборочной проверки. Перед импортом новых материалов проверьте корень и выбранное дело. История операций и SHA-256 позволяют отделять прежний источник от изменённой копии.

## Резервирование

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup.ps1 -Destination C:\DrevoBackups\drevo.sqlite3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restore.ps1 -Source C:\DrevoBackups\drevo.sqlite3
```

Сканы и signing.key резервируются отдельно от SQLite. Копия на том же внешнем диске не заменяет независимую копию. Restore предварительно останавливает сервер, сохраняет текущую базу и отзывает сессии/ссылки в восстановленной копии. Нужны согласованные пути к тем же исходным сканам.
