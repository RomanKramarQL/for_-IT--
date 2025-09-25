"""Minimal WSGI server that powers the cash flow tracker."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import html
import re
from datetime import date
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode

from . import db
from . import repository as repo

db.ensure_database()

Response = Tuple[str, List[Tuple[str, str]], bytes]


class Request:
    """Utility wrapper around the WSGI environ dictionary."""

    def __init__(self, environ: Dict[str, Any]):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "")
        self.query = parse_qs(environ.get("QUERY_STRING", ""))
        self._body: Optional[Dict[str, Any]] = None

    @property
    def POST(self) -> Dict[str, Any]:
        if self._body is None:
            try:
                length = int(self.environ.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                length = 0
            body_bytes = self.environ.get("wsgi.input").read(length) if length else b""
            content_type = self.environ.get("CONTENT_TYPE", "")
            if "application/x-www-form-urlencoded" in content_type:
                data = parse_qs(body_bytes.decode("utf-8"))
                self._body = {key: values[0] if values else "" for key, values in data.items()}
            else:
                self._body = {}
        return self._body

    def form_value(self, key: str, default: str = "") -> str:
        if self.method == "POST":
            return self.POST.get(key, default)
        return self.query.get(key, [default])[0]


class Router:
    def __init__(self):
        self._routes: List[Tuple[str, re.Pattern[str], Callable[[Request, Dict[str, str]], Response]]] = []

    def add(self, method: str, pattern: str, handler: Callable[[Request, Dict[str, str]], Response]) -> None:
        self._routes.append((method.upper(), re.compile(pattern), handler))

    def resolve(self, method: str, path: str) -> Tuple[Callable[[Request, Dict[str, str]], Response], Dict[str, str]]:
        for registered_method, regex, handler in self._routes:
            if registered_method != method.upper():
                continue
            match = regex.fullmatch(path)
            if match:
                return handler, match.groupdict()
        raise KeyError("Route not found")


router = Router()


HTML_HEADER = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f4f4f4; }}
        header {{ background: #1f2937; color: #fff; padding: 1rem 2rem; }}
        main {{ padding: 2rem; }}
        a {{ color: #1f2937; }}
        table {{ border-collapse: collapse; width: 100%; background: #fff; }}
        th, td {{ border: 1px solid #d1d5db; padding: 0.5rem; text-align: left; }}
        th {{ background: #e5e7eb; }}
        form {{ margin-bottom: 1rem; background: #fff; padding: 1rem; border: 1px solid #d1d5db; }}
        input[type=text], input[type=date], select, textarea {{ width: 100%; padding: 0.4rem; margin-top: 0.2rem; }}
        textarea {{ min-height: 80px; }}
        .actions {{ display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }}
        .btn {{ padding: 0.4rem 0.8rem; background: #2563eb; color: #fff; text-decoration: none; border: none; border-radius: 4px; cursor: pointer; }}
        .btn.secondary {{ background: #6b7280; }}
        .btn.danger {{ background: #dc2626; }}
        .message {{ padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1rem; }}
        .message.error {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
        .message.success {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }}
        .grid {{ display: grid; gap: 1rem; }}
        .grid.two {{ grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
        nav a {{ margin-right: 1rem; color: #bfdbfe; text-decoration: none; }}
        nav a.active {{ font-weight: bold; }}
        .meta {{ color: #6b7280; font-size: 0.9em; margin-left: 0.25rem; }}
    </style>
</head>
<body>
<header>
    <h1>ДДС: учёт движения денежных средств</h1>
    <nav>
        <a href="/" {home_active}>Записи</a>
        <a href="/entries/new" {create_active}>Новая запись</a>
        <a href="/reference" {reference_active}>Справочники</a>
    </nav>
</header>
<main>
"""

HTML_FOOTER = """
</main>
</body>
</html>
"""


