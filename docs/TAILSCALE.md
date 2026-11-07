# Постоянный адрес API без покупки домена

Tailscale Funnel публикует локальный API по HTTPS-имени устройства в домене `ts.net`. Интерфейс остаётся на Vercel; авторизация, SQLite и файлы обслуживаются домашним сервером. Исходники и сканы не загружаются в Tailscale как хранилище.

## Первоначальное подключение

1. Установите официальный Tailscale для Windows и войдите в личный аккаунт.
2. Добавьте компьютер в tailnet. Для этой задачи не требуются exit node, доступ к домашней подсети или Tailscale SSH.
3. Запустите ДРЕВО через `start_server.bat`.
4. Выполните в PowerShell:

```powershell
tailscale funnel --bg http://127.0.0.1:8000
```

Если CLI выдаст ссылку, откройте её в аккаунте владельца и разрешите HTTPS/Funnel. Tailscale получит сертификат и покажет адрес вида `https://имя-компьютера.имя-сети.ts.net`. При первой выдаче сертификата HTTPS может быть готов не сразу; не отключайте проверку TLS.

Повторный запуск после настройки:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_tailscale_funnel.ps1
tailscale funnel status
```

После внешней проверки `GET /health = 200` настройте внешние rewrite в `frontend/vercel.json`: `/api/*`, `/ai/images/*`, `/ai/crops/*`, `/health` → соответствующие пути Funnel. Для текущей схемы `DREVO_PUBLIC_API_URL`, `DREVO_FRONTEND_ORIGIN` и production-переменная Vercel `VITE_API_URL` равны `https://drevo-beta.vercel.app`. Перезапустите API и переиздайте frontend.

Так браузер и подписанные ссылки используют один адрес Vercel. Это также обходит наблюдавшийся обрыв публичного TLS к Funnel из домашней сети: из облака Vercel подключение проверено. Vercel передаёт запросы и ответы, включая изображения; кеширование API запрещено. Лимиты трафика Vercel и Funnel сохраняются.

## Автозапуск и сохранение

`--bg` сохраняет Funnel в службе Tailscale; он возобновляется после перезапуска Tailscale/компьютера. Пока сохраняются имя устройства и домен tailnet, адрес не меняется при обычном перезапуске. Переименование или повторная регистрация устройства могут потребовать обновления адреса.

API ДРЕВО запускается отдельно. Для старта при входе пользователя Windows предусмотрен `scripts/register_autostart.ps1`. Запуск до входа и продолжение работы после выхода из Windows требуют отдельной настройки учётной записи/службы — один Funnel не запускает Python-сервер.

Состояние и отключение:

```powershell
tailscale status
tailscale funnel status --json
tailscale funnel --https=443 off
```

Доступ из интернета по-прежнему ограничен проверкой кода/сессии в API. Для ссылок ChatGPT дополнительно действуют права конкретного дела, подпись, срок, лимит и отзыв. Само включение Funnel не разрешает выдачу сканов без авторизации.

Funnel доступен на всех тарифах, Personal предназначен для личного использования. У Funnel статус beta и ограничения пропускной способности; скорость работы с крупными сканами нужно проверять на реальном подключении. Официальные источники: [Funnel](https://tailscale.com/docs/features/tailscale-funnel), [сохранение после перезагрузки](https://tailscale.com/docs/reference/tailscale-cli/funnel#effects-of-rebooting-and-restarting).
