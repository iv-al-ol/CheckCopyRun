# Архитектура и видение проекта CheckCopyRun

## 🏛️ Общее описание (Product Vision)

**CheckCopyRun** — десктопное приложение для Windows (Python 3.12+,
CustomTkinter), которое автоматизирует процесс «проверить папку с
приложением → скопировать изменения в рабочую копию → запустить
приложение».

Целевая аудитория — разработчики и пользователи, которым нужно
регулярно синхронизировать папку с приложением (например, `build/`
после компиляции) в рабочую директорию и запускать оттуда. Профили
позволяют держать несколько независимых пар source→destination с
разными настройками.

Главная проблема, которую решает приложение: **безопасное
копирование с возможностью отмены и восстановления к прошлым
версиям**, без дублирования файлов и без риска потерять данные при
ошибке выбора папки (mirror-режим).

Ключевые принципы:
- **Безопасность**: любое деструктивное действие (copy с заменой,
  restore, mirror-удаление) предваряется снимком состояния.
- **Эффективность**: хранение версий через CAS — один blob на
  уникальный контент, сколько бы раз он ни встречался.
- **Прозрачность**: пользователь всегда видит, какая версия
  файлов сейчас в destination (метка «Текущая версия от …»),
  и понимает, что произойдёт при следующих действиях.
- **Не мешать**: автопроверка при старте не должна ломать
  восстановленные из бэкапа состояния.

## 🛠️ Ключевой функционал (Core Features)

### Основное
- **Профили копирования**: несколько независимых source→destination
  с опциями (резервирование, mirror, автозапуск exe, автопроверка
  при старте).
- **Копирование с инкрементальной проверкой**: сравнение по
  `(size, mtime_ns, sha256)` с кэшем хэшей в `hashes.json`.
- **CAS-хранилище версий**: содержимое файлов хранится один раз по
  sha256 (`!CCRun/blobs/<ab>/<sha256>`), состояния — как JSON-списки
  файлов с хэшами (`!CCRun/states/state_*.json`).
- **Восстановление (restore)**: перевод destination в любое
  сохранённое состояние. Перед restore создаётся «точка возврата»
  (`restore_point`).
- **Откат (rollback)**: автоматический возврат destination к
  состоянию «до отменённой операции» при нажатии «Отмена»
  во время copy/restore.
- **Режим зеркала (mirror)**: удаление из destination файлов и
  папок, которых нет в source. Всегда создаёт states (даже если
  `create_backup=False`) — иначе потери безвозвратны.
- **Автопроверка при запуске**: для профилей с
  `check_on_startup=True` копирование выполняется в фоне при старте
  приложения. **Пропускается для профилей, восстановленных из
  бэкапа** (`current.last_action == "restore"`), если в настройках
  не включено `run_autocheck_on_restored`.
- **Запуск .exe** после успешного копирования.
- **Кэш хэшей** (`hashes.json`): повторные копирования не читают
  содержимое неизменившихся файлов.
- **Метка текущей версии** под формой профиля: показывает, от какой
  даты состояние, было ли восстановление из бэкапа, были ли ручные
  правки.

### Дополнительно
- **Множественное выделение профилей** в сайдбаре (Ctrl/Shift/рамка),
  массовое удаление через ПКМ.
- **Политика очистки состояний** (keep_last_n / delete_older_days) +
  GC blob-ов, на которые больше нет ссылок.
- **Настройки** (тема, кэш хэшей, подтверждение выхода, автопроверка
  восстановленных) — `settings.dat`, зашифрованный через DPAPI.
- **Тёмная / светлая / системная тема**.

## 🏗️ Архитектура

### Слои

```
main.py → ui.app.MainWindow
            ├── config/           константы, версия, UI-размеры
            ├── core/             модели, пути, settings_store, long_io
            ├── services/         вся бизнес-логика (не знает про Tk)
            ├── ui/               CTk-слой: layouts, components, views, dialogs
            └── utils/            сквозная инфраструктура (логирование)
```

