from flask import Flask, render_template, request, jsonify, send_file, url_for, session, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import inspect, text
import hmac
import os
import re

from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


def _resolve_company_logo(raw):
    logo = (raw or "logo.png").strip().replace("\\", "/")
    if logo.startswith(("http://", "https://")):
        return logo
    if logo.startswith("static/"):
        logo = logo[len("static/") :]
    if ".." in logo or logo.startswith("/"):
        return "logo.png"
    return logo


def _company_logo_url(logo_file, request_root=None):
    if logo_file.startswith(("http://", "https://")):
        return logo_file
    path = url_for("static", filename=logo_file)
    if request_root:
        return request_root.rstrip("/") + path
    return path


CURRENCIES = {
    "GBP": {"code": "GBP", "symbol": "£", "label": "UK £"},
    "USD": {"code": "USD", "symbol": "US$", "label": "US $"},
    "JMD": {"code": "JMD", "symbol": "J$", "label": "Jamaican $"},
    "EUR": {"code": "EUR", "symbol": "€", "label": "Euro"},
}
DEFAULT_CURRENCY = "GBP"
JOB_DESCRIPTION_MAX = 8000


def _currency_meta(code):
    key = (code or DEFAULT_CURRENCY).strip().upper()
    return CURRENCIES.get(key, CURRENCIES[DEFAULT_CURRENCY])


def _currency_symbol(code):
    return _currency_meta(code)["symbol"]


def _parse_currency(data: dict):
    raw = data.get("currency")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_CURRENCY, None
    code = str(raw).strip().upper()
    if code not in CURRENCIES:
        return None, "Unsupported currency"
    return code, None


def _parse_job_description(data: dict, required_key=False):
    if "job_description" not in data:
        if required_key:
            return "", None
        return None, None
    text = str(data.get("job_description") or "").strip()
    if len(text) > JOB_DESCRIPTION_MAX:
        text = text[:JOB_DESCRIPTION_MAX]
    return text, None


def _env_company_defaults():
    name = (os.environ.get("COMPANY_NAME") or "Paul Banning").strip()
    raw_address = (
        os.environ.get("COMPANY_ADDRESS") or "48 Pellipar Close, London N13 4AG"
    ).strip()
    if "COMPANY_PHONE" in os.environ:
        phone = os.environ.get("COMPANY_PHONE", "").strip()
    else:
        phone = "07730 556097"
    return {
        "name": name,
        "address": raw_address,
        "phone": phone,
        "bank_name": (os.environ.get("COMPANY_BANK_ACCOUNT_NAME") or name).strip(),
        "bank_account": (os.environ.get("COMPANY_BANK_ACCOUNT") or "72113763").strip(),
        "bank_sort": (os.environ.get("COMPANY_BANK_SORT") or "60-83-71").strip(),
        "payment_terms": (
            os.environ.get("COMPANY_PAYMENT_TERMS")
            or "Payment is due on receipt of invoice"
        ).strip(),
        "app_title": (os.environ.get("COMPANY_APP_TITLE") or "Invoices & quotes").strip(),
        "logo_file": _resolve_company_logo(os.environ.get("COMPANY_LOGO")),
    }


def _finalize_company(raw):
    name = (raw.get("name") or "Paul Banning").strip() or "Paul Banning"
    address = (raw.get("address") or "").strip()
    phone = (raw.get("phone") or "").strip()
    address_lines = [
        line.strip()
        for line in address.replace("\\n", "\n").split("\n")
        if line.strip()
    ]
    if phone and all(phone not in line for line in address_lines):
        address_lines.append(phone)
    return {
        "name": name,
        "address": address,
        "address_lines": address_lines,
        "phone": phone,
        "bank_name": (raw.get("bank_name") or name).strip() or name,
        "bank_account": (raw.get("bank_account") or "").strip(),
        "bank_sort": (raw.get("bank_sort") or "").strip(),
        "payment_terms": (
            raw.get("payment_terms") or "Payment is due on receipt of invoice"
        ).strip(),
        "app_title": (raw.get("app_title") or "Invoices & quotes").strip(),
        "logo_file": raw.get("logo_file") or "logo.png",
    }


def _company_config():
    """Business branding from saved settings, falling back to environment defaults."""
    defaults = _env_company_defaults()
    row = None
    try:
        row = CompanySettings.query.order_by(CompanySettings.id.asc()).first()
    except Exception:
        row = None
    if not row:
        return _finalize_company(defaults)

    merged = dict(defaults)
    if row.name is not None:
        merged["name"] = row.name
    if row.address is not None:
        merged["address"] = row.address
    if row.phone is not None:
        merged["phone"] = row.phone
    if row.bank_name is not None:
        merged["bank_name"] = row.bank_name
    if row.bank_account is not None:
        merged["bank_account"] = row.bank_account
    if row.bank_sort is not None:
        merged["bank_sort"] = row.bank_sort
    if row.payment_terms is not None:
        merged["payment_terms"] = row.payment_terms
    if row.app_title is not None:
        merged["app_title"] = row.app_title
    return _finalize_company(merged)


def _database_uri():
    """Railway Postgres sets DATABASE_URL. Local dev uses SQLite if unset."""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        # Recent SQLAlchemy treats postgresql:// as psycopg v3. This app installs psycopg2.
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://") :]
        return url
    instance_path = os.path.join(basedir, "instance")
    os.makedirs(instance_path, exist_ok=True)
    db_path = os.path.join(instance_path, "invoices.db")
    return "sqlite:///" + db_path.replace("\\", "/")


# Optional: volume mount for generated PDFs only (DB is Postgres on Railway)
_data_root = os.environ.get("DATA_DIR", basedir).strip() or basedir
_invoice_folder = os.path.join(_data_root, "invoices")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_engine_options = {}
if (os.environ.get("DATABASE_URL") or "").strip():
    _engine_options["pool_pre_ping"] = True

