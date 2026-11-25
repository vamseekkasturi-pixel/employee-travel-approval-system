# Employee Travel Approval System

A simple base project built with **Python, Flask and SQLite**. Employees submit travel
requests, their reporting manager approves or rejects them, and an admin oversees everything.

## Features

- Role-based login (Employee, Manager, Admin) with hashed passwords
- Employee self-registration (choose a reporting manager)
- Employees: submit a travel request, track status, cancel a pending request
- Managers: see pending requests from their team, approve or reject with a comment
  (a comment is required when rejecting), view decision history
- Admin: all requests with status filter, summary counts, approved budget total,
  can decide any request, user list
- Input validation (dates, cost, travel mode), CSRF protection, access control per request

## Project structure

```
employee-travel-approval-system/
├── app.py               # Flask app: routes, database, auth
├── requirements.txt
├── static/style.css
├── templates/           # Jinja2 HTML templates
└── tests/test_app.py    # Automated tests
```

The SQLite database (`travel_approval.db`) is created automatically on first run.

## Setup and run

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Demo accounts

| Role     | Email                | Password    |
|----------|----------------------|-------------|
| Employee | employee@company.com | employee123 |
| Manager  | manager@company.com  | manager123  |
| Admin    | admin@company.com    | admin123    |

## Run the tests

```bash
python -m unittest discover tests
```

## Approval workflow

1. Employee submits a request, which starts as **Pending**.
2. The employee's manager (or an admin) reviews it and sets **Approved** or **Rejected**.
3. The employee can cancel a request while it is still Pending (**Cancelled**).

## Ideas for extending it

- Multi-level approval (manager, then finance) and approval limits by cost
- Email notifications on submit and decision
- Expense claims after the trip, receipt uploads
- Export reports to Excel or PDF
- Switch to MySQL/PostgreSQL with SQLAlchemy

Before deploying, set a real `SECRET_KEY` environment variable and change the demo passwords.