def render_page(title: str, body: str, *, messages: Optional[List[Tuple[str, str]]] = None, active: str = "home") -> bytes:
    messages_html = ""
    for level, text in messages or []:
        messages_html += f'<div class="message {level}">{html.escape(text)}</div>'
    html_doc = HTML_HEADER.format(
        title=html.escape(title),
        home_active="class=\"active\"" if active == "home" else "",
        create_active="class=\"active\"" if active == "create" else "",
        reference_active="class=\"active\"" if active == "reference" else "",
    ) + messages_html + body + HTML_FOOTER
    return html_doc.encode("utf-8")


def redirect(location: str) -> Response:
    headers = [
        ("Location", location),
        ("Content-Type", "text/plain; charset=utf-8"),
    ]
    return "302 Found", headers, b""


# ----- Вспомогательные функции -----


def parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_amount(value: str) -> Optional[int]:
    value = (value or "").strip().replace(" ", "")
    if not value:
        return None
    value = value.replace(",", ".")
    try:
        dec_value = Decimal(value)
    except InvalidOperation:
        return None
    dec_value = dec_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cents = int(dec_value * 100)
    return cents


def format_amount(cents: int) -> str:
    return f"{cents / 100:,.2f}".replace(",", " ")


# ----- Представления -----


def format_reference_name(row: Dict[str, Any]) -> str:
    name = html.escape(row["name"])
    if "type_name" in row:
        name += f"<span class='meta'>{html.escape(row['type_name'])}</span>"
    elif "category_name" in row:
        name += f"<span class='meta'>{html.escape(row['category_name'])}</span>"
    return name


def view_index(request: Request, params: Dict[str, str]) -> Response:
    filters = {
        "date_from": request.form_value("date_from"),
        "date_to": request.form_value("date_to"),
        "status_id": request.form_value("status_id"),
        "type_id": request.form_value("type_id"),
        "category_id": request.form_value("category_id"),
        "subcategory_id": request.form_value("subcategory_id"),
    }
    entries = repo.list_cashflows({k: v for k, v in filters.items() if v})
    references = db.load_reference_lists()

    rows_html = "".join(
        f"<tr><td>{html.escape(entry['recorded_on'])}</td>"
        f"<td>{html.escape(entry['status_name'])}</td>"
        f"<td>{html.escape(entry['type_name'])}</td>"
        f"<td>{html.escape(entry['category_name'])}</td>"
        f"<td>{html.escape(entry['subcategory_name'])}</td>"
        f"<td>{format_amount(entry['amount_cents'])}</td>"
        f"<td>{html.escape(entry['comment'] or '')}</td>"
        f"<td class='actions'>"
        f"<a class='btn secondary' href='/entries/{entry['id']}/edit'>Изменить</a>"
        f"<form method='post' action='/entries/{entry['id']}/delete' style='display:inline' onsubmit='return confirm(\"Удалить запись?\");'>"
        f"<button type='submit' class='btn danger'>Удалить</button></form></td></tr>"
        for entry in entries
    )
    if not rows_html:
        rows_html = "<tr><td colspan='8' style='text-align:center;color:#6b7280;'>Нет записей</td></tr>"

    def options(items: List[Dict[str, Any]], selected: str) -> str:
        opts = ["<option value=''>— все —</option>"]
        for item in items:
            sel = " selected" if str(item["id"]) == selected else ""
            opts.append(f"<option value='{item['id']}'{sel}>{html.escape(item['name'])}</option>")
        return "".join(opts)

    filter_form = f"""
    <form method="get" class="grid two">
        <div>
            <label>Дата с
                <input type="date" name="date_from" value="{html.escape(filters['date_from'])}">
            </label>
        </div>
        <div>
            <label>Дата по
                <input type="date" name="date_to" value="{html.escape(filters['date_to'])}">
            </label>
        </div>
        <div>
            <label>Статус
                <select name="status_id">{options(references.statuses, filters['status_id'])}</select>
            </label>
        </div>
        <div>
            <label>Тип
                <select name="type_id">{options(references.types, filters['type_id'])}</select>
            </label>
        </div>
        <div>
            <label>Категория
                <select name="category_id">{options(references.categories, filters['category_id'])}</select>
            </label>
        </div>
        <div>
            <label>Подкатегория
                <select name="subcategory_id">{options(references.subcategories, filters['subcategory_id'])}</select>
            </label>
        </div>
        <div class="actions">
            <button class="btn" type="submit">Применить фильтры</button>
            <a class="btn secondary" href="/">Сбросить</a>
        </div>
    </form>
    """

    body = filter_form + """
    <table>
        <thead>
            <tr>
                <th>Дата</th>
                <th>Статус</th>
                <th>Тип</th>
                <th>Категория</th>
                <th>Подкатегория</th>
                <th>Сумма (₽)</th>
                <th>Комментарий</th>
                <th>Действия</th>
            </tr>
        </thead>
        <tbody>
    """ + rows_html + "</tbody></table>"

    message = []
    if request.query.get("success"):
        message.append(("success", request.query["success"][0]))
    return "200 OK", [("Content-Type", "text/html; charset=utf-8")], render_page("Список записей", body, messages=message, active="home")