_config = dict(
    SQLALCHEMY_DATABASE_URI=_database_uri(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-in-production"),
    INVOICE_FOLDER=_invoice_folder,
)
if _engine_options:
    _config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_options
app.config.update(_config)
app.debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

os.makedirs(app.config["INVOICE_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))
    invoices = db.relationship("Invoice", backref="client", lazy=True)
    quotes = db.relationship("Quote", backref="client", lazy=True)


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(20), unique=True, nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    items = db.relationship("InvoiceItem", backref="invoice", lazy=True)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    paid = db.Column(db.Boolean, nullable=False, default=False)
    vat_applies = db.Column(db.Boolean, nullable=False, default=False)
    vat_rate_percent = db.Column(db.Float, nullable=True)
    vat_amount = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(3), nullable=False, default=DEFAULT_CURRENCY)
    job_description = db.Column(db.Text, nullable=True)


class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)


class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_number = db.Column(db.String(20), unique=True, nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    items = db.relationship(
        "QuoteItem", backref="quote", lazy=True, cascade="all, delete-orphan"
    )
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    vat_applies = db.Column(db.Boolean, nullable=False, default=False)
    vat_rate_percent = db.Column(db.Float, nullable=True)
    vat_amount = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(3), nullable=False, default=DEFAULT_CURRENCY)
    job_description = db.Column(db.Text, nullable=True)
    converted_invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=True)
    converted_invoice = db.relationship("Invoice", foreign_keys=[converted_invoice_id])


class QuoteItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    quote_id = db.Column(db.Integer, db.ForeignKey("quote.id"), nullable=False)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


class CompanySettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=True)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(80), nullable=True)
    bank_name = db.Column(db.String(200), nullable=True)
    bank_account = db.Column(db.String(80), nullable=True)
    bank_sort = db.Column(db.String(40), nullable=True)
    payment_terms = db.Column(db.Text, nullable=True)
    app_title = db.Column(db.String(200), nullable=True)


def _auth_enabled() -> bool:
    return bool((os.environ.get("INVOICE_APP_PASSWORD") or "").strip())


def _bootstrap_auth_user():
    if not _auth_enabled():
        return
    username = (os.environ.get("INVOICE_APP_USERNAME") or "admin").strip() or "admin"
    if User.query.filter_by(username=username).first():
        return
    pwd = os.environ["INVOICE_APP_PASSWORD"].strip()
    db.session.add(User(username=username, password_hash=generate_password_hash(pwd)))
    db.session.commit()


def _ensure_invoice_vat_columns():
    """Add VAT columns to existing deployments (create_all does not alter tables)."""
    try:
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        if "invoice" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("invoice")}
        dialect = db.engine.dialect.name
        alters = []
        if "vat_applies" not in cols:
            if dialect == "sqlite":
                alters.append(
                    "ALTER TABLE invoice ADD COLUMN vat_applies BOOLEAN NOT NULL DEFAULT 0"
                )
            else:
                alters.append(
                    "ALTER TABLE invoice ADD COLUMN vat_applies BOOLEAN NOT NULL DEFAULT FALSE"
                )
        if "vat_rate_percent" not in cols:
            alters.append("ALTER TABLE invoice ADD COLUMN vat_rate_percent FLOAT")
        if "vat_amount" not in cols:
            if dialect == "sqlite":
                alters.append(
                    "ALTER TABLE invoice ADD COLUMN vat_amount REAL NOT NULL DEFAULT 0"
                )
            else:
                alters.append(
                    "ALTER TABLE invoice ADD COLUMN vat_amount DOUBLE PRECISION NOT NULL DEFAULT 0"
                )
        for stmt in alters:
            with db.engine.begin() as conn:
                conn.execute(text(stmt))
    except Exception as e:
        app.logger.warning("Could not ensure invoice VAT columns: %s", e)


def _ensure_quote_converted_column():
    """Add converted_invoice_id to existing deployments."""
    try:
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        if "quote" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("quote")}
        if "converted_invoice_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE quote ADD COLUMN converted_invoice_id INTEGER"))
    except Exception as e:
        app.logger.warning("Could not ensure quote converted column: %s", e)


def _ensure_currency_and_job_columns():
    """Add currency and job_description to existing invoice/quote tables."""
    try:
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        dialect_default = "VARCHAR(3) NOT NULL DEFAULT 'GBP'"
        for table in ("invoice", "quote"):
            if table not in tables:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            alters = []
            if "currency" not in cols:
                alters.append(f"ALTER TABLE {table} ADD COLUMN currency {dialect_default}")
            if "job_description" not in cols:
                alters.append(f"ALTER TABLE {table} ADD COLUMN job_description TEXT")
            for stmt in alters:
                with db.engine.begin() as conn:
                    conn.execute(text(stmt))
        dialect = db.engine.dialect.name
        if dialect != "sqlite":
            for item_table in ("invoice_item", "quote_item"):
                if item_table not in tables:
                    continue
                with db.engine.begin() as conn:
                    conn.execute(
                        text(
                            f"ALTER TABLE {item_table} ALTER COLUMN description TYPE TEXT"
                        )
                    )
    except Exception as e:
        app.logger.warning("Could not ensure currency/job columns: %s", e)


def _new_currency_bucket():
    return {"count": 0, "owed_total": 0.0, "paid_total": 0.0}


def _finalize_currency_map(raw):
    out = {}
    for code in sorted(raw.keys()):
        bucket = raw[code]
        out[code] = {
            "count": bucket["count"],
            "owed_total": round(bucket["owed_total"], 2),
            "paid_total": round(bucket["paid_total"], 2),
        }
    return out


def _calendar_week_range(now=None):
    """Monday 00:00 UTC through the following Monday 00:00 UTC (end exclusive)."""
    now = now or datetime.utcnow()
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(days=7)
    return start, end


