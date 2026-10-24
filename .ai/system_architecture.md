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
            └── utils/            logger, app_icon
```

**Инвариант**: `services/` не импортирует `tkinter` / `customtkinter`.
UI получает события через колбэки + `scheduler` (обычно
`self.after(0, fn)`).

### Ключевые модули

**CAS / состояния:**
- `services/blob_store.py` — `BlobStore`. Хранение уникальных
  контентов по sha256. `put`, `get`, `has`, `gc`.
- `services/state_store.py` — `StateStore`. Создание/чтение/список
  `state_*.json`. `StateData` (полный список файлов + `empty_dirs` +
  summary), `StateInfo` (обёртка для UI).
- `services/state_scanner.py` — `scan_destination(destination,
  hash_cache, file_list, on_progress) -> StateData`.
- `services/current_pointer.py` — `CurrentPointer` → `current.json`
  (`state`, `last_action`, `last_action_at`, `restored_from`).
  `last_action` ∈ `copy | restore | rollback | initial`.

**Копирование и восстановление:**
- `services/copy_service.py` — `CopyService` / `_CopyWorker`. Фазы
  прогресса: `copy` (файлы), `save_scan` (сканирование destination),
  `save_store` (сохранение новых blob-ов). При отмене — автооткат
  через `apply_plan`.
- `services/restore_service.py` — `RestoreService` / `_RestoreWorker`.
  Перед restore создаёт `restore_point` **с дедупликацией**:
  переиспользует `current.state` или любой существующий state с
  идентичным содержимым; только если такого нет — создаёт новый.
- `services/restore_planner.py` — `build_plan(target, current,
  blobs) -> RestorePlan` (`to_restore`, `to_delete_files`,
  `create_dirs`, `needed_dirs`, `missing_blobs`, `skipped_files`).
- `services/restore_apply.py` — `apply_plan(plan, target,
  destination, on_progress, cancel_event) -> ApplyResult`.
  Единый механизм для restore и rollback.
- `services/file_compare.py` — `files_identical` с эвристикой
  «size + mtime_ns + кэш».
- `services/hash_cache.py` — `HashCache`, `hash_file`.

**Вспомогательное:**
- `services/mirror_check.py` — `scan_mirror_diff` (pre-scan, диалог
  «удаляется > 50%»), `is_reparse_point`.
- `services/disk_space.py` — быстрая оценка по stat.
- `services/backup_registry.py` — реестр состояний для UI.
- `services/backup_cleanup.py` — политика + GC blob-ов.
- `services/destination_state.py` — метка «Текущая версия от …»
  (учитывает `last_action` и ручные правки через per-file mtime).
- `services/startup_check.py` — `StartupCheckQueue`,
  `select_startup_candidates(profiles, run_on_restored)`,
  `_is_restored(destination)`.
- `services/long_io.py` — обёртки I/O с `\\?\` для длинных путей.

**Системное:**
- `services/dpapi.py` — обёртка `CryptProtectData/UnprotectData`.
- `services/icon_extractor.py` — извлечение иконки из `.exe`
  (PrivateExtractIconsW + ExtractIconExW).
- `services/icon_cleanup.py` — очистка PNG, на которые не ссылается
  ни один профиль.
- `services/launcher.py` — `launch_exe` через `subprocess.Popen`.

**UI:**
- `ui/app.py` — `MainWindow`. Оркестратор: роутер, статус-бар,
  `CopyService`/`RestoreService`, `StartupCheckQueue`,
  `ProfileActionController`, контекстные меню.
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