def entry_form_context(references: db.ReferenceLists, data: Dict[str, Any]) -> str:
    type_to_categories: Dict[str, List[Dict[str, Any]]] = {}
    for category in references.categories:
        type_to_categories.setdefault(str(category["type_id"]), []).append(category)

    category_to_subcats: Dict[str, List[Dict[str, Any]]] = {}
    for sub in references.subcategories:
        category_to_subcats.setdefault(str(sub["category_id"]), []).append(sub)

    type_options = "".join(
        f"<option value='{t['id']}' {'selected' if str(t['id']) == str(data.get('type_id','')) else ''}>{html.escape(t['name'])}</option>"
        for t in references.types
    )
    status_options = "".join(
        f"<option value='{s['id']}' {'selected' if str(s['id']) == str(data.get('status_id','')) else ''}>{html.escape(s['name'])}</option>"
        for s in references.statuses
    )

    # Формируем списки категорий и подкатегорий с учётом выбранных значений
    selected_type = str(data.get("type_id", ""))
    selected_category = str(data.get("category_id", ""))
    selected_subcategory = str(data.get("subcategory_id", ""))

    def build_options(items: List[Dict[str, Any]], selected_value: str) -> str:
        return "".join(
            f"<option value='{item['id']}' {'selected' if str(item['id']) == selected_value else ''}>{html.escape(item['name'])}</option>"
            for item in items
        )

    categories_for_type = type_to_categories.get(selected_type, []) if selected_type else []
    category_options = build_options(categories_for_type, selected_category)
    subcategories_for_category = category_to_subcats.get(selected_category, []) if selected_category else []
    subcategory_options = build_options(subcategories_for_category, selected_subcategory)

    script_data = {
        "typeToCategories": type_to_categories,
        "categoryToSubcategories": category_to_subcats,
    }

    return f"""
    <form method="post" class="grid two" id="entry-form">
        <div>
            <label>Дата операции
                <input type="date" name="recorded_on" value="{html.escape(str(data.get('recorded_on','')))}" required>
            </label>
        </div>
        <div>
            <label>Статус
                <select name="status_id" required>{status_options}</select>
            </label>
        </div>
        <div>
            <label>Тип
                <select name="type_id" id="type-select" required>
                    <option value="">— выберите тип —</option>
                    {type_options}
                </select>
            </label>
        </div>
        <div>
            <label>Категория
                <select name="category_id" id="category-select" required>
                    <option value="">— выберите категорию —</option>
                    {category_options}
                </select>
            </label>
        </div>
        <div>
            <label>Подкатегория
                <select name="subcategory_id" id="subcategory-select" required>
                    <option value="">— выберите подкатегорию —</option>
                    {subcategory_options}
                </select>
            </label>
        </div>
        <div>
            <label>Сумма, ₽
                <input type="text" name="amount" value="{html.escape(str(data.get('amount','')))}" placeholder="например, 1000" required>
            </label>
        </div>
        <div style="grid-column: 1 / -1;">
            <label>Комментарий
                <textarea name="comment" placeholder="Необязательное поле">{html.escape(str(data.get('comment','')))}</textarea>
            </label>
        </div>
        <div class="actions" style="grid-column: 1 / -1;">
            <button class="btn" type="submit">Сохранить</button>
            <a class="btn secondary" href="/">Отмена</a>
        </div>
    </form>
    <script>
    const data = {json.dumps(script_data)};
    const typeSelect = document.getElementById('type-select');
    const categorySelect = document.getElementById('category-select');
    const subcategorySelect = document.getElementById('subcategory-select');

    function populate(select, items, selected) {{
        select.innerHTML = '<option value="">— выберите —</option>';
        items.forEach(item => {{
            const option = document.createElement('option');
            option.value = item.id;
            option.textContent = item.name;
            if (String(item.id) === String(selected)) {{
                option.selected = true;
            }}
            select.appendChild(option);
        }});
    }}

    function onTypeChange() {{
        const selectedType = typeSelect.value;
        const categories = data.typeToCategories[selectedType] || [];
        populate(categorySelect, categories, '{selected_category}');
        categorySelect.dispatchEvent(new Event('change'));
    }}

    function onCategoryChange() {{
        const selectedCategory = categorySelect.value;
        const subcategories = data.categoryToSubcategories[selectedCategory] || [];
        populate(subcategorySelect, subcategories, '{selected_subcategory}');
    }}

    typeSelect.addEventListener('change', () => {{
        populate(categorySelect, data.typeToCategories[typeSelect.value] || [], '');
        populate(subcategorySelect, [], '');
    }});

    categorySelect.addEventListener('change', () => {{
        populate(subcategorySelect, data.categoryToSubcategories[categorySelect.value] || [], '');
    }});

    if (typeSelect.value) {{
        onTypeChange();
    }}
    if (categorySelect.value) {{
        onCategoryChange();
    }}
    </script>
    """


