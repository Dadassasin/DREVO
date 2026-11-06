# Размещение интерфейса на Vercel

На Vercel загружается только каталог `frontend/`: исходники интерфейса и настройки сборки. API, SQLite, сканы, семейные карточки и серверные секреты остаются на домашнем Windows-компьютере.

Рабочий production-адрес: **https://drevo-beta.vercel.app**. Проект `drevo` в личной Hobby-команде развёрнут через CLI. Проверены HTTP 200 интерфейса и ресурсов, CORS для точного production-origin, вход, защищённый каталог и изображение; без сессии — 401.

Для личного некоммерческого проекта доступен бесплатный Hobby. Публикация через Vercel CLI не использует GitHub Actions. Официальные источники: [Hobby](https://vercel.com/docs/plans/hobby), [CLI deployment](https://vercel.com/docs/cli/deploying-from-cli).

## Настройки

- Framework: Vite.
- Root Directory при импорте репозитория: `frontend`.
- Install Command: `npm ci`.
- Build Command: `npm run build`.
- Output Directory: `dist`.
- Build environment: `VITE_API_URL` — внешний HTTPS-адрес домашнего API, `PAGES_BASE=/`.
- После получения постоянного production-адреса Vercel задайте его origin в серверном `DREVO_FRONTEND_ORIGIN`, затем перезапустите API.

CLI-развёртывание выполняется из `frontend/`. Сохранённые production-переменные VITE_API_URL и PAGES_BASE используются при повторной публикации. `vercel deploy --prod` повторно публикует проект после входа и привязки локального каталога. Если импортируете GitHub-репозиторий через интерфейс Vercel, укажите Root Directory `frontend`; не меняйте этот параметр для текущего CLI-проекта без согласования структуры загрузки.

Связать текущий проект с GitHub автоматически пока не удалось: Vercel отказал в подключении репозитория. Публикация через CLI работает самостоятельно; push в GitHub пока не запускает Vercel-сборку. Для автоматических обновлений нужно отдельно подключить репозиторий в Vercel → Project Settings → Git и настроить каталог сборки.

`frontend/.vercelignore` разрешает загрузку только исходников и файлов сборки. `.vercel/` и локальные переменные исключены из Git. Код доступа, GitHub token и signing key никогда не задаются в Vercel environment или frontend.

Стабильный адрес интерфейса Vercel не делает временный Quick Tunnel постоянным. При смене адреса API требуется обновить VITE_API_URL и выполнить новое развёртывание. Для постоянного API нужен настроенный named Cloudflare Tunnel/hostname. Архив доступен только при работающем домашнем сервере.
