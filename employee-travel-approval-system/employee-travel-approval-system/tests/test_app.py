import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as travel  # noqa: E402


class TravelApprovalTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        travel.app.config.update(DATABASE=self.path, TESTING=True)
        with travel.app.app_context():
            travel.init_db()
        self.client = travel.app.test_client()

    def tearDown(self):
        os.remove(self.path)

    def login(self, email, password):
        return self.client.post("/login", data={"email": email, "password": password},
                                follow_redirects=True)

    def submit_request(self, **overrides):
        start = date.today() + timedelta(days=7)
        data = {
            "destination": "Mumbai", "purpose": "Client meeting",
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=2)).isoformat(),
            "travel_mode": "Flight", "estimated_cost": "12500",
        }
        data.update(overrides)
        return self.client.post("/requests/new", data=data, follow_redirects=True)

    def test_login_required(self):
        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 302)

    def test_bad_login(self):
        resp = self.login("employee@company.com", "wrong")
        self.assertIn(b"Invalid email or password", resp.data)

    def test_full_approval_flow(self):
        self.login("employee@company.com", "employee123")
        resp = self.submit_request()
        self.assertIn(b"submitted for approval", resp.data)
        self.client.post("/logout")

        self.login("manager@company.com", "manager123")
        resp = self.client.get("/dashboard")
        self.assertIn(b"Mumbai", resp.data)
        resp = self.client.post("/requests/1/decide",
                                data={"action": "approve", "comment": "OK"},
                                follow_redirects=True)
        self.assertIn(b"Request approved", resp.data)
        self.client.post("/logout")

        self.login("employee@company.com", "employee123")
        resp = self.client.get("/requests/1")
        self.assertIn(b"Approved", resp.data)

    def test_reject_requires_comment(self):
        self.login("employee@company.com", "employee123")
        self.submit_request()
        self.client.post("/logout")
        self.login("manager@company.com", "manager123")
        resp = self.client.post("/requests/1/decide", data={"action": "reject", "comment": ""},
                                follow_redirects=True)
        self.assertIn(b"explaining the rejection", resp.data)

    def test_validation_rejects_past_and_reversed_dates(self):
        self.login("employee@company.com", "employee123")
        past = (date.today() - timedelta(days=1)).isoformat()
        self.assertIn(b"cannot be in the past", self.submit_request(start_date=past).data)
        start = date.today() + timedelta(days=5)
        resp = self.submit_request(start_date=start.isoformat(),
                                   end_date=(start - timedelta(days=1)).isoformat())
        self.assertIn(b"cannot be before", resp.data)

    def test_employee_cannot_decide_or_see_others(self):
        self.login("employee@company.com", "employee123")
        self.submit_request()
        resp = self.client.post("/requests/1/decide", data={"action": "approve"})
        self.assertEqual(resp.status_code, 403)
        self.client.post("/logout")

        self.client.post("/register", data={
            "name": "Other Person", "email": "other@company.com", "password": "secret1",
            "department": "Sales", "manager_id": "2"})
        self.login("other@company.com", "secret1")
        self.assertEqual(self.client.get("/requests/1").status_code, 403)

    def test_cancel_pending_request(self):
        self.login("employee@company.com", "employee123")
        self.submit_request()
        resp = self.client.post("/requests/1/cancel", follow_redirects=True)
        self.assertIn(b"Request cancelled", resp.data)

    def test_admin_dashboard_and_users(self):
        self.login("admin@company.com", "admin123")
        self.assertIn(b"All Travel Requests", self.client.get("/dashboard").data)
        self.assertIn(b"employee@company.com", self.client.get("/admin/users").data)


if __name__ == "__main__":
    unittest.main()