**Инвариант**: `services/` не импортирует `tkinter` / `customtkinter`.
UI получает события через колбэки + `scheduler` (обычно
`self.after(0, fn)`).

#### Почему `utils/` — отдельный пакет, а не часть `core/` или `services/`

| | `services/` | `utils/` |
|---|---|---|
| Назначение | бизнес-логика: CAS, копирование, restore, системные интеграции | инфраструктура без домена |
| Знает о домене | да (`Profile`, состояния, blob-ы) | нет |
| Кто импортирует | `ui/` (через `MainWindow`) | все слои: `main`, `config`, `core`, `services`, `ui` |
| Ограничения слоёв | нельзя `ui.*`, `tkinter` | нет — самый нижний слой |

Сейчас в `utils/` один модуль — `logger.py`, но его импортируют
почти все модули проекта. Пакет отделён намеренно:

- **Не внутри `core/`**: `core/paths.py` и `core/settings_store.py`
  сами импортируют `utils.logger`. Перенос логгера в `core/` или
  `services/` создал бы цикл `core ↔ services` и нарушил инвариант
  из `.zoorules` §4.
- **Не один модуль в корне**: пакет честно обозначает роль
  «доменно-нейтральная инфраструктура» и оставляет место для
  будущих помощников (форматирование, замеры времени), которым
  нельзя жить в `services/`.

### Ключевые модули

Пакет `services/` разбит на подпакеты: `cas`, `common`, `copy`,
`restore`, `system`. Их `__init__.py` используют ленивые
реэкспорты (PEP 562), поэтому импорт одного модуля не тянет
весь подпакет и циклы `core ↔ services` невозможны.

**CAS / состояния (`services/cas/`):**
- `services/cas/blob_store.py` — `BlobStore`. Хранение уникальных
  контентов по sha256. `put`, `get`, `has`, `gc`.
- `services/cas/state_store.py` — `StateStore`. Создание/чтение/список
  `state_*.json`. `StateData` (полный список файлов + `empty_dirs` +
  summary), `StateInfo` (обёртка для UI).
- `services/cas/state_scanner.py` — `scan_destination(destination,
  hash_cache, file_list, on_progress) -> StateData`.
- `services/cas/current_pointer.py` — `CurrentPointer` → `current.json`
  (`state`, `last_action`, `last_action_at`, `restored_from`).
  `last_action` ∈ `copy | restore | rollback | initial`.
- `services/cas/backup_registry.py` — реестр состояний для UI.
- `services/cas/backup_cleanup.py` — политика + GC blob-ов.
- `services/cas/destination_state.py` — метка «Текущая версия от …»
  (учитывает `last_action` и ручные правки через per-file mtime).
  Здесь же единый примитив записи указателя: `commit_current`,
  а также `save_after_copy` / `save_after_restore` — их используют
  `copy_service` и `restore_service`, чтобы не дублировать запись
  `current.json`. `last_action ∈ copy | restore | rollback`.

**Общее (`services/common/`):**
- `services/common/copy_constants.py` — имена служебных папок,
  версии форматов, `is_special_first_segment`.
- `services/common/copy_errors.py` — `CopyError`,
  `CopyValidationError`.
- `services/common/hash_cache.py` — `HashCache`, `hash_file`.

**Копирование и восстановление:**
- `services/copy/copy_service.py` — `CopyService` / `_CopyWorker`. Фазы
  прогресса: `copy` (файлы), `save_scan` (сканирование destination),
  `save_store` (сохранение новых blob-ов). При отмене — автооткат
  через `apply_plan`.
- `services/copy/file_compare.py` — `files_identical` с эвристикой
  «size + mtime_ns + кэш».
- `services/copy/mirror_check.py` — `scan_mirror_diff` (pre-scan, диалог
  «удаляется > 50%»), `is_reparse_point`.
