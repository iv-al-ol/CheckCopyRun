# История изменений и выполненных задач (Changelog)

## 📝 Лог выполненных задач (По датам)

### 2026-10-24 — Оптимизация проекта

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
