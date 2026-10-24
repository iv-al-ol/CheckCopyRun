# История изменений и выполненных задач (Changelog)

## 📝 Лог выполненных задач (По датам)

### 2026-10-24 — Собственный toast: автозакрытие, анимация, настройки

Отказ от нативных Windows-toast в пользу собственного окна:
WinRT не даёт ни произвольной длительности, ни управляемой
анимации, ни гарантии показа при скрытом главном окне.

**Новый виджет `ui/components/toast.py`:**

- `ToastWindow` — окно без рамки, `-topmost`, не забирает фокус.
  Появление и исчезновение — линейное изменение
  `attributes("-alpha", …)` шагами по `NOTIFY_FADE_STEP_MS`
  (`NOTIFY_FADE_IN_MS` / `NOTIFY_FADE_OUT_MS`). Резкого
  закрытия нет: `dismiss()` доводит прозрачность до нуля и
  только потом вызывает `destroy()`.
- Несколько уведомлений выстраиваются стопкой снизу вверх
  (`offset_index`), правый нижний угол рабочей области,
  размеры учитывают DPI (`get_scaling`).
- Клик по любому месту закрывает уведомление плавно.
- `ToastManager` — стек активных окон и их уборка.
- `ToastNotifier` — адаптер под протокол `Notifier`; показ
  маршалится в Tk-поток через `after(0, …)`, потому что
  вызывается из потока мониторинга.

**Настройки:**

- `AppSettings.notify_duration` (`short`/`long`) удалено —
  заменено на `notify_auto_close_sec` (секунды, `0` = не
  скрывать). Диапазон `NOTIFY_AUTO_CLOSE_MIN..MAX`
  (0..600), по умолчанию **0** — уведомление остаётся до клика.
- Миграция безопасна: `_from_dict` клампит значение,
  нечисловые данные дают `0`; старый `settings.dat` без новых
  полей загружается как раньше.
- `Notification.duration` → `Notification.auto_close_sec`.

**Зависимости:**

- `windows-toasts` убрана из `pyproject.toml`: задача решается
  средствами Tk, лишняя зависимость не нужна (§1 `.zoorules`).
  `WindowsToastNotifier` и `build_notifier` удалены,
  `build_fallback_notifier` собирает «трей → no-op» на случай
  недоступности UI-тоста.
- `MainWindow` создаёт `ToastManager` и подключает
  `ChainNotifier([ToastNotifier, fallback])`. Трей теперь
  поднимается только для режима «сворачивать в трей».

**Вкладка «Уведомления»:**

- Мастер «Включить уведомления» вынесен **над** рамкой; все
  зависимые параметры — в одной рамке с тонкой границей.
- У каждого параметра короткое пояснение (1–2 строки), в том
  числе у автозакрытия и у интервала опроса — вместо
  технического описания механизма опроса.
- Поле «Скрывать через: N сек.» с валидацией и клампингом.

**Тесты:** 427 (было 419). Добавлены проверки значений по
умолчанию, roundtrip и клампинга `notify_auto_close_sec` и
`monitor_interval_min`, roundtrip флагов уведомлений профиля,
загрузка старого `settings.dat` без новых полей,
`auto_close_sec` в `Notification` и в собранном уведомлении.

### 2026-10-24 — Уведомления об изменениях источника и `!CCRun/message.txt`

Новый фоновый мониторинг папок-источников: приложение само
сообщает, что в источнике появились изменения, без ручного
нажатия «Копировать».

**Новый пакет `services/monitor/`:**

- `source_snapshot.py` — `build_snapshot(source, max_files)` и
  `diff_snapshots(old, new)`. Только `stat` через `long_io`
  (размер + `st_mtime_ns`), без чтения содержимого и хэширования —
  опрос раз в N минут не нагружает диск. При числе файлов больше
  `MONITOR_INDEX_MAX_FILES` (5000) индекс не хранится:
  `truncated=True`, изменения оцениваются по агрегатам
  `(total_files, total_bytes, max_mtime_ns)`.