def _calendar_month_range(now=None):
    """First day of month 00:00 UTC through first day of next month (end exclusive)."""
    now = now or datetime.utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _calendar_year_range(now=None):
    """1 Jan 00:00 UTC through 1 Jan next year (end exclusive)."""
    now = now or datetime.utcnow()
    start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1)
    return start, end


def _period_range(period: str):
    period = (period or "month").strip().lower()
    if period == "week":
        return "week", *_calendar_week_range()
    if period == "year":
        return "year", *_calendar_year_range()
    return "month", *_calendar_month_range()


def _build_period_summary(start, end):
    invoices = (
        Invoice.query.filter(Invoice.date >= start, Invoice.date < end)
        .order_by(Invoice.date.desc())
        .all()
    )
    paid_total = 0.0
    owed_total = 0.0
    inv_by = defaultdict(_new_currency_bucket)
    for inv in invoices:
        amount = float(inv.total_amount or 0)
        code = (getattr(inv, "currency", None) or DEFAULT_CURRENCY).upper()
        inv_by[code]["count"] += 1
        if inv.paid:
            paid_total += amount
            inv_by[code]["paid_total"] += amount
        else:
            owed_total += amount
            inv_by[code]["owed_total"] += amount

    quotes = (
        Quote.query.filter(Quote.date >= start, Quote.date < end)
        .order_by(Quote.date.desc())
        .all()
    )
    quote_owed_total = 0.0
    quote_paid_total = 0.0
    quote_by = defaultdict(_new_currency_bucket)
    for quote in quotes:
        amount = float(quote.total_amount or 0)
        code = (getattr(quote, "currency", None) or DEFAULT_CURRENCY).upper()
        quote_by[code]["count"] += 1
        if quote.converted_invoice_id:
            inv = quote.converted_invoice or db.session.get(
                Invoice, quote.converted_invoice_id
            )
            if inv and inv.paid:
                quote_paid_total += amount
                quote_by[code]["paid_total"] += amount
            else:
                quote_owed_total += amount
                quote_by[code]["owed_total"] += amount
        else:
            quote_owed_total += amount
            quote_by[code]["owed_total"] += amount

    end_inclusive = end - timedelta(seconds=1)
    return {
        "range_start": start.strftime("%Y-%m-%d"),
        "range_end": end_inclusive.strftime("%Y-%m-%d"),
        "invoices": {
            "count": len(invoices),
            "owed_total": round(owed_total, 2),
            "paid_total": round(paid_total, 2),
            "by_currency": _finalize_currency_map(inv_by),
        },
        "quotes": {
            "count": len(quotes),
            "owed_total": round(quote_owed_total, 2),
            "paid_total": round(quote_paid_total, 2),
            "by_currency": _finalize_currency_map(quote_by),
        },
    }


def _net_subtotal_from_items(items):
    total = 0.0
    for it in items:
        if isinstance(it, dict):
            total += float(it["amount"])
        else:
            total += float(it.amount)
    return round(total, 2)


def _vat_amount_and_total(net_subtotal: float, vat_applies: bool, vat_rate_percent):
    if not vat_applies or vat_rate_percent is None:
        return 0.0, round(float(net_subtotal), 2)
    rate = float(vat_rate_percent)
    vat = round(net_subtotal * rate / 100.0, 2)
    return vat, round(net_subtotal + vat, 2)


def _invoice_dict(inv: Invoice):
    subtotal = _net_subtotal_from_items(inv.items)
    currency = (getattr(inv, "currency", None) or DEFAULT_CURRENCY).upper()
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "date": inv.date.strftime("%Y-%m-%d"),
        "client": _client_json(inv.client),
        "items": [
            {"description": item.description, "amount": item.amount} for item in inv.items
        ],
        "subtotal_net": subtotal,
        "vat_applies": bool(inv.vat_applies),
        "vat_rate_percent": inv.vat_rate_percent,
        "vat_amount": float(inv.vat_amount or 0.0),
        "total_amount": inv.total_amount,
        "paid": inv.paid,
        "currency": currency,
        "currency_symbol": _currency_symbol(currency),
        "job_description": getattr(inv, "job_description", None) or "",
    }


def _quote_dict(quote: Quote):
    subtotal = _net_subtotal_from_items(quote.items)
    currency = (getattr(quote, "currency", None) or DEFAULT_CURRENCY).upper()
    return {
        "id": quote.id,
        "quote_number": quote.quote_number,
        "date": quote.date.strftime("%Y-%m-%d"),
        "client": _client_json(quote.client),
        "items": [
            {"description": item.description, "amount": item.amount} for item in quote.items
        ],
        "subtotal_net": subtotal,
        "vat_applies": bool(quote.vat_applies),
        "vat_rate_percent": quote.vat_rate_percent,
        "vat_amount": float(quote.vat_amount or 0.0),
        "total_amount": quote.total_amount,
        "currency": currency,
        "currency_symbol": _currency_symbol(currency),
        "job_description": getattr(quote, "job_description", None) or "",
        "converted_invoice_id": quote.converted_invoice_id,
    }


def _parse_vat_from_payload(data: dict):
    vat_applies = bool(data.get("vat_applies", False))
    raw_rate = data.get("vat_rate_percent")
    rate = None
    if vat_applies:
        try:
            rate = float(raw_rate if raw_rate is not None else 20.0)
        except (TypeError, ValueError):
            return None, None, "Invalid VAT rate"
        if rate < 0 or rate > 100:
            return None, None, "VAT rate must be between 0 and 100"
    return vat_applies, rate, None