- `services/restore/restore_service.py` — `RestoreService` /
  `_RestoreWorker`. Перед restore создаёт `restore_point`
  **с дедупликацией**: переиспользует `current.state` или любой
  существующий state с идентичным содержимым; только если такого
  нет — создаёт новый.
- `services/restore/restore_planner.py` — `build_plan(target, current,
  blobs) -> RestorePlan` (`to_restore`, `to_delete_files`,
  `create_dirs`, `needed_dirs`, `missing_blobs`, `skipped_files`).
- `services/restore/restore_apply.py` — `apply_plan(plan, target,
  destination, on_progress, cancel_event) -> ApplyResult`.
  Единый механизм для restore и rollback.
- `services/restore/disk_space.py` — быстрая оценка по stat.

**Мониторинг источника (`services/monitor/`):**
- `services/monitor/source_snapshot.py` — `build_snapshot(source,
  max_files)` (только `stat` через `long_io`, без чтения содержимого
  и хэширования) и `diff_snapshots(old, new) -> SnapshotDiff`
  (`added`, `modified`, `removed`). При числе файлов больше
  `MONITOR_INDEX_MAX_FILES` посуточный индекс не хранится:
  `truncated=True`, изменения оцениваются по агрегатам
  `(total_files, total_bytes, max_mtime_ns)`.
- `services/monitor/message_file.py` — `read_message(source)` →
  `SourceMessage` (`text`, `preview`, `sha256`, `truncated`).
  Читает `<source>/!CCRun/message.txt` с лимитом
  `MESSAGE_FILE_MAX_BYTES`, перебирает кодировки
  (`utf-8-sig`, `utf-8`, `cp1251`), обрезает превью по
  `MESSAGE_PREVIEW_LINES` / `MESSAGE_PREVIEW_CHARS`. sha256 —
  для дедупликации: одно сообщение не показывается дважды.
- `services/monitor/monitor_state.py` — `MonitorStore` /
  `MonitorEntry`. База снимков и хэша сообщения в
  `Documents/CheckCopyRun/monitor/<profile_id>.json`,
  атомарная запись (`.tmp` + `Path.replace`), `prune(keep_ids)`.
  `profile_id` валидируется regex — защита от подстановки в имя
  файла.
- `services/monitor/monitor_service.py` — `MonitorService`.
  Один daemon-поток `SourceMonitor`, профили обходятся
  последовательно. `run_once()` синхронен и тестируем без
  потоков и `sleep`. Первый цикл профиля только создаёт базу
  (иначе уведомление «изменилось всё»), сообщение из
  `message.txt` показывается сразу. Пропускает профиль, если
  идёт copy/restore или источник недоступен (исчезнувший
  источник не трактуется как «удалено всё»). После смены
  `source` база пересоздаётся без сравнения.

**Вспомогательное:**
- `services/startup_check.py` — `StartupCheckQueue`,
  `select_startup_candidates(profiles, run_on_restored)`,
  `_is_restored(destination)`.
