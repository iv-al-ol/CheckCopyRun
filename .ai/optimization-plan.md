# План оптимизации CheckCopyRun (Вариант C, с исключениями)

## Ограничения

Не трогать (пользователь просил сохранить):

- `ui/views/stub_view.py`
- `tools/structure_creator.py`

## 1. Удаление неиспользуемых файлов

| Файл | Действие | Замена / причина |
|---|---|---|
| `utils/app_icon.py` | удалить | логика иконки переезжает в единый хелпер |
| `services/destination_snapshot.py` | удалить | 0 импортов; `scan()` нигде не вызывается |

## 2. Единый хелпер иконки окна

Сейчас три реализации: `utils/app_icon.py::apply_window_icon`, `ui/dialogs/_icon.py::apply_dialog_icon`,
`ui/app.py::MainWindow._apply_window_icon`.

План: оставить единственный источник в `ui/dialogs/_icon.py` (он уже кэширует `PhotoImage`),
`MainWindow._apply_window_icon()` заменить вызовом `apply_dialog_icon(self)`, `utils/app_icon.py` удалить.

## 3. Мёртвый код

- `ui/dialogs/_standard.py`: `show_info`, `show_warning` + экспорт в `ui/dialogs/__init__.py` и `__all__`.
- `core/models.py`: `Profile.has_exe()`.
- `services/system/autostart.py`: `get_current_command()`.
- `services/common/copy_constants.py`: `STATE_KIND_INITIAL`.
- `core/paths.py`: `is_valid_directory`, `is_valid_file` (в продакшене не вызываются).
- `services/cas/destination_state.py`: `save_after_copy`, `save_after_restore` + `tests/test_destination_state.py`
  (продакшн-код обновляет `current.json` самостоятельно; функции жили только ради тестов).
- `services/{cas,copy,restore,system,common}/__init__.py`: таблицы `_EXPORTS` + `__getattr__`/`__dir__`.
  Проверено: ни один вызывающий код не импортирует имена через пакет, только через подмодули.

## 4. Нарушения слоёв (services → ui)

### 4.1 `ensure_directory`

- Источник: `ui/views/profile/profile_paths.py:47`
- Новый дом: `core/paths.py`
- Правки импортов: `services/startup_check.py:38`, `ui/app.py:62`,
  `ui/views/profile/profile_path_controller.py:24`, `ui/views/profile/profile_process_controller.py:18`

### 4.2 `looks_like_image_path`

- Источник: `ui/components/image_utils.py:24`
- Новый дом: `core/paths.py` (вместе с кортежем расширений)
- Правки импортов: `services/system/icon_cleanup.py:21`, `ui/components/icon_picker/state.py:27`,
  `ui/components/nav_icon.py:30`, `ui/components/profile_tile.py:23`, `ui/views/profile/profile_header.py:11`

После переноса правило `services → core` соблюдается, UI-слой продолжает работать без изменений поведения.

## 5. Конфигурация и гигиена репозитория

- `.gitignore`: добавить `.pytest_cache/`; убрать легаси Flet (`.flet/`, `flet_bundle/`, `*.apk`, `*.aab`, `*.ipa`).
- `ruff.toml`: убрать `.flet` из `exclude`; `target-version` → `py312` (согласовать с `.python-version` = 3.12.10).
- `pyproject.toml`: `nuitka` из `dependencies` → `[dependency-groups].dev` (нужен только `build.py`).
- `TODO.txt` → перенести пункты в `.ai/todo.md`, корневой файл удалить (единый трекер по `.zoorules`).
- `README.md`: краткое описание, стек, запуск (`uv run main.py`), сборка (`uv run build.py`), тесты, линт.
- `.ai/system_architecture.md`: убрать `destination_snapshot`, указать новые дома перенесённых функций.

## 6. Проверка

1. `ruff check .`
2. `ruff format --check .`
3. `pytest`
4. Ручная проверка: запуск приложения, иконка главного окна и диалогов, копирование профиля
   (затрагивается `ensure_directory`), очистка иконок (`looks_like_image_path`).

## Риски

| Риск | Смягчение |
|---|---|
| Удаление реэкспортов `_EXPORTS` ломает внешний код | Проверено поиском: импортов через пакет нет |
| Перенос функций ломает импорты | Явный список правок импортов в разделе 4 |
| Удаление `save_after_*` теряет логику состояний | `copy_service` уже обновляет `current.json`; фиксируется тестами копирования |