- `message_file.py` — `read_message(source)` читает
  `<source>/!CCRun/message.txt` (лимит `MESSAGE_FILE_MAX_BYTES`,
  кодировки `utf-8-sig` / `utf-8` / `cp1251`), отдаёт превью
  (`MESSAGE_PREVIEW_LINES` / `MESSAGE_PREVIEW_CHARS`) и sha256
  для дедупликации. Папка `!CCRun` уже исключена
  `is_special_first_segment`, поэтому файл не попадает в
  destination и не ломает CAS.
- `monitor_state.py` — `MonitorStore` / `MonitorEntry`. База
  снимков в `Documents/CheckCopyRun/monitor/<profile_id>.json`,
  атомарная запись (`.tmp` + `Path.replace`), `prune(keep_ids)`
  для удалённых профилей, regex-валидация `profile_id`.
- `monitor_service.py` — `MonitorService`: один daemon-поток,
  последовательный обход, `run_once()` синхронен и тестируем без
  потоков и `sleep`. Первый цикл профиля только создаёт базу
  (нет уведомления «изменилось всё»), `message.txt` показывается
  сразу. Пропуск при идущем copy/restore. Исчезнувший источник
  не трактуется как «удалено всё» (`skipped_unavailable`). После
  смены `source` база пересоздаётся без сравнения.

**Уведомления — `services/system/notifier.py`:**

- Протокол `Notifier` и каскад `ChainNotifier`:
  `WindowsToastNotifier` (нативные Windows-toast через
  необязательную `windows-toasts`, с длительностью) →
  `TrayNotifier` (balloon иконки трея) → `NullNotifier`.
  Недоступность любого звена не ломает приложение.
- Чистые функции форматирования: `format_changes_summary`,
  `format_profile_notification` (агрегация нескольких профилей
  в одно уведомление), `plural_files`, `plural_profiles`.

**Настройки и UI:**

- `AppSettings`: `notifications_enabled`, `notify_source_changes`,
  `notify_message`, `notify_aggregate`, `notify_duration`,
  `monitor_interval_min` (1..60, по умолчанию 5).
- `Profile`: `notify_on_changes`, `notify_on_message` —
  перекрывают глобальные выключатели каналов.
- `core/settings_store.py`: сериализация новых полей, миграция
  безопасна (неизвестные ключи игнорируются, интервал
  клампится, неизвестная длительность сбрасывается).
- Новая вкладка «Уведомления» (`notifications_tab.py`):
  мастер-чекбокс, два канала, агрегация, длительность, интервал
  в минутах. При выключенных уведомлениях остальные элементы
  блокируются.
- `ui/app.py`: `MonitorService` создаётся вместе с окном,
  `refresh_monitor_config()` — единая точка синхронизации
  (вызывается из `save_settings_now` и `refresh_sidebar`),
  трей поднимается как фолбэк показа. `reset_monitor_profile()`
  после успешного копирования. Монитор стартует через
  `_MONITOR_START_DELAY_MS` (2500 мс) после автопроверки, чтобы
  первый цикл не соревновался за диск.
- `ui/components/option_menu.py`: `set_enabled()` — раньше
  блокировка выпадающего списка была невозможна (это CTkFrame,
  а не виджет с `state`).

**Тесты:** 5 новых файлов (`test_source_snapshot`,
`test_message_file`, `test_monitor_state`, `test_notifier_format`,
`test_monitor_service`), 72 теста. Всего: 419 (было 347).

**Найденные при тестах дефекты (исправлены):**

- `format_changes_summary` теряла общее количество файлов в
  тексте уведомления.
- `WindowsToastNotifier` вычисляла длительность, но не применяла
  её (F841) — переписано на два пути API `windows-toasts`
  (`Toast` + `show_toast`, затем короткий конструктор).
- Пропавший источник молча выпадал из обхода из-за
  `can_copy()` в фильтре кандидатов — теперь попадает в
  `skipped_unavailable`.

`windows-toasts` добавлен в `pyproject.toml`, но на рантайме
необязателен.

### 2026-10-24 — Документирование роли пакета `utils/`

Разбор вопроса «зачем отдельный пакет из одного файла».