def validate_entry_form(form: Dict[str, str]) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    data: Dict[str, Any] = {}

    recorded_on = form.get("recorded_on", "").strip()
    if not recorded_on:
        errors.append("Дата операции обязательна")
    else:
        data["recorded_on"] = recorded_on

    status_id = parse_int(form.get("status_id", ""))
    if not status_id:
        errors.append("Статус обязателен")
    elif not repo.get_status(status_id):
        errors.append("Выбран несуществующий статус")
    else:
        data["status_id"] = status_id

    type_id = parse_int(form.get("type_id", ""))
    if not type_id:
        errors.append("Тип обязателен")
    elif not repo.get_type(type_id):
        errors.append("Выбран несуществующий тип")
    else:
        data["type_id"] = type_id

    category_id = parse_int(form.get("category_id", ""))
    if not category_id:
        errors.append("Категория обязательна")
    else:
        category = repo.get_category(category_id)
        if not category:
            errors.append("Выбрана несуществующая категория")
        else:
            data["category_id"] = category_id
            if type_id and category["type_id"] != type_id:
                errors.append("Категория не связана с выбранным типом")

    subcategory_id = parse_int(form.get("subcategory_id", ""))
    if not subcategory_id:
        errors.append("Подкатегория обязательна")
    else:
        subcategory = repo.get_subcategory(subcategory_id)
        if not subcategory:
            errors.append("Выбрана несуществующая подкатегория")
        else:
            data["subcategory_id"] = subcategory_id
            if category_id and subcategory["category_id"] != category_id:
                errors.append("Подкатегория не относится к выбранной категории")
            if type_id and subcategory["type_id"] != type_id:
                errors.append("Подкатегория не относится к выбранному типу")

    amount_raw = form.get("amount", "")
    cents = parse_amount(amount_raw)
    if cents is None or cents == 0:
        errors.append("Введите корректную сумму")
    else:
        data["amount_cents"] = cents
        data["amount"] = amount_raw

    data["comment"] = form.get("comment", "").strip()

    return data, errors


