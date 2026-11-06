# GitHub Pages, приватный GitHub и Cloudflare

Локальный архив работает без этих сервисов. Постоянное внешнее подключение не настроено: серверный GitHub token и домен Cloudflare не предоставлены. Выполнен отдельный реальный тест Quick Tunnel на технических изображениях; результаты и ограничение веб-инструмента ChatGPT приведены в STATUS.md. Секреты задавайте только в локальном `.env`.

## Два разных репозитория

Создайте **Public `DREVO`** только для исходников и интерфейса. Проверьте `.gitignore`: `.local`, `.env`, картинки, ZIP, БД, кэши и логи не должны попасть в Git. `research-template/` содержит только пустую структуру и JSON Schema, без персональных данных.

Создайте отдельно **Private `DREVO-Research-Data`**, ветка `main`, и скопируйте в него содержимое `research-template/`. Не вкладывайте рабочий приватный репозиторий в публичный; сервер читает его через API, локальный clone не требуется.

Создайте fine-grained personal access token с доступом **только к DREVO-Research-Data**, Contents: Read and write и Metadata: Read. Это минимум для используемого Contents API; запись файлов передаёт Base64 и SHA существующей версии. Токен не нужен frontend или GitHub Pages. [GitHub Contents API](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#create-or-update-file-contents).

```dotenv
DREVO_GITHUB_REPO="YOUR_NAME/DREVO-Research-Data"
DREVO_GITHUB_TOKEN="задайте_локально"
DREVO_GITHUB_BRANCH="main"
DREVO_SYNC_SECONDS=60
```

Перезапустите сервер/worker. В «ChatGPT и GitHub» выполните ручную синхронизацию и проверьте появление manifest.json, каталога и квитанций. Worker откажется работать с public репозиторием. Встроенные mock-тесты не подтверждают реальное подключение.

## Cloudflare: тестовый HTTPS

Установите `cloudflared` из официальной поставки. Для временного теста:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Quick Tunnel выдаёт временный trycloudflare.com адрес без домена, предназначен для разработки; адрес меняется после нового запуска. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

Укажите выданный адрес как `DREVO_PUBLIC_API_URL`, без завершающего слеша; перезапустите API. Не устанавливайте интерактивный Cloudflare Access challenge на `/ai/images/*`, если веб-инструмент ChatGPT не способен пройти его: доступ к этому маршруту уже ограничен подписанными разрешениями. Остальные API по-прежнему требуют отдельную пользовательскую сессию. Не выключайте проверки приложения.

Для CDN задайте bypass cache для `/api/*` и `/ai/*`. Не включайте Cache Everything для этих маршрутов. Приложение отправляет no-store и no-referrer. Не подключайте аналитические сервисы, записывающие query string подписанных ссылок. Входящие порты роутера не открываются.

## Постоянный домен и служба Windows

Для постоянного адреса нужен настроенный Cloudflare Tunnel и собственный hostname. Домен автоматически не покупается. Используйте официальный Windows service workflow: скачанный cloudflared помещается в `C:\Cloudflared\bin`, создаётся tunnel и конфигурация с tunnel UUID, credentials-file, ingress на `http://127.0.0.1:8000` и завершающим `http_status:404`; credentials и config для SYSTEM помещаются в `%WINDIR%\System32\config\systemprofile\.cloudflared`. Служба устанавливается командой `cloudflared.exe service install` в административном терминале, ImagePath указывает на выбранный config и `tunnel run`. Точный порядок и пути приведены в [официальном руководстве службы Windows](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/windows/).

Используйте пример `scripts/cloudflared.example.yml` с вашими UUID и hostname. Не коммитьте credentials. Задайте восстановление службы при сбое в Windows Services, проверяйте состояние Cloudflared и подключение в панели Cloudflare. `scripts/check_health.ps1` проверяет локальный API, БД и наличие процесса; наличие процесса само по себе не доказывает внешний доступ.

## Публикация интерфейса

В настройках Public DREVO добавьте Actions repository variable `VITE_API_URL=https://ваш-api-домен`. Это адрес, не секрет. Settings → Pages → Source: GitHub Actions. Workflow `.github/workflows/pages.yml` собирает только `frontend/dist` с base `/DREVO/` и публикует артефакт; без HTTPS API сборка публикации остановится. [Vite: GitHub Pages](https://vite.dev/guide/static-deploy.html#github-pages).

На сервере задайте `DREVO_FRONTEND_ORIGIN=https://YOUR_NAME.github.io` (только origin, **без `/DREVO/`**), `DREVO_PUBLIC_API_URL=https://ваш-api-домен`, перезапустите API. Откройте опубликованный сайт, войдите кодом. Токен остаётся в оперативной памяти, при обновлении страницы войдите заново. Снимите stale local build VITE_API_URL перед локальной разработкой либо задайте `.env.local` во frontend; корневой `.env` не копируется в frontend.

## Разрешение выдачи выбранных сканов

До первой AI-ссылки проверьте права и условия использования архивных копий. В конкретном деле откройте «Источник → Правила выдачи копий», выберите signed_links_allowed и подтвердите проверку прав. Все остальные дела остаются private_only. Даже public_allowed в текущей версии не создаёт постоянный публичный листинг — выдача остаётся подписанной. Лимиты: до 20 страниц в запросе, 300 новых сообщений/час, до 100 чтений каждой ссылки, TTL 30 минут по умолчанию. Массовый отзыв есть на странице интеграции.