def _parse_line_items(items_data):
    if not items_data:
        return None, "At least one line item is required"
    parsed = []
    for item_data in items_data:
        if not isinstance(item_data, dict):
            return None, "Invalid line item"
        desc = (item_data.get("description") or "").strip()
        if not desc:
            return None, "Each line item needs a description"
        raw_amount = item_data.get("amount")
        if raw_amount is None:
            return None, "Each line item needs a valid amount"
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            return None, "Invalid amount on a line item"
        parsed.append({"description": desc, "amount": amount})
    return parsed, None


def _client_json(client):
    return {
        "id": client.id,
        "name": client.name,
        "email": client.email,
        "address": client.address or "",
    }


def _invoice_prefix(client_name: str) -> str:
    name_parts = (client_name or "").split()
    if len(name_parts) >= 3:
        business_words = [word for word in name_parts if word and word[0].isupper()]
        if len(business_words) >= 3:
            prefix = "".join(word[0] for word in business_words[:3]).upper()
            if "Saturday Love Funk" in client_name:
                prefix = "SLF"
            return prefix

    if not name_parts:
        return "INV"

    prefix = "".join(c for c in name_parts[0][:3] if c.isalpha()).upper()
    prefix = (prefix + "XXX")[:3]
    return prefix


_INVOICE_NUM_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _parse_invoice_number(num: str):
    m = _INVOICE_NUM_RE.match((num or "").strip())
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def _invoice_prefix_for_client(client: Client) -> str:
    """Use the letter prefix from this client's highest numbered invoice, if any."""
    rows = (
        db.session.query(Invoice.invoice_number)
        .filter(Invoice.client_id == client.id)
        .all()
    )
    best_suffix = -1
    best_prefix = None
    for (num,) in rows:
        parsed = _parse_invoice_number(num)
        if not parsed:
            continue
        prefix, suffix = parsed
        if suffix > best_suffix:
            best_suffix = suffix
            best_prefix = prefix
    if best_prefix:
        return best_prefix
    return _invoice_prefix(client.name)


def _format_next_invoice_number(prefix: str, next_suffix: int, existing_numbers: list) -> str:
    width = 1
    prefix_upper = prefix.upper()
    for num in existing_numbers:
        parsed = _parse_invoice_number(num)
        if parsed and parsed[0].upper() == prefix_upper:
            width = max(width, len(num) - len(parsed[0]))
    next_str = str(next_suffix)
    if len(next_str) < width:
        next_str = next_str.zfill(width)
    return f"{prefix}{next_str}"


def generate_invoice_number(client: Client) -> str:
    """
    Generate the next invoice number for a client.

    Follows the letter prefix from existing invoices (e.g. TOX200 -> TOX201).
    Falls back to a name-based prefix when the client has no invoices yet.
    """
    prefix = _invoice_prefix_for_client(client)
    rows = (
        db.session.query(Invoice.invoice_number)
        .filter(Invoice.client_id == client.id)
        .all()
    )
    numbers = [num for (num,) in rows]
    prefix_upper = prefix.upper()
    max_suffix = 0
    has_prefix = False
    for num in numbers:
        parsed = _parse_invoice_number(num)
        if parsed and parsed[0].upper() == prefix_upper:
            has_prefix = True
            max_suffix = max(max_suffix, parsed[1])
    if not has_prefix:
        return f"{prefix}001"
    return _format_next_invoice_number(prefix, max_suffix + 1, numbers)


def _resolve_new_invoice_number(client: Client, custom: str | None):
    custom = (custom or "").strip()
    if custom:
        exists = (
            db.session.query(Invoice.id)
            .filter(Invoice.invoice_number == custom)
            .first()
        )
        if exists:
            return None, "Invoice number already exists"
        return custom, None
    return generate_invoice_number(client), None


def generate_quote_number(client: Client) -> str:
    prefix = _invoice_prefix(client.name)
    q_prefix = f"{prefix}Q"
    existing = (
        db.session.query(Quote.quote_number)
        .filter(Quote.client_id == client.id)
        .filter(Quote.quote_number.like(f"{q_prefix}%"))
        .all()
    )

    max_suffix = 0
    for (num,) in existing:
        if not num or not num.startswith(q_prefix):
            continue
        suffix = num[len(q_prefix) :]
        if suffix.isdigit():
            max_suffix = max(max_suffix, int(suffix))

    return f"{q_prefix}{(max_suffix + 1):03d}"


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/hub/summary")
def hub_summary():
    if not _hub_token_configured():
        return jsonify({"error": "HUB_API_TOKEN is not configured"}), 503
    if not _hub_token_ok():
        return jsonify({"error": "Unauthorized"}), 401

    period, start, end = _period_range("month")
    invoices = Invoice.query.all()
    unpaid = [inv for inv in invoices if not inv.paid]
    owed = round(sum(float(inv.total_amount or 0) for inv in unpaid), 2)
    in_period = [inv for inv in invoices if inv.date and start <= inv.date < end]
    paid = round(
        sum(float(inv.total_amount or 0) for inv in in_period if inv.paid), 2
    )
    return jsonify(
        {
            "owed": owed,
            "paid": paid,
            "unpaidCount": len(unpaid),
            "invoicesInPeriod": len(in_period),
            "period": period,
        }
    )


@app.route("/api/hub/clients")
def hub_clients():
    if not _hub_token_configured():
        return jsonify({"error": "HUB_API_TOKEN is not configured"}), 503
    if not _hub_token_ok():
        return jsonify({"error": "Unauthorized"}), 401

    clients = Client.query.order_by(Client.name.asc()).all()
    unpaid_by_client = defaultdict(float)
    for inv in Invoice.query.filter_by(paid=False).all():
        unpaid_by_client[inv.client_id] += float(inv.total_amount or 0)

    return jsonify(
        {
            "clients": [
                {
                    "id": _hub_client_id(client),
                    "name": client.name,
                    "unpaidTotal": round(unpaid_by_client.get(client.id, 0.0), 2),
                }
                for client in clients
            ]
        }
    )