- `utils/__init__.py`: добавлен докстринг с обоснованием. Пакет — сквозная
  инфраструктура без домена; его импортируют все слои (`main`, `config`,
  `core`, `services`, `ui`). Перенос логгера в `core/` или `services/`
  создал бы цикл `core ↔ services` (`core/paths.py`,
  `core/settings_store.py` сами импортируют `utils.logger`) и нарушил
  инвариант `.zoorules` §4.
- `.ai/system_architecture.md`: в раздел «Слои» добавлена таблица
  сравнения `services/` и `utils/` с объяснением, почему пакет не слит
  с `core/` и не заменён одиночным модулем.

Код не менялся — правки только в документации и докстринге.

### 2026-10-24 — Этап 3: DPI и разрешения экрана

**Исправлены баги смешения логических и физических пикселей**

- `ui/dialogs/_centering.py::_target_center_for_hidden` возвращала логические
  координаты центра монитора, тогда как `_target_center_for_visible` и
  `wm_geometry` работают в физических. При DPI > 100% диалог, открытый из
  свёрнутого/скрытого в трей окна, смещался к левому верхнему углу.
  Теперь обе ветки возвращают физические пиксели.
- `ui/dialogs/backup_list.py::_position_and_size` смешивал физические
  `winfo_rootx/width` родителя с логической константой `_DIALOG_WIDTH` и
  применял результат через масштабируемый `CTkToplevel.geometry()`.
  Теперь размер масштабируется, применяется `wm_geometry`.
- `ui/components/option_menu.py::open` формировал `geometry()` из физической
  ширины (winfo) и логической высоты (`_ITEM_HEIGHT`): на 2K/150% последний
  пункт списка обрезался. Теперь всё считается в физических пикселях и
  применяется через `wm_geometry`.

**Крайние разрешения**

- `ui/window_geometry.py`: новые `get_work_area_logical()` (WinAPI
  `SystemParametersInfoW(SPI_GETWORKAREA)`) и `effective_min_size()`.
  `apply_default_geometry` центрирует окно по рабочей области (без панели
  задач) и клампит стартовый размер.
- `ui/app.py`: `minsize` берётся из `effective_min_size` — на 1366x768 при
  150% окно больше не становится неуменьшаемым.

**Сборка**

- `assets/app.manifest` — манифест с `dpiAwareness=PerMonitorV2`,
  `dpiAware=true/PM`, `longPathAware=true` и совместимостью с Windows 10/11.
- `build.py`: манифест подключён через `--windows-manifest`, добавлена его
  проверка в `_check_prerequisites`. Без манифеста Windows растягивает
  готовое окно, интерфейс мылится на HiDPI, а `ScalingTracker` видит 1.0.

**Мелочи**

- `ui/components/section_tabs.py`: фиксированный `wraplength=800` заменён на
  `WrappingLabel` с пересчётом по фактической ширине.

**Тесты**

- Новый `tests/test_window_geometry_dpi.py` — 33 теста: `parse_geometry`,
  `is_inside_virtual_screen`, `capture_geometry` (roundtrip без роста окна),
  `effective_min_size`, `apply_default_geometry`, `try_restore_geometry` на
  scaling 1.0 / 1.25 / 1.5 / 2.0.
- Всего тестов: 347 (было 314).

### 2026-10-24 — Этап 2: устранение дублирования