def view_new_entry(request: Request, params: Dict[str, str]) -> Response:
    references = db.load_reference_lists()
    defaults = {
        "recorded_on": date.today().isoformat(),
        "amount": "",
    }
    body = entry_form_context(references, defaults)
    return (
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8")],
        render_page("Новая запись", body, active="create"),
    )


def view_create_entry(request: Request, params: Dict[str, str]) -> Response:
    form = request.POST
    data, errors = validate_entry_form(form)
    references = db.load_reference_lists()
    if errors:
        body = entry_form_context(references, {**form, **data})
        messages = [("error", error) for error in errors]
        return (
            "400 Bad Request",
            [("Content-Type", "text/html; charset=utf-8")],
            render_page("Новая запись", body, messages=messages, active="create"),
        )

    repo.create_cashflow(data)
    query = urlencode({"success": "Запись успешно создана"})
    return redirect(f"/?{query}")


def view_edit_entry(request: Request, params: Dict[str, str]) -> Response:
    entry_id = int(params["entry_id"])
    entry = repo.get_cashflow(entry_id)
    if not entry:
        return not_found()
    references = db.load_reference_lists()
    form_data = {
        "recorded_on": entry["recorded_on"],
        "status_id": entry["status_id"],
        "type_id": entry["type_id"],
        "category_id": entry["category_id"],
        "subcategory_id": entry["subcategory_id"],
        "amount": f"{entry['amount_cents'] / 100:.2f}",
        "comment": entry.get("comment", ""),
    }
    body = entry_form_context(references, form_data)
    return (
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8")],
        render_page("Редактирование записи", body, active="create"),
    )


def view_update_entry(request: Request, params: Dict[str, str]) -> Response:
    entry_id = int(params["entry_id"])
    if not repo.get_cashflow(entry_id):
        return not_found()
    form = request.POST
    data, errors = validate_entry_form(form)
    references = db.load_reference_lists()
    if errors:
        body = entry_form_context(references, {**form, **data})
        messages = [("error", error) for error in errors]
        return (
            "400 Bad Request",
            [("Content-Type", "text/html; charset=utf-8")],
            render_page("Редактирование записи", body, messages=messages, active="create"),
        )
    repo.update_cashflow(entry_id, data)
    query = urlencode({"success": "Запись обновлена"})
    return redirect(f"/?{query}")


def view_delete_entry(request: Request, params: Dict[str, str]) -> Response:
    entry_id = int(params["entry_id"])
    if not repo.get_cashflow(entry_id):
        return not_found()
    repo.delete_cashflow(entry_id)
    query = urlencode({"success": "Запись удалена"})
    return redirect(f"/?{query}")


# ----- Управление справочниками -----


