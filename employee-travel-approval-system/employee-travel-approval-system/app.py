"""Employee Travel Approval System - simple base project (Flask + SQLite).

Roles
-----
employee : submits travel requests, tracks status, cancels pending requests
manager  : approves / rejects requests from direct reports
admin    : sees every request, can decide any request, manages users
"""
import os
import secrets
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["DATABASE"] = os.path.join(BASE_DIR, "travel_approval.db")

TRAVEL_MODES = ["Flight", "Train", "Bus", "Car", "Other"]
STATUSES = ["Pending", "Approved", "Rejected", "Cancelled"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'admin')),
    department    TEXT,
    manager_id    INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS travel_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id      INTEGER NOT NULL REFERENCES users(id),
    destination      TEXT NOT NULL,
    purpose          TEXT NOT NULL,
    start_date       TEXT NOT NULL,
    end_date         TEXT NOT NULL,
    travel_mode      TEXT NOT NULL,
    estimated_cost   REAL NOT NULL,
    status           TEXT NOT NULL DEFAULT 'Pending',
    manager_comment  TEXT,
    decided_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL,
    decided_at       TEXT
);
"""


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables and seed demo users when the database is empty."""
    db = get_db()
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role, department) "
            "VALUES (?, ?, ?, 'admin', 'Administration')",
            ("System Admin", "admin@company.com", generate_password_hash("admin123")),
        )
        db.execute(
            "INSERT INTO users (name, email, password_hash, role, department) "
            "VALUES (?, ?, ?, 'manager', 'Engineering')",
            ("Maya Manager", "manager@company.com", generate_password_hash("manager123")),
        )
        manager_id = db.execute(
            "SELECT id FROM users WHERE email = 'manager@company.com'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO users (name, email, password_hash, role, department, manager_id) "
            "VALUES (?, ?, ?, 'employee', 'Engineering', ?)",
            ("Eli Employee", "employee@company.com",
             generate_password_hash("employee123"), manager_id),
        )
        db.commit()


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------
@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST" and not app.config.get("TESTING"):
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Invalid or missing CSRF token.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can_view(req):
    """Owner, the owner's manager, or an admin may view a request."""
    if g.user["role"] == "admin" or req["employee_id"] == g.user["id"]:
        return True
    return g.user["role"] == "manager" and req["owner_manager_id"] == g.user["id"]