**Исправлен функциональный баг**
- `services/restore/restore_service.py::_populate_blobs` работал в обход
  `long_io`: `Path.is_file()` и `str(full)` не понимают префикс `\\?\`.
  На путях длиннее 260 символов блобы молча не попадали в хранилище.
  Теперь используется `to_long_path` + `long_io.isfile` + `os.path.join`,
  как в `copy_service`.

**Новые общие модули**
- `services/common/time_utils.py::now_iso` — одна реализация вместо копий
  в `cas/state_store.py` и `cas/destination_state.py`.
- `services/common/path_norm.py::norm_path` — замена трёх копий `_norm`
  в `cas/destination_state.py`, `restore/restore_apply.py`,
  `restore/restore_planner.py`.
- `services/common/worker_base.py::WorkerEventsMixin` — общие
  `_emit_done` / `_emit_error` / `_safe_schedule` для `_CopyWorker`
  и `_RestoreWorker`.
- `services/cas/state_store.py::StateStore.find_matching` — одна
  реализация поиска идентичного состояния (было две копии:
  в `copy_service` с `exclude_kinds` и в `restore_service` без него).
- `ui/components/popup_utils.py` — `get_scaling`, `make_transparent`,
  `is_inside` вместо копий в `context_menu.py` и `tooltip.py`.
- `ui/components/hover_mixin.py::HoverMixin` — общая hover-логика
  для `nav_item.py` и `profile_tile.py`.
- `services/copy/copy_service.py::format_mirror_suffix` — вместо
  двух одинаковых `_mirror_suffix` в `ui/app.py` и
  `profile_process_controller.py`.

**Производительность**
- `cas/destination_state.py::_scan_vs_state` при ошибке обхода больше не
  запускает повторный полный `walk` через `_latest_file_mtime`.

**Конфигурация**
- `pyproject.toml`: в dev-группу добавлен `pytest-cov`.
- `ruff.toml`: каталог `tools/` исключён из линта (утилита разработчика,
  в приложение не входит).

### 2026-10-24 — Этап 1: оптимизация проекта

**Удалены неиспользуемые файлы**
- `utils/app_icon.py` — логика установки иконки переехала в единый хелпер.
- `services/destination_snapshot.py` — `scan()` не вызывался ниоткуда.
- `TODO.txt` — бэклог перенесён в `.ai/todo.md` (единый трекер по правилам проекта).

**Удалён мёртвый код**
- `ui/dialogs/_standard.py`: `show_info`, `show_warning` (+ их экспорт и `__all__`).
- `core/models.py`: `Profile.has_exe()`.
- `services/system/autostart.py`: `get_current_command()`.
- `services/common/copy_constants.py`: `STATE_KIND_INITIAL`.
- `core/paths.py`: `is_valid_directory`, `is_valid_file`.
- `services/{cas,copy,restore,system,common}/__init__.py`: ленивые таблицы
  `_EXPORTS` (PEP 562) — ни один вызывающий код не использовал реэкспорты.

**Устранены нарушения слоёв (`services/` не должен импортировать `ui/`)**
- `ensure_directory` перенесена из `ui/views/profile/profile_paths.py` в
  `core/paths.py`. Импорты обновлены в `services/startup_check.py`, `ui/app.py`,
  `profile_path_controller.py`, `profile_process_controller.py`.
- `looks_like_image_path` перенесена из `ui/components/image_utils.py` в
  `core/paths.py` (вместе с `IMAGE_EXTENSIONS`). Импорты обновлены в
  `services/system/icon_cleanup.py`, `icon_picker/state.py`, `nav_icon.py`,
  `profile_tile.py`, `profile_header.py`.

**Устранено дублирование**
- Три реализации установки иконки окна сведены к одной:
  `ui/dialogs/_icon.py::apply_app_icon(window, taskbar=...)`.
  `MainWindow._apply_window_icon()` теперь вызывает её; диалоги используют
  тонкую обёртку `apply_dialog_icon`.
- Запись `current.json` вынесена в общий примитив
  `services/cas/destination_state.py::commit_current`; `copy_service` и
  `restore_service` больше не дублируют создание `CurrentData`.
  `save_after_copy` / `save_after_restore` стали рабочими точками входа:
  `save_after_copy(destination, state_name)` переводит указатель на готовое
  состояние без повторного сканирования.

**Конфигурация и документация**
- `.gitignore`: добавлены `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
  `.coverage`, `htmlcov/`; убраны легаси-строки Flet (`.flet/`, `flet_bundle/`,
  `*.apk`, `*.aab`, `*.ipa`).
- `ruff.toml`: `target-version` выровнен по `.python-version` (`py312`),
  из `exclude` убран `.flet`.
- `pyproject.toml`: `nuitka` перенесён из `dependencies` в
  `[dependency-groups].dev` — он нужен только для `build.py`.
- `README.md` заполнен: описание, стек, запуск, сборка, тесты, расположение
  данных, структура проекта.
- `.ai/system_architecture.md`: убран `destination_snapshot`, описаны
  `commit_current` / `save_after_*` и новые дома `ensure_directory` и
  `looks_like_image_path`.

**Проверка:** `pytest` — 314 тестов пройдено (до и после изменений).