def render_reference_page(messages: Optional[List[Tuple[str, str]]] = None) -> Response:
    references = db.load_reference_lists()

    def render_table(title: str, rows: List[Dict[str, Any]], edit_url: str, delete_url: str, extra: str = "") -> str:
        header = f"<h2>{html.escape(title)}</h2>"
        table_rows = "".join(
            f"<tr><td>{html.escape(str(row['id']))}</td><td>{format_reference_name(row)}</td>"
            f"<td class='actions'><a class='btn secondary' href='{edit_url.format(row['id'])}'>Изменить</a>"
            f"<form method='post' action='{delete_url.format(row['id'])}' style='display:inline' onsubmit='return confirm(\"Удалить элемент?\");'>"
            f"<button type='submit' class='btn danger'>Удалить</button></form></td></tr>"
            for row in rows
        )
        if not table_rows:
            table_rows = "<tr><td colspan='3' style='text-align:center;color:#6b7280;'>Нет данных</td></tr>"
        return header + extra + f"<table><thead><tr><th>ID</th><th>Название</th><th>Действия</th></tr></thead><tbody>{table_rows}</tbody></table>"

    body_parts = [
        render_table(
            "Статусы",
            references.statuses,
            "/reference/statuses/{}/edit",
            "/reference/statuses/{}/delete",
            """
            <form method='post' action='/reference/statuses'>
                <label>Новый статус
                    <input type='text' name='name' required>
                </label>
                <div class='actions'>
                    <button class='btn' type='submit'>Добавить</button>
                </div>
            </form>
            """,
        ),
        render_table(
            "Типы операций",
            references.types,
            "/reference/types/{}/edit",
            "/reference/types/{}/delete",
            """
            <form method='post' action='/reference/types'>
                <label>Новый тип
                    <input type='text' name='name' required>
                </label>
                <div class='actions'>
                    <button class='btn' type='submit'>Добавить</button>
                </div>
            </form>
            """,
        ),
    ]

    category_form = """
        <form method='post' action='/reference/categories'>
            <label>Название категории
                <input type='text' name='name' required>
            </label>
            <label>Тип
                <select name='type_id' required>
                    {type_options}
                </select>
            </label>
            <div class='actions'>
                <button class='btn' type='submit'>Добавить</button>
            </div>
        </form>
    """
    type_options = "".join(
        f"<option value='{t['id']}'>{html.escape(t['name'])}</option>" for t in references.types
    )
    category_form = category_form.format(type_options=type_options)

    body_parts.append(
        render_table(
            "Категории",
            references.categories,
            "/reference/categories/{}/edit",
            "/reference/categories/{}/delete",
            category_form,
        )
    )

    category_options_for_sub = "".join(
        f"<option value='{c['id']}'>{html.escape(c['name'])} ({html.escape(c['type_name'])})</option>"
        for c in references.categories
    )
    subcategory_form = """
        <form method='post' action='/reference/subcategories'>
            <label>Название подкатегории
                <input type='text' name='name' required>
            </label>
            <label>Категория
                <select name='category_id' required>
                    {category_options}
                </select>
            </label>
            <div class='actions'>
                <button class='btn' type='submit'>Добавить</button>
            </div>
        </form>
    """.format(category_options=category_options_for_sub)

    body_parts.append(
        render_table(
            "Подкатегории",
            references.subcategories,
            "/reference/subcategories/{}/edit",
            "/reference/subcategories/{}/delete",
            subcategory_form,
        )
    )

    body = "<div class='grid'>" + "".join(body_parts) + "</div>"
    return (
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8")],
        render_page("Справочники", body, messages=messages, active="reference"),
    )


def not_found() -> Response:
    body = render_page("Страница не найдена", "<p>Запрошенный ресурс не найден.</p>")
    return "404 Not Found", [("Content-Type", "text/html; charset=utf-8")], body


def view_reference(request: Request, params: Dict[str, str]) -> Response:
    return render_reference_page()


def handle_reference_creation(entity: str, request: Request, params: Dict[str, str]) -> Response:
    name = request.POST.get("name", "").strip()
    if not name:
        return render_reference_page([("error", "Название обязательно")])
    try:
        if entity == "status":
            repo.create_status(name)
        elif entity == "type":
            repo.create_type(name)
        elif entity == "category":
            type_id = parse_int(request.POST.get("type_id", ""))
            if not type_id or not repo.get_type(type_id):
                return render_reference_page([("error", "Выберите корректный тип")])
            repo.create_category(name, type_id)
        elif entity == "subcategory":
            category_id = parse_int(request.POST.get("category_id", ""))
            if not category_id or not repo.get_category(category_id):
                return render_reference_page([("error", "Выберите корректную категорию")])
            repo.create_subcategory(name, category_id)
    except sqlite3.IntegrityError:
        return render_reference_page([("error", "Элемент с таким названием уже существует")])
    return render_reference_page([("success", "Элемент добавлен")])