@app.route("/api/hub/invoices")
def hub_invoices():
    if not _hub_token_configured():
        return jsonify({"error": "HUB_API_TOKEN is not configured"}), 503
    if not _hub_token_ok():
        return jsonify({"error": "Unauthorized"}), 401

    client_id = (request.args.get("clientId") or "").strip()
    query = Invoice.query.order_by(Invoice.date.desc())
    if client_id:
        try:
            cid = int(client_id)
        except ValueError:
            return jsonify({"invoices": []})
        query = query.filter(Invoice.client_id == cid)

    rows = query.all()
    return jsonify(
        {
            "invoices": [
                {
                    "id": str(inv.id),
                    "number": inv.invoice_number,
                    "clientId": _hub_client_id(inv.client) if inv.client else "",
                    "clientName": inv.client.name if inv.client else "",
                    "amount": round(float(inv.total_amount or 0), 2),
                    "status": "paid" if inv.paid else "unpaid",
                    "date": inv.date.strftime("%Y-%m-%d") if inv.date else "",
                }
                for inv in rows
            ]
        }
    )


@app.context_processor
def inject_company():
    company = _company_config()
    company["logo_path"] = _company_logo_url(company["logo_file"])
    return {"company": company, "currencies": CURRENCIES}


def _hub_token_configured() -> bool:
    return bool((os.environ.get("HUB_API_TOKEN") or "").strip())


def _hub_token_ok() -> bool:
    expected = (os.environ.get("HUB_API_TOKEN") or "").strip()
    if not expected:
        return False
    header = request.headers.get("Authorization") or ""
    token = header[7:].strip() if header.startswith("Bearer ") else ""
    if not token:
        return False
    return hmac.compare_digest(token, expected)


def _hub_client_id(client: Client) -> str:
    """Stable id for hub linking (store this as invoiceClientId in the hub)."""
    return str(client.id)


