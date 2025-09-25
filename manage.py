#!/usr/bin/env python3
"""Command line helper for the cash flow web application."""
from __future__ import annotations

import argparse
from wsgiref.simple_server import make_server

from dds_app import db
from dds_app.server import application


def runserver(host: str, port: int) -> None:
    db.ensure_database()
    with make_server(host, port, application) as httpd:
        print(f"Сервер запущен на http://{host}:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановка сервера...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление приложением ДДС")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init-db", help="Создать или обновить структуру базы данных")

    runserver_parser = subparsers.add_parser("runserver", help="Запустить встроенный веб-сервер")
    runserver_parser.add_argument("--host", default="127.0.0.1", help="Хост для прослушивания")
    runserver_parser.add_argument("--port", type=int, default=8000, help="Порт сервера")

    args = parser.parse_args()

    if args.command == "init-db":
        db.ensure_database()
        print("База данных готова к работе")
    elif args.command == "runserver":
        runserver(args.host, args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