- `services/selection_model.py` — выделение профилей в UI.
- `core/long_io.py` — обёртки I/O с `\\?\` для длинных путей.
- `core/paths.py` — помимо путей и валидации: `ensure_directory`
  (создание директории, используется и сервисами, и UI) и
  `looks_like_image_path` (проверка «похоже на картинку»).
  Эти функции специально живут в `core`, чтобы `services/` не
  импортировал `ui/`.

**Системное (`services/system/`):**
- `services/system/autostart.py` — автозапуск через реестр (HKCU).
- `services/system/dpapi.py` — обёртка `CryptProtectData/UnprotectData`.
- `services/system/icon_extractor.py` — извлечение иконки из `.exe`
  (PrivateExtractIconsW + ExtractIconExW).
- `services/system/icon_cleanup.py` — очистка PNG, на которые не ссылается
  ни один профиль.
- `services/system/launcher.py` — `launch_exe` через `subprocess.Popen`.
- `services/system/tray.py`, `services/system/tray_manager.py` — иконка
  в системном трее.
- `services/system/notifier.py` — протокол `Notifier` и
  сервисные провайдеры: `TrayNotifier` (balloon иконки трея) и
  `NullNotifier` (тихий no-op), сборка `build_fallback_notifier`.
  Здесь же чистые функции форматирования:
  `format_changes_summary`, `format_profile_notification`,
  `plural_files`, `plural_profiles`. Показ идёт из потока
  монитора, поэтому провайдеры обязаны быть потокобезопасными.
  Основной способ показа — UI-тост, см. ниже.
- `ui/components/toast.py` — собственное всплывающее
  уведомление: `ToastWindow` (окно без рамки, `-topmost`, не
  забирает фокус, плавные появление/исчезновение через
  `attributes("-alpha", …)`, автозакрытие по
  `Notification.auto_close_sec`, `0` — до клика), `ToastManager`
  (стопка окон снизу вверх, DPI-осведомлённое
  позиционирование) и `ToastNotifier` (адаптер под `Notifier`,
  маршалит показ в Tk-поток через `after(0, …)`). Нативные
  Windows-toast не используются: WinRT не даёт произвольной
  длительности и управляемой анимации.

**UI:**
- `ui/app.py` — `MainWindow`. Оркестратор: роутер, статус-бар,
  `CopyService`/`RestoreService`, `StartupCheckQueue`,
  `MonitorService`, `ProfileActionController`, контекстные меню.
  `refresh_monitor_config()` — единственная точка синхронизации
  настроек со монитором: вызывается из `save_settings_now()` и
  `refresh_sidebar()`, стартует/останавливает поток по
  `notifications_enabled` и поднимает трей как фолбэк уведомлений.
  `reset_monitor_profile(pid)` вызывается после успешного
  копирования, чтобы скопированное не считалось «новостью».
- `ui/layouts/sidebar.py` — `Sidebar`. Список профилей + выделение
  (Ctrl/Shift/рамка). Клик вне списка сбрасывает выделение.
- `ui/views/profile/profile_view.py` — `ProfileView`. Метка версии
  считается в фоне (`threading.Thread`, `_label_gen` для защиты
  от гонок).
- `ui/dialogs/backup_list.py` — «Резервные копии». Формат строки:
  `Дата · [Текущий | Точка возврата] / В проекте: N файлов, M папок
  (размер) · Сохранены изменения: X файлов (Y)`. Кнопка
  «Восстановить» — синяя (primary). Удаление текущего запрещено.
- `ui/components/context_menu.py` — контекстное меню. Закрывается
  по ЛКМ/ПКМ вне окна (bind `after_idle` для Button-3, чтобы не
  закрывать меню тем же кликом, что его открыл).
- `ui/components/tooltip.py` — safety-polling каждые 200 мс вместо
  таймаута.

## 📁 Данные и файловая структура

### Documents
```
%USERPROFILE%\Documents\CheckCopyRun\
    settings.dat     # настройки, DPAPI
    log\app.log      # лог с ротацией
    icons\exe_*.png  # PNG-иконки, извлечённые из exe профилей
    monitor\<profile_id>.json  # база снимков источника для уведомлений
```

### Destination каждого профиля
```
<destination>\
    !CCRun\
        blobs\<ab>\<sha256>    # CAS: уникальные контенты
        states\state_*.json    # JSON-снимки состояний
        hashes.json            # кэш хэшей (ускоряет повторные копирования)
        current.json           # указатель на текущее состояние
    <пользовательские файлы>