@app.before_request
def _require_login():
    # Hub read API uses Bearer HUB_API_TOKEN instead of session login.
    if request.path.startswith("/api/hub/"):
        return None
    if not _auth_enabled():
        return None
    if request.endpoint in (None, "static", "health", "login", "logout"):
        return None
    if session.get("user_id"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _auth_enabled():
        return redirect(url_for("index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            nxt = request.args.get("next") or ""
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid username or password"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    if _auth_enabled():
        return redirect(url_for("login"))
    return redirect(url_for("index"))


@app.route("/")
def index():
    return render_template("index.html", auth_enabled=_auth_enabled())


@app.route("/api/summary")
def api_summary():
    period = (request.args.get("period") or "month").strip().lower()
    period, start, end = _period_range(period)
    summary = _build_period_summary(start, end)
    summary["period"] = period
    return jsonify(summary)


@app.route("/api/reports")
def api_reports():
    period = (request.args.get("period") or "month").strip().lower()
    period, start, end = _period_range(period)

    rows = (
        Invoice.query.filter(Invoice.date >= start, Invoice.date < end)
        .order_by(Invoice.date.desc())
        .all()
    )
    total_invoiced = sum(float(inv.total_amount or 0) for inv in rows)
    paid_total = sum(float(inv.total_amount or 0) for inv in rows if inv.paid)
    unpaid_total = total_invoiced - paid_total
    end_inclusive = end - timedelta(seconds=1)

    period_summary = _build_period_summary(start, end)
    quote_summary = period_summary["quotes"]
    invoice_summary = period_summary["invoices"]

    return jsonify(
        {
            "period": period,
            "range_start": start.strftime("%Y-%m-%d"),
            "range_end": end_inclusive.strftime("%Y-%m-%d"),
            "invoice_count": len(rows),
            "total_invoiced": round(total_invoiced, 2),
            "paid_total": round(paid_total, 2),
            "unpaid_total": round(unpaid_total, 2),
            "quote_count": quote_summary["count"],
            "quote_owed_total": quote_summary["owed_total"],
            "quote_paid_total": quote_summary["paid_total"],
            "invoices_by_currency": invoice_summary.get("by_currency") or {},
            "quotes_by_currency": quote_summary.get("by_currency") or {},
            "invoices": [
                {
                    "id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "date": inv.date.strftime("%Y-%m-%d"),
                    "client_name": inv.client.name,
                    "total_amount": inv.total_amount,
                    "paid": inv.paid,
                    "currency": (getattr(inv, "currency", None) or DEFAULT_CURRENCY),
                }
                for inv in rows
            ],
        }
    )


@app.route("/api/clients", methods=["GET", "POST"])
def handle_clients():
    if request.method == "POST":
        data = request.json or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        if not name or not email:
            return jsonify({"error": "Name and email are required"}), 400
        new_client = Client(
            name=name,
            email=email,
            address=(data.get("address") or "").strip(),
        )
        db.session.add(new_client)
        db.session.commit()
        return jsonify({"id": new_client.id, "message": "Client created successfully"})

    clients = Client.query.order_by(Client.name.asc()).all()
    return jsonify([_client_json(c) for c in clients])


@app.route("/api/clients/<int:client_id>", methods=["GET", "PUT"])
def handle_client(client_id):
    """Update client details only. Quotes and invoices stay linked by client_id."""
    client = db.session.get(Client, client_id)
    if not client:
        return jsonify({"error": "Not found"}), 404

    if request.method == "GET":
        return jsonify(_client_json(client))

    data = request.json or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    client.name = name
    client.email = email
    client.address = (data.get("address") or "").strip()
    db.session.commit()
    return jsonify({"id": client.id, "message": "Client updated successfully", **_client_json(client)})


@app.route("/api/clients/<int:client_id>/next-invoice-number")
def next_invoice_number(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"invoice_number": generate_invoice_number(client)})


@app.route("/api/invoices", methods=["GET", "POST"])
def handle_invoices():
    if request.method == "POST":
        data = request.json or {}
        client = db.session.get(Client, data.get("client_id"))
        if not client:
            return jsonify({"error": "Client not found"}), 404

        client_folder = os.path.join(
            app.config["INVOICE_FOLDER"], client.name.replace(" ", "_")
        )
        if not os.path.exists(client_folder):
            os.makedirs(client_folder)

        vat_applies, vat_rate, vat_err = _parse_vat_from_payload(data)
        if vat_err:
            return jsonify({"error": vat_err}), 400

        currency, currency_err = _parse_currency(data)
        if currency_err:
            return jsonify({"error": currency_err}), 400
        job_description, _ = _parse_job_description(data, required_key=True)

        inv_number, num_err = _resolve_new_invoice_number(
            client, data.get("invoice_number")
        )
        if num_err:
            return jsonify({"error": num_err}), 409

        new_invoice = Invoice(
            invoice_number=inv_number,
            client_id=client.id,
            date=datetime.utcnow(),
            vat_applies=vat_applies,
            vat_rate_percent=vat_rate if vat_applies else None,
            currency=currency,
            job_description=job_description or None,
        )

        for item_data in data.get("items", []):
            item = InvoiceItem(
                description=item_data["description"],
                amount=float(item_data["amount"]),
            )
            new_invoice.items.append(item)

        net = _net_subtotal_from_items(new_invoice.items)
        vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
        new_invoice.vat_amount = vat_amt if vat_applies else 0.0
        new_invoice.total_amount = gross
        db.session.add(new_invoice)
        db.session.commit()

        return jsonify(
            {
                "id": new_invoice.id,
                "invoice_number": new_invoice.invoice_number,
                "client_name": client.name,
                "message": "Invoice created successfully",
            }
        )

    invoices = Invoice.query.order_by(Invoice.date.desc()).all()
    return jsonify([_invoice_dict(inv) for inv in invoices])


@app.route("/api/invoices/<int:invoice_id>", methods=["GET", "PUT", "DELETE"])
def handle_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({"error": "Not found"}), 404

    if request.method == "GET":
        return jsonify(_invoice_dict(invoice))

    if request.method == "PUT":
        data = request.json or {}
        new_number = (data.get("invoice_number") or "").strip()
        if new_number and new_number != invoice.invoice_number:
            exists = (
                db.session.query(Invoice.id)
                .filter(Invoice.invoice_number == new_number)
                .filter(Invoice.id != invoice.id)
                .first()
            )
            if exists:
                return jsonify({"error": "Invoice number already exists"}), 409
            invoice.invoice_number = new_number

        merged = {**data}
        if "vat_applies" not in merged:
            merged["vat_applies"] = invoice.vat_applies
        if (
            merged.get("vat_applies")
            and merged.get("vat_rate_percent") is None
            and invoice.vat_rate_percent is not None
        ):
            merged["vat_rate_percent"] = invoice.vat_rate_percent

        vat_applies, vat_rate, vat_err = _parse_vat_from_payload(merged)
        if vat_err:
            return jsonify({"error": vat_err}), 400
        invoice.vat_applies = vat_applies
        invoice.vat_rate_percent = vat_rate if vat_applies else None

        if "currency" in data:
            currency, currency_err = _parse_currency(data)
            if currency_err:
                return jsonify({"error": currency_err}), 400
            invoice.currency = currency
        if "job_description" in data:
            job_description, _ = _parse_job_description(data)
            invoice.job_description = job_description or None

        parsed_items, items_err = _parse_line_items(data.get("items"))
        if items_err:
            return jsonify({"error": items_err}), 400

        InvoiceItem.query.filter_by(invoice_id=invoice.id).delete()

        items_buffer = []
        for item_data in parsed_items:
            item = InvoiceItem(
                description=item_data["description"],
                amount=item_data["amount"],
                invoice_id=invoice.id,
            )
            items_buffer.append(item)
            db.session.add(item)

        net = _net_subtotal_from_items(
            [{"amount": i.amount, "description": i.description} for i in items_buffer]
        )
        vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
        invoice.vat_amount = vat_amt if vat_applies else 0.0
        invoice.total_amount = gross
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        return jsonify({"message": "Invoice updated successfully"})

    InvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
    db.session.delete(invoice)
    db.session.commit()
    return jsonify({"message": "Invoice deleted successfully"})


@app.route("/download_invoice/<int:invoice_id>")
def download_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({"error": "Not found"}), 404
    client_folder = os.path.join(
        app.config["INVOICE_FOLDER"], invoice.client.name.replace(" ", "_")
    )
    filename = f"{invoice.invoice_number}_{invoice.date.strftime('%Y%m%d')}.pdf"
    filepath = os.path.join(client_folder, filename)

    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({"error": "Invoice file not found"}), 404


@app.route("/api/invoices/<int:invoice_id>/paid", methods=["PUT"])
def toggle_paid_status(invoice_id):
    try:
        data = request.get_json() or {}
        paid = bool(data.get("paid", False))

        invoice = db.session.get(Invoice, invoice_id)
        if not invoice:
            return jsonify({"success": False, "error": "Not found"}), 404

        invoice.paid = paid
        db.session.commit()

        return jsonify({"success": True, "paid": invoice.paid})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/invoices/<int:invoice_id>/send", methods=["POST"])
def send_invoice_email(invoice_id):
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    if not api_key or not from_email:
        return jsonify(
            {
                "success": False,
                "error": "RESEND_API_KEY and RESEND_FROM_EMAIL must be set on the server.",
            }
        ), 503

    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({"success": False, "error": "Invoice not found"}), 404

    client = invoice.client
    if not (client.email or "").strip():
        return jsonify({"success": False, "error": "Client has no email address"}), 400

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if len(message) > 4000:
        message = message[:4000]

    try:
        import resend

        resend.api_key = api_key
        logo_url = _company_logo_url(_company_config()["logo_file"], request.url_root)
        html = render_template(
            "email_invoice.html",
            invoice=invoice,
            message=message or None,
            logo_url=logo_url,
            subtotal_net=_net_subtotal_from_items(invoice.items),
            currency_symbol=_currency_symbol(invoice.currency),
        )
        params = {
            "from": from_email,
            "to": [client.email.strip()],
            "subject": f"Invoice {invoice.invoice_number}",
            "html": html,
        }
        result = resend.Emails.send(params)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True, "id": result.get("id") if isinstance(result, dict) else None})


