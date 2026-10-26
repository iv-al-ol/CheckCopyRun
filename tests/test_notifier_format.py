"""Тесты форматирования уведомлений и цепочки провайдеров."""

from __future__ import annotations

from services.system.notifier import (
    ChainNotifier,
    Notification,
    NullNotifier,
    ProfileDigest,
    format_changes_summary,
    format_profile_notification,
    format_split_summary,
    plural_files,
    plural_profiles,
)


def test_notification_default_auto_close_is_zero():
    """По умолчанию уведомление не исчезает само."""
    assert Notification("t", "b").auto_close_sec == 0


def test_notification_default_open_path_is_empty():
    """По умолчанию кнопки «Открыть» нет."""
    assert Notification("t", "b").open_path == ""

# --- Склонения ---

def test_plural_files():
    assert plural_files(1) == "файл"
    assert plural_files(2) == "файла"
    assert plural_files(5) == "файлов"
    assert plural_files(11) == "файлов"
    assert plural_files(21) == "файл"
    assert plural_files(22) == "файла"
    assert plural_files(25) == "файлов"


def test_plural_profiles():
    assert plural_profiles(1) == "профиль"
    assert plural_profiles(3) == "профиля"
    assert plural_profiles(7) == "профилей"
    assert plural_profiles(11) == "профилей"


# --- Сводка изменений ---

def test_summary_all_kinds():
    text = format_changes_summary(2, 1, 3)
    assert text == "добавлено 2, изменено 1, удалено 3"


def test_summary_skips_zeros():
    assert format_changes_summary(0, 0, 1) == "удалено 1"
    assert format_changes_summary(5, 0, 0) == "добавлено 5"
    assert format_changes_summary(0, 4, 0) == "изменено 4"


def test_summary_empty():
    assert format_changes_summary(0, 0, 0) == ""


# --- Одно уведомление ---

def test_single_profile_changes_only():
    digest = ProfileDigest(
        profile_name="Профиль A", added=3, modified=1,
    )

    notification = format_profile_notification(
        [digest], aggregate=True,
    )

    assert notification is not None
    assert notification.title.startswith("CheckCopyRun")
    assert "Профиль A" in notification.title
    # Формат: "Добавлено: N\nИзменено: N" без суммирования.
    assert "Добавлено: 3" in notification.body
    assert "Изменено: 1" in notification.body
    assert "Удалено:" not in notification.body
    # Изменения файлов, без сообщения — «Открыть» нечего.
    assert notification.open_path == ""


def test_single_profile_only_removed():
    """Тот самый случай из скриншота: только удаление.
    Никакого «Удалено 2 — 2 файла», только «Удалено: 2»."""
    digest = ProfileDigest(
        profile_name="Профиль 1: Mirror", removed=2,
    )

    notification = format_profile_notification([digest])

    assert notification is not None
    assert notification.body == "Удалено: 2"
    assert "—" not in notification.body


def test_single_profile_message_only():
    digest = ProfileDigest(
        profile_name="Профиль A", message_preview="Готово",
    )

    notification = format_profile_notification([digest])

    assert notification is not None
    assert "Сообщение: Готово" in notification.body


def test_single_profile_truncated_message():
    digest = ProfileDigest(
        profile_name="A",
        message_preview="Текст",
        message_truncated=True,
    )

    notification = format_profile_notification([digest])

    assert notification is not None
    assert "сообщение обрезано" in notification.body


def test_no_digests_no_notification():
    assert format_profile_notification([]) is None


def test_empty_digest_no_notification():
    digest = ProfileDigest(profile_name="A")
    assert format_profile_notification([digest]) is None


# --- open_path ---

def test_single_notification_with_message_sets_open_path():
    digest = ProfileDigest(
        profile_name="A",
        message_preview="Готово",
        message_file_path="C:/src/!CCRun/message.txt",
    )

    notification = format_profile_notification([digest])

    assert notification is not None
    assert notification.open_path == "C:/src/!CCRun/message.txt"


def test_single_notification_message_without_path_no_open():
    """Сообщение есть, но путь не задан — кнопки «Открыть» нет."""
    digest = ProfileDigest(
        profile_name="A",
        message_preview="Готово",
        # message_file_path не заполнен
    )

    notification = format_profile_notification([digest])

    assert notification is not None
    assert notification.open_path == ""


