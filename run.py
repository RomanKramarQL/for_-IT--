#!/usr/bin/env python3
"""Упрощённый запуск встроенного WSGI-сервера приложения ДДС."""
from manage import runserver


def main() -> None:
    """Инициализировать базу (если нужно) и запустить сервер на порту 8000."""
    host = "127.0.0.1"
    port = 8000
    print("Подготовка базы данных и запуск сервера...")
    runserver(host, port)


if __name__ == "__main__":
    main()