@app.route("/api/invoices/<int:invoice_id>/duplicate", methods=["POST"])
def duplicate_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({"success": False, "error": "Invoice not found"}), 404

    client = invoice.client
    if not client:
        return jsonify({"success": False, "error": "Client not found"}), 404

    vat_applies = bool(invoice.vat_applies)
    vat_rate = invoice.vat_rate_percent if vat_applies else None

    new_invoice = Invoice(
        invoice_number=generate_invoice_number(client),
        client_id=client.id,
        date=datetime.utcnow(),
        paid=False,
        vat_applies=vat_applies,
        vat_rate_percent=vat_rate if vat_applies else None,
        currency=invoice.currency or DEFAULT_CURRENCY,
        job_description=invoice.job_description,
    )

    for item in invoice.items:
        new_item = InvoiceItem(description=item.description, amount=float(item.amount))
        new_invoice.items.append(new_item)

    net = _net_subtotal_from_items(new_invoice.items)
    vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
    new_invoice.vat_amount = vat_amt if vat_applies else 0.0
    new_invoice.total_amount = gross
    db.session.add(new_invoice)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "id": new_invoice.id,
            "invoice_number": new_invoice.invoice_number,
            "client_name": client.name,
        }
    )


@app.route("/api/quotes", methods=["GET", "POST"])
def handle_quotes():
    if request.method == "POST":
        data = request.json or {}
        client = db.session.get(Client, data.get("client_id"))
        if not client:
            return jsonify({"error": "Client not found"}), 404

        vat_applies, vat_rate, vat_err = _parse_vat_from_payload(data)
        if vat_err:
            return jsonify({"error": vat_err}), 400

        currency, currency_err = _parse_currency(data)
        if currency_err:
            return jsonify({"error": currency_err}), 400
        job_description, _ = _parse_job_description(data, required_key=True)

        new_quote = Quote(
            quote_number=generate_quote_number(client),
            client_id=client.id,
            date=datetime.utcnow(),
            vat_applies=vat_applies,
            vat_rate_percent=vat_rate if vat_applies else None,
            currency=currency,
            job_description=job_description or None,
        )

        for item_data in data.get("items", []):
            new_quote.items.append(
                QuoteItem(
                    description=item_data["description"],
                    amount=float(item_data["amount"]),
                )
            )

        net = _net_subtotal_from_items(new_quote.items)
        vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
        new_quote.vat_amount = vat_amt if vat_applies else 0.0
        new_quote.total_amount = gross
        db.session.add(new_quote)
        db.session.commit()

        return jsonify(
            {
                "id": new_quote.id,
                "quote_number": new_quote.quote_number,
                "client_name": client.name,
                "message": "Quote created successfully",
            }
        )

    quotes = Quote.query.order_by(Quote.date.desc()).all()
    return jsonify([_quote_dict(q) for q in quotes])


@app.route("/api/quotes/<int:quote_id>", methods=["GET", "PUT", "DELETE"])
def handle_quote(quote_id):
    quote = db.session.get(Quote, quote_id)
    if not quote:
        return jsonify({"error": "Not found"}), 404

    if request.method == "GET":
        return jsonify(_quote_dict(quote))

    if request.method == "PUT":
        data = request.json or {}
        new_number = (data.get("quote_number") or "").strip()
        if new_number and new_number != quote.quote_number:
            exists = (
                db.session.query(Quote.id)
                .filter(Quote.quote_number == new_number)
                .filter(Quote.id != quote.id)
                .first()
            )
            if exists:
                return jsonify({"error": "Quote number already exists"}), 409
            quote.quote_number = new_number

        merged = {**data}
        if "vat_applies" not in merged:
            merged["vat_applies"] = quote.vat_applies
        if (
            merged.get("vat_applies")
            and merged.get("vat_rate_percent") is None
            and quote.vat_rate_percent is not None
        ):
            merged["vat_rate_percent"] = quote.vat_rate_percent

        vat_applies, vat_rate, vat_err = _parse_vat_from_payload(merged)
        if vat_err:
            return jsonify({"error": vat_err}), 400
        quote.vat_applies = vat_applies
        quote.vat_rate_percent = vat_rate if vat_applies else None

        if "currency" in data:
            currency, currency_err = _parse_currency(data)
            if currency_err:
                return jsonify({"error": currency_err}), 400
            quote.currency = currency
        if "job_description" in data:
            job_description, _ = _parse_job_description(data)
            quote.job_description = job_description or None

        parsed_items, items_err = _parse_line_items(data.get("items"))
        if items_err:
            return jsonify({"error": items_err}), 400

        QuoteItem.query.filter_by(quote_id=quote.id).delete()

        items_buffer = []
        for item_data in parsed_items:
            item = QuoteItem(
                description=item_data["description"],
                amount=item_data["amount"],
                quote_id=quote.id,
            )
            items_buffer.append(item)
            db.session.add(item)

        net = _net_subtotal_from_items(
            [{"amount": i.amount, "description": i.description} for i in items_buffer]
        )
        vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
        quote.vat_amount = vat_amt if vat_applies else 0.0
        quote.total_amount = gross
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        return jsonify({"message": "Quote updated successfully"})

    QuoteItem.query.filter_by(quote_id=quote.id).delete()
    db.session.delete(quote)
    db.session.commit()
    return jsonify({"message": "Quote deleted successfully"})