def handle_reference_edit_form(entity: str, request: Request, params: Dict[str, str]) -> Response:
    entity_id = int(params["entity_id"])
    references = db.load_reference_lists()
    if entity == "status":
        item = repo.get_status(entity_id)
    elif entity == "type":
        item = repo.get_type(entity_id)
    elif entity == "category":
        item = repo.get_category(entity_id)
    else:
        item = repo.get_subcategory(entity_id)
    if not item:
        return not_found()

    if entity == "category":
        type_options = "".join(
            f"<option value='{t['id']}' {'selected' if t['id'] == item['type_id'] else ''}>{html.escape(t['name'])}</option>"
            for t in references.types
        )
        extra = f"""
        <form method='post'>
            <label>Название
                <input type='text' name='name' value='{html.escape(item['name'])}' required>
            </label>
            <label>Тип
                <select name='type_id' required>{type_options}</select>
            </label>
            <div class='actions'>
                <button class='btn' type='submit'>Сохранить</button>
                <a class='btn secondary' href='/reference'>Отмена</a>
            </div>
        </form>
        """
    elif entity == "subcategory":
        category_options = "".join(
            f"<option value='{c['id']}' {'selected' if c['id'] == item['category_id'] else ''}>{html.escape(c['name'])}</option>"
            for c in references.categories
        )
        extra = f"""
        <form method='post'>
            <label>Название
                <input type='text' name='name' value='{html.escape(item['name'])}' required>
            </label>
            <label>Категория
                <select name='category_id' required>{category_options}</select>
            </label>
            <div class='actions'>
                <button class='btn' type='submit'>Сохранить</button>
                <a class='btn secondary' href='/reference'>Отмена</a>
            </div>
        </form>
        """
    else:
        extra = f"""
        <form method='post'>
            <label>Название
                <input type='text' name='name' value='{html.escape(item['name'])}' required>
            </label>
            <div class='actions'>
                <button class='btn' type='submit'>Сохранить</button>
                <a class='btn secondary' href='/reference'>Отмена</a>
            </div>
        </form>
        """

    body = f"<h2>Редактирование</h2>{extra}"
    return (
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8")],
        render_page("Редактирование", body, active="reference"),
    )


def handle_reference_update(entity: str, request: Request, params: Dict[str, str]) -> Response:
    entity_id = int(params["entity_id"])
    name = request.POST.get("name", "").strip()
    if not name:
        return render_reference_page([("error", "Название обязательно")])

    try:
        if entity == "status":
            if not repo.get_status(entity_id):
                return not_found()
            repo.update_status(entity_id, name)
        elif entity == "type":
            if not repo.get_type(entity_id):
                return not_found()
            repo.update_type(entity_id, name)
        elif entity == "category":
            category = repo.get_category(entity_id)
            if not category:
                return not_found()
            type_id = parse_int(request.POST.get("type_id", ""))
            if not type_id or not repo.get_type(type_id):
                return render_reference_page([("error", "Выберите корректный тип")])
            if type_id != category["type_id"]:
                # проверяем отсутствие записей ДДС для категории перед сменой типа
                if repo.count_dependencies("cashflows", "category_id", entity_id) > 0:
                    return render_reference_page([("error", "Нельзя изменить тип категории, пока существуют связанные записи ДДС")])
            repo.update_category(entity_id, name, type_id)
        else:
            subcategory = repo.get_subcategory(entity_id)
            if not subcategory:
                return not_found()
            category_id = parse_int(request.POST.get("category_id", ""))
            if not category_id:
                return render_reference_page([("error", "Выберите корректную категорию")])
            category = repo.get_category(category_id)
            if not category:
                return render_reference_page([("error", "Выберите корректную категорию")])
            if repo.count_dependencies("cashflows", "subcategory_id", entity_id) > 0 and category_id != subcategory["category_id"]:
                return render_reference_page([("error", "Нельзя изменить категорию подкатегории, пока существуют связанные записи ДДС")])
            repo.update_subcategory(entity_id, name, category_id)
    except sqlite3.IntegrityError:
        return render_reference_page([("error", "Элемент с таким названием уже существует")])

    return render_reference_page([("success", "Изменения сохранены")])