```

`!Backup_*` — **устаревший формат до CAS**. Не используется, не
удаляется, не сканируется. В коде `is_special_first_segment`
пропускает и `!CCRun`, и `!Backup_*`.

## 🔑 Ключевые понятия и инварианты

**State** — полный список файлов + пустых папок destination на
конкретный момент, с хэшами. Два state с идентичным набором
`(path → sha256)` и `empty_dirs` — эквивалентны (дедупликация).

**Blob** — уникальный контент файла (по sha256). Хранится один раз.

**Текущий (state)** — state, на который указывает `current.state`.
Удаление запрещено (в UI кнопка disabled).

**Точка возврата** (`restore_point`) — состояние, созданное (или
переиспользованное) перед restore. При отмене restore — откат
через неё.

**Restore vs Rollback**:
- **Restore** — пользователь осознанно выбрал версию X из списка.
  `last_action="restore"`.
- **Rollback** — система автоматически вернула состояние после
  отмены copy/restore. `last_action="rollback"`.

**Mirror + Backup**: mirror **всегда** создаёт states (даже при
`create_backup=False`), иначе потери безвозвратны. `CopyService.start`
принудительно включает `create_state = create_backup or mirror_mode`.

**Auto-check + Restore**: профили с `current.last_action == "restore"`
пропускаются при автопроверке (защита восстановленных файлов),
если в настройках `run_autocheck_on_restored = False`. Ручное
копирование всегда работает.

**Длинные пути**: файловые операции идут через `core.long_io`
(с `\\?\` при длине ≥ 248). `explorer` и `subprocess` — без
префикса (не понимают). `filedialog` не может выбирать длинный
корень — это ограничение ОС, не наше. Поддержка нужна для
файлов **внутри** дерева (например, `node_modules`).

**Метки «Текущая версия»** (в порядке приоритета):
1. Ручная правка → `Текущая версия от <mtime> — изменено вручную`
   (или `… после восстановления из бэкапа`, `… после отката`).
2. Restore → `Текущая версия от <created_at> — восстановлено из бэкапа`.
3. Rollback → `Текущая версия от <created_at> — откат после отмены`.
4. Copy → `Текущая версия от <last_action_at>`.
5. Пусто → `Папка пуста` / `Версия не определена`.

## 🧰 Технологии и зависимости

- **Python 3.12+**, `customtkinter`, `Pillow`, `nuitka`, `pystray`,
  `pywin32`, `pytest` (dev).
- **Сборка** — `build.py` через Nuitka: `--standalone` (папка
  `build/CCRun.dist/`) или `--onefile` (единый `CCRun.exe`).
  Метаданные exe (`CompanyName`, `ProductName`, `FileVersion`)
  читаются из `config/constants.py`.

## 📝 Правила именования

| Контекст | Значение |
|---|---|
| UI-тексты | `CheckCopyRun` |
| Заголовок окна | `Check, Copy & Run` |
| Имя .exe / папки сборки | `CCRun` |
| Служебная папка в destination | `!CCRun` (не путать с exe) |
| package в `pyproject.toml` | `checkcopyrun` |

## 🎯 Рекомендации для ИИ-агента

- **Не менять `services/` без понимания CAS-инвариантов**:
  state = полный список, blob = уникальный контент, `current.json`
  = указатель на «где мы сейчас».
- **Не ломать `last_action`**: `copy | restore | rollback | initial`
  — на нём построены метки UI, автопроверка, дедупликация
  restore_point.
- **Тесты** — запускать полностью (`pytest tests/ -q`). Тесты
  CAS-логики чувствительны к пошаговым изменениям.
- **UI и сервисы разделены**: правки UI не должны тянуть Tk
  в `services/`. События — через `scheduler` (`self.after(0, …)`)
  и колбэки.
- **Прогресс копирования** имеет фазы (`copy` / `save_scan` /
  `save_store`). Не объединять — пользователь должен видеть
  «сканирование» отдельно от «сохранения».
- **Формат метки версии** — фиксирован. Если меняете — согласуйте
  с пользователем: он единый для всех сценариев и читается в UI
  как `<основное> — <уточнение>` без скобок.
- **`explorer` не понимает `\\?\`**: если пользователь на длинном
  пути нажмёт «Открыть папку» — не откроется. Это ограничение ОС,
  не баг.
- **Перед изменением `services/copy_service.py` или
  `restore_service.py`** — прогонять `pytest tests/ -q`, потому
  что там завязано много сценариев (rollback, mirror, cancel,
  дедупликация).