@app.route("/api/quotes/<int:quote_id>/send", methods=["POST"])
def send_quote_email(quote_id):
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    if not api_key or not from_email:
        return jsonify(
            {
                "success": False,
                "error": "RESEND_API_KEY and RESEND_FROM_EMAIL must be set on the server.",
            }
        ), 503

    quote = db.session.get(Quote, quote_id)
    if not quote:
        return jsonify({"success": False, "error": "Quote not found"}), 404

    client = quote.client
    if not (client.email or "").strip():
        return jsonify({"success": False, "error": "Client has no email address"}), 400

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if len(message) > 4000:
        message = message[:4000]

    try:
        import resend

        resend.api_key = api_key
        logo_url = _company_logo_url(_company_config()["logo_file"], request.url_root)
        html = render_template(
            "email_quote.html",
            quote=quote,
            message=message or None,
            logo_url=logo_url,
            subtotal_net=_net_subtotal_from_items(quote.items),
            currency_symbol=_currency_symbol(quote.currency),
        )
        params = {
            "from": from_email,
            "to": [client.email.strip()],
            "subject": f"Quote {quote.quote_number}",
            "html": html,
        }
        result = resend.Emails.send(params)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True, "id": result.get("id") if isinstance(result, dict) else None})


@app.route("/api/quotes/<int:quote_id>/duplicate", methods=["POST"])
def duplicate_quote(quote_id):
    quote = db.session.get(Quote, quote_id)
    if not quote:
        return jsonify({"success": False, "error": "Quote not found"}), 404

    client = quote.client
    if not client:
        return jsonify({"success": False, "error": "Client not found"}), 404

    vat_applies = bool(quote.vat_applies)
    vat_rate = quote.vat_rate_percent if vat_applies else None

    new_quote = Quote(
        quote_number=generate_quote_number(client),
        client_id=client.id,
        date=datetime.utcnow(),
        vat_applies=vat_applies,
        vat_rate_percent=vat_rate if vat_applies else None,
        currency=quote.currency or DEFAULT_CURRENCY,
        job_description=quote.job_description,
    )

    for item in quote.items:
        new_quote.items.append(
            QuoteItem(description=item.description, amount=float(item.amount))
        )

    net = _net_subtotal_from_items(new_quote.items)
    vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
    new_quote.vat_amount = vat_amt if vat_applies else 0.0
    new_quote.total_amount = gross
    db.session.add(new_quote)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "id": new_quote.id,
            "quote_number": new_quote.quote_number,
            "client_name": client.name,
        }
    )


@app.route("/api/quotes/<int:quote_id>/convert-to-invoice", methods=["POST"])
def convert_quote_to_invoice(quote_id):
    quote = db.session.get(Quote, quote_id)
    if not quote:
        return jsonify({"success": False, "error": "Quote not found"}), 404

    client = quote.client
    if not client:
        return jsonify({"success": False, "error": "Client not found"}), 404

    client_folder = os.path.join(
        app.config["INVOICE_FOLDER"], client.name.replace(" ", "_")
    )
    if not os.path.exists(client_folder):
        os.makedirs(client_folder)

    vat_applies = bool(quote.vat_applies)
    vat_rate = quote.vat_rate_percent if vat_applies else None

    new_invoice = Invoice(
        invoice_number=generate_invoice_number(client),
        client_id=client.id,
        date=datetime.utcnow(),
        paid=False,
        vat_applies=vat_applies,
        vat_rate_percent=vat_rate if vat_applies else None,
        currency=quote.currency or DEFAULT_CURRENCY,
        job_description=quote.job_description,
    )

    for item in quote.items:
        new_invoice.items.append(
            InvoiceItem(description=item.description, amount=float(item.amount))
        )

    net = _net_subtotal_from_items(new_invoice.items)
    vat_amt, gross = _vat_amount_and_total(net, vat_applies, vat_rate)
    new_invoice.vat_amount = vat_amt if vat_applies else 0.0
    new_invoice.total_amount = gross
    db.session.add(new_invoice)
    db.session.flush()
    quote.converted_invoice_id = new_invoice.id
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "id": new_invoice.id,
            "invoice_number": new_invoice.invoice_number,
            "client_name": client.name,
            "quote_number": quote.quote_number,
        }
    )


def _settings_json():
    company = _company_config()
    company["logo_path"] = _company_logo_url(company["logo_file"])
    return company


@app.route("/api/settings", methods=["GET", "PUT"])
def handle_settings():
    if request.method == "GET":
        return jsonify(_settings_json())

    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Business name is required"}), 400

    address = (data.get("address") or "").strip()
    phone = (data.get("phone") or "").strip()
    bank_name = (data.get("bank_name") or "").strip() or name
    bank_account = (data.get("bank_account") or "").strip()
    bank_sort = (data.get("bank_sort") or "").strip()
    payment_terms = (data.get("payment_terms") or "").strip() or (
        "Payment is due on receipt of invoice"
    )
    app_title = (data.get("app_title") or "").strip() or "Invoices & quotes"

    row = CompanySettings.query.order_by(CompanySettings.id.asc()).first()
    if not row:
        row = CompanySettings()
        db.session.add(row)

    row.name = name
    row.address = address
    row.phone = phone
    row.bank_name = bank_name
    row.bank_account = bank_account
    row.bank_sort = bank_sort
    row.payment_terms = payment_terms
    row.app_title = app_title
    db.session.commit()
    return jsonify(_settings_json())


# Ensure tables exist (Railway runs gunicorn, not run.py — create_all is idempotent)
with app.app_context():
    db.create_all()
    _ensure_invoice_vat_columns()
    _ensure_quote_converted_column()
    _ensure_currency_and_job_columns()
    _bootstrap_auth_user()


if __name__ == "__main__":
    app.run(debug=True)
