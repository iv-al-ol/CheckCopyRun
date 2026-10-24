"""Системные интеграции: автозапуск, DPAPI, иконки, трей, запуск.

Пакет ничего не реэкспортирует на уровне `__init__`: импортируйте
подмодули напрямую (`from services.system import autostart`).
Это критично для отсутствия циклов: core.settings_store
импортирует services.system.dpapi, а icon_cleanup импортирует
core.settings_store — эагерный реэкспорт давал бы цикл.
"""