def test_single_notification_changes_and_message_sets_open_path():
    digest = ProfileDigest(
        profile_name="A",
        added=1,
        message_preview="Готово",
        message_file_path="C:/src/!CCRun/message.txt",
    )

    notification = format_profile_notification([digest])

    assert notification is not None
    assert notification.open_path == "C:/src/!CCRun/message.txt"


# --- Агрегация ---

def test_aggregation_title_no_number():
    """В заголовке нет числа и падежа — только «в профилях»."""
    from config.constants import APP_NAME

    digests = [
        ProfileDigest(profile_name="A", added=1),
        ProfileDigest(profile_name="B", message_preview="hi"),
    ]

    notification = format_profile_notification(
        digests, aggregate=True,
    )

    assert notification is not None
    assert notification.title == (
        f"{APP_NAME}: Обновления в профилях"
    )
    assert not any(ch.isdigit() for ch in notification.title)


def test_aggregation_lists_profiles():
    digests = [
        ProfileDigest(profile_name="A", added=1),
        ProfileDigest(profile_name="B", message_preview="hi"),
    ]

    notification = format_profile_notification(
        digests, aggregate=True,
    )

    assert notification is not None
    assert "• A — добавлено 1" in notification.body
    assert "• B — есть сообщение" in notification.body


def test_aggregation_no_open_path():
    """Агрегат — про несколько профилей, «Открыть» не ведёт
    к одному файлу."""
    digests = [
        ProfileDigest(
            profile_name="A",
            message_preview="x",
            message_file_path="/a/message.txt",
        ),
        ProfileDigest(
            profile_name="B",
            message_preview="y",
            message_file_path="/b/message.txt",
        ),
    ]

    notification = format_profile_notification(
        digests, aggregate=True,
    )

    assert notification is not None
    assert notification.open_path == ""


def test_aggregation_disabled_returns_first():
    digests = [
        ProfileDigest(profile_name="A", added=1),
        ProfileDigest(profile_name="B", added=2),
    ]

    notification = format_profile_notification(
        digests, aggregate=False,
    )

    assert notification is not None
    assert "A" in notification.title
    assert "B" not in notification.title


def test_aggregation_limits_items():
    digests = [
        ProfileDigest(profile_name=f"P{i}", added=1)
        for i in range(8)
    ]

    notification = format_profile_notification(digests, aggregate=True)

    assert notification is not None
    assert "…и ещё 3 профиля" in notification.body


# --- Split-summary ---

def test_format_split_summary_title_prefix():
    n = format_split_summary(2)

    assert n.title.startswith("CheckCopyRun")
    assert "Есть обновления" in n.title


def test_format_split_summary_body():
    n = format_split_summary(2)

    assert "Ещё в 2 профиля" in n.body
    assert "Проверьте папки источников" in n.body


def test_format_split_summary_zero():
    n = format_split_summary(0)

    assert "Проверьте папки источников" in n.body
    assert "Ещё в" not in n.body


def test_format_split_summary_no_open_path():
    n = format_split_summary(5)
    assert n.open_path == ""


# --- Провайдеры ---

class _OkProvider:
    def __init__(self):
        self.calls = 0

    def notify(self, notification):
        self.calls += 1
        return True


class _FailProvider:
    def __init__(self):
        self.calls = 0

    def notify(self, notification):
        self.calls += 1
        return False


class _RaisingProvider:
    def notify(self, notification):
        raise RuntimeError("boom")


def test_chain_stops_on_success():
    first = _FailProvider()
    second = _OkProvider()
    third = _OkProvider()

    chain = ChainNotifier([first, second, third])
    shown = chain.notify(Notification("t", "b"))

    assert shown is True
    assert first.calls == 1
    assert second.calls == 1
    assert third.calls == 0


def test_chain_survives_raising_provider():
    raising = _RaisingProvider()
    ok = _OkProvider()

    chain = ChainNotifier([raising, ok])

    assert chain.notify(Notification("t", "b")) is True
    assert ok.calls == 1


def test_chain_all_fail():
    chain = ChainNotifier([_FailProvider(), NullNotifier()])
    assert chain.notify(Notification("t", "b")) is False


def test_null_notifier_returns_false():
    assert NullNotifier().notify(Notification("t", "b")) is False