def handle_reference_delete(entity: str, request: Request, params: Dict[str, str]) -> Response:
    entity_id = int(params["entity_id"])
    if entity == "status":
        if repo.count_dependencies("cashflows", "status_id", entity_id) > 0:
            return render_reference_page([("error", "Нельзя удалить статус, пока существуют связанные записи ДДС")])
        repo.delete_status(entity_id)
    elif entity == "type":
        if repo.count_dependencies("categories", "type_id", entity_id) > 0 or repo.count_dependencies("cashflows", "type_id", entity_id) > 0:
            return render_reference_page([("error", "Нельзя удалить тип с существующими категориями или записями ДДС")])
        repo.delete_type(entity_id)
    elif entity == "category":
        if repo.count_dependencies("subcategories", "category_id", entity_id) > 0 or repo.count_dependencies("cashflows", "category_id", entity_id) > 0:
            return render_reference_page([("error", "Нельзя удалить категорию, пока существуют связанные подкатегории или записи ДДС")])
        repo.delete_category(entity_id)
    else:
        if repo.count_dependencies("cashflows", "subcategory_id", entity_id) > 0:
            return render_reference_page([("error", "Нельзя удалить подкатегорию, пока существуют связанные записи ДДС")])
        repo.delete_subcategory(entity_id)
    return render_reference_page([("success", "Элемент удалён")])


# ----- Регистрация маршрутов -----

router.add("GET", r"/", view_index)
router.add("GET", r"/entries/new", view_new_entry)
router.add("POST", r"/entries/new", view_create_entry)
router.add("GET", r"/entries/(?P<entry_id>\d+)/edit", view_edit_entry)
router.add("POST", r"/entries/(?P<entry_id>\d+)/edit", view_update_entry)
router.add("POST", r"/entries/(?P<entry_id>\d+)/delete", view_delete_entry)

router.add("GET", r"/reference", view_reference)
router.add("POST", r"/reference/statuses", lambda req, params: handle_reference_creation("status", req, params))
router.add("POST", r"/reference/types", lambda req, params: handle_reference_creation("type", req, params))
router.add("POST", r"/reference/categories", lambda req, params: handle_reference_creation("category", req, params))
router.add("POST", r"/reference/subcategories", lambda req, params: handle_reference_creation("subcategory", req, params))

router.add("GET", r"/reference/statuses/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_edit_form("status", req, params))
router.add("GET", r"/reference/types/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_edit_form("type", req, params))
router.add("GET", r"/reference/categories/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_edit_form("category", req, params))
router.add("GET", r"/reference/subcategories/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_edit_form("subcategory", req, params))

router.add("POST", r"/reference/statuses/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_update("status", req, params))
router.add("POST", r"/reference/types/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_update("type", req, params))
router.add("POST", r"/reference/categories/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_update("category", req, params))
router.add("POST", r"/reference/subcategories/(?P<entity_id>\d+)/edit", lambda req, params: handle_reference_update("subcategory", req, params))

router.add("POST", r"/reference/statuses/(?P<entity_id>\d+)/delete", lambda req, params: handle_reference_delete("status", req, params))
router.add("POST", r"/reference/types/(?P<entity_id>\d+)/delete", lambda req, params: handle_reference_delete("type", req, params))
router.add("POST", r"/reference/categories/(?P<entity_id>\d+)/delete", lambda req, params: handle_reference_delete("category", req, params))
router.add("POST", r"/reference/subcategories/(?P<entity_id>\d+)/delete", lambda req, params: handle_reference_delete("subcategory", req, params))


# ----- Точка входа WSGI -----

def application(environ: Dict[str, Any], start_response: Callable[[str, List[Tuple[str, str]]], None]):
    try:
        request = Request(environ)
        handler, params = router.resolve(request.method, request.path)
        status, headers, body = handler(request, params)
    except KeyError:
        status, headers, body = not_found()
    except Exception as exc:  # pragma: no cover - защитный код
        body = render_page("Ошибка", f"<p>Произошла ошибка: {html.escape(str(exc))}</p>", messages=[("error", "Внутренняя ошибка сервера")])
        status = "500 Internal Server Error"
        headers = [("Content-Type", "text/html; charset=utf-8")]
    start_response(status, headers)
    return [body]


__all__ = ["application"]