def get_request_or_404(request_id):
    row = get_db().execute(
        "SELECT r.*, u.name AS employee_name, u.email AS employee_email, "
        "u.department AS department, u.manager_id AS owner_manager_id, "
        "d.name AS decided_by_name "
        "FROM travel_requests r "
        "JOIN users u ON u.id = r.employee_id "
        "LEFT JOIN users d ON d.id = r.decided_by "
        "WHERE r.id = ?", (request_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


# --------------------------------------------------------------------------
# Routes: auth
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("dashboard") if g.user else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    managers = db.execute(
        "SELECT id, name, department FROM users WHERE role = 'manager' ORDER BY name"
    ).fetchall()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department = request.form.get("department", "").strip()
        manager_id = request.form.get("manager_id", type=int)

        error = None
        if not name or not email or not password:
            error = "Name, email and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif manager_id not in [m["id"] for m in managers]:
            error = "Please choose a valid manager."
        elif db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            error = "That email is already registered."

        if error:
            flash(error, "error")
        else:
            db.execute(
                "INSERT INTO users (name, email, password_hash, role, department, manager_id) "
                "VALUES (?, ?, ?, 'employee', ?, ?)",
                (name, email, generate_password_hash(password), department, manager_id),
            )
            db.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", managers=managers)


# --------------------------------------------------------------------------
# Routes: dashboards
# --------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    role = g.user["role"]

    if role == "employee":
        rows = db.execute(
            "SELECT * FROM travel_requests WHERE employee_id = ? ORDER BY id DESC",
            (g.user["id"],),
        ).fetchall()
        return render_template("employee_dashboard.html", requests=rows)

    if role == "manager":
        base = (
            "SELECT r.*, u.name AS employee_name FROM travel_requests r "
            "JOIN users u ON u.id = r.employee_id WHERE u.manager_id = ? "
        )
        pending = db.execute(base + "AND r.status = 'Pending' ORDER BY r.id", (g.user["id"],)).fetchall()
        history = db.execute(base + "AND r.status != 'Pending' ORDER BY r.id DESC", (g.user["id"],)).fetchall()
        return render_template("manager_dashboard.html", pending=pending, history=history)

    # admin
    counts = {s: 0 for s in STATUSES}
    for row in db.execute("SELECT status, COUNT(*) AS n FROM travel_requests GROUP BY status"):
        counts[row["status"]] = row["n"]
    status_filter = request.args.get("status", "")
    query = (
        "SELECT r.*, u.name AS employee_name FROM travel_requests r "
        "JOIN users u ON u.id = r.employee_id "
    )
    params = ()
    if status_filter in STATUSES:
        query += "WHERE r.status = ? "
        params = (status_filter,)
    rows = db.execute(query + "ORDER BY r.id DESC", params).fetchall()
    total_approved = db.execute(
        "SELECT COALESCE(SUM(estimated_cost), 0) FROM travel_requests WHERE status = 'Approved'"
    ).fetchone()[0]
    return render_template(
        "admin_dashboard.html", requests=rows, counts=counts,
        statuses=STATUSES, status_filter=status_filter, total_approved=total_approved,
    )


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    users = get_db().execute(
        "SELECT u.*, m.name AS manager_name FROM users u "
        "LEFT JOIN users m ON m.id = u.manager_id ORDER BY u.role, u.name"
    ).fetchall()
    return render_template("admin_users.html", users=users)


# --------------------------------------------------------------------------
# Routes: travel requests
# --------------------------------------------------------------------------
@app.route("/requests/new", methods=["GET", "POST"])
@role_required("employee")
def new_request():
    if request.method == "POST":
        destination = request.form.get("destination", "").strip()
        purpose = request.form.get("purpose", "").strip()
        start = request.form.get("start_date", "")
        end = request.form.get("end_date", "")
        mode = request.form.get("travel_mode", "")
        cost_raw = request.form.get("estimated_cost", "")

        error = None
        try:
            start_d = datetime.strptime(start, "%Y-%m-%d").date()
            end_d = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            start_d = end_d = None
            error = "Please enter valid start and end dates."
        try:
            cost = float(cost_raw)
        except ValueError:
            cost = None
            error = error or "Estimated cost must be a number."

        if not error:
            if not destination or not purpose:
                error = "Destination and purpose are required."
            elif mode not in TRAVEL_MODES:
                error = "Please choose a travel mode."
            elif start_d < date.today():
                error = "Start date cannot be in the past."
            elif end_d < start_d:
                error = "End date cannot be before the start date."
            elif cost < 0:
                error = "Estimated cost cannot be negative."

        if error:
            flash(error, "error")
            return render_template("new_request.html", modes=TRAVEL_MODES, form=request.form)

        db = get_db()
        cur = db.execute(
            "INSERT INTO travel_requests (employee_id, destination, purpose, start_date, "
            "end_date, travel_mode, estimated_cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (g.user["id"], destination, purpose, start, end, mode, cost,
             datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
        flash("Travel request submitted for approval.", "success")
        return redirect(url_for("request_detail", request_id=cur.lastrowid))
    return render_template("new_request.html", modes=TRAVEL_MODES, form={})


@app.route("/requests/<int:request_id>")
@login_required
def request_detail(request_id):
    req = get_request_or_404(request_id)
    if not can_view(req):
        abort(403)
    can_decide = req["status"] == "Pending" and (
        g.user["role"] == "admin"
        or (g.user["role"] == "manager" and req["owner_manager_id"] == g.user["id"])
    )
    can_cancel = req["status"] == "Pending" and req["employee_id"] == g.user["id"]
    return render_template("request_detail.html", req=req,
                           can_decide=can_decide, can_cancel=can_cancel)


@app.route("/requests/<int:request_id>/decide", methods=["POST"])
@role_required("manager", "admin")
def decide_request(request_id):
    req = get_request_or_404(request_id)
    if g.user["role"] == "manager" and req["owner_manager_id"] != g.user["id"]:
        abort(403)
    if req["status"] != "Pending":
        flash("This request has already been processed.", "error")
        return redirect(url_for("request_detail", request_id=request_id))

    action = request.form.get("action")
    comment = request.form.get("comment", "").strip()
    if action not in ("approve", "reject"):
        abort(400)
    if action == "reject" and not comment:
        flash("Please add a comment explaining the rejection.", "error")
        return redirect(url_for("request_detail", request_id=request_id))

    db = get_db()
    db.execute(
        "UPDATE travel_requests SET status = ?, manager_comment = ?, decided_by = ?, "
        "decided_at = ? WHERE id = ?",
        ("Approved" if action == "approve" else "Rejected", comment, g.user["id"],
         datetime.now().strftime("%Y-%m-%d %H:%M"), request_id),
    )
    db.commit()
    flash(f"Request {'approved' if action == 'approve' else 'rejected'}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/requests/<int:request_id>/cancel", methods=["POST"])
@role_required("employee")
def cancel_request(request_id):
    req = get_request_or_404(request_id)
    if req["employee_id"] != g.user["id"]:
        abort(403)
    if req["status"] != "Pending":
        flash("Only pending requests can be cancelled.", "error")
    else:
        db = get_db()
        db.execute("UPDATE travel_requests SET status = 'Cancelled' WHERE id = ?", (request_id,))
        db.commit()
        flash("Request cancelled.", "success")
    return redirect(url_for("dashboard"))


# --------------------------------------------------------------------------
# Error pages
# --------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, message="You do not have access to this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message=getattr(e, "description", "Bad request.")), 400


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
