import json
import os
import sys
import tempfile
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Console Windows có thể dùng cp1252 khi stdout bị redirect.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from services import login_flow
from services.login_flow import (
    FACEBOOK_HOME,
    FACEBOOK_ME,
    LoginResult,
    inject_cookies,
    login_session,
    persist_cookies,
    session_matches_uid,
    verify_login,
)


class FakeDriver:
    """Driver tối thiểu cho các thao tác cookie/điều hướng."""

    def __init__(self, cookies=None, url="https://www.facebook.com/"):
        self.cookies = list(cookies or [])
        self.current_url = url
        self.visited = []
        self.added = []
        self.refresh_count = 0
        self.title = "Facebook"

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def get_cookies(self):
        return list(self.cookies)

    def add_cookie(self, cookie):
        self.added.append(cookie)
        self.cookies.append({"name": cookie["name"], "value": cookie["value"]})

    def refresh(self):
        self.refresh_count += 1

    def execute_script(self, script):
        return "complete"


class FakeStore:
    def __init__(self):
        self.saved = {}

    def save(self, uid, cookies):
        self.saved[uid] = list(cookies)
        return f"/tmp/{uid}.json"


def _session_cookies(uid="123"):
    return [
        {"name": "c_user", "value": uid},
        {"name": "xs", "value": "session-token"},
    ]


class LoginFlowTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("services.login_flow.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_session_matches_uid_requires_both_cookies(self):
        self.assertTrue(session_matches_uid(FakeDriver(_session_cookies("123")), "123"))
        self.assertFalse(session_matches_uid(FakeDriver(_session_cookies("123")), "456"))
        self.assertFalse(
            session_matches_uid(FakeDriver([{"name": "c_user", "value": "123"}]), "123")
        )

    def test_verify_login_fast_fails_without_session_cookies(self):
        driver = FakeDriver([{"name": "datr", "value": "x"}])
        result = verify_login(driver)

        self.assertFalse(result.ok)
        self.assertEqual(driver.visited, [])

    def test_verify_login_reports_account_mismatch(self):
        driver = FakeDriver(_session_cookies("111"))
        result = verify_login(driver, expected_uid="222")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "account_mismatch")
        self.assertEqual(driver.visited, [])

    def test_verify_login_success_opens_profile_page(self):
        driver = FakeDriver(_session_cookies("123"))
        result = verify_login(driver, expected_uid="123")

        self.assertTrue(result.ok)
        self.assertEqual(driver.visited, [FACEBOOK_ME])

    def test_verify_login_rejects_verification_redirect(self):
        driver = FakeDriver(_session_cookies("123"))
        driver.get = lambda url: setattr(driver, "current_url", "https://facebook.com/checkpoint/1")

        result = verify_login(driver, expected_uid="123")

        self.assertFalse(result.ok)

    def test_inject_cookies_reads_file_and_refreshes(self):
        payload = [
            {"name": "c_user", "value": "123", "expirationDate": "1700000000"},
            {"name": "xs", "value": "token"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cookies.json")
            with open(path, "w", encoding="utf-8") as file:
                json.dump(payload, file)

            driver = FakeDriver()
            self.assertTrue(inject_cookies(driver, path))

        self.assertEqual(driver.visited, [FACEBOOK_HOME])
        self.assertEqual(len(driver.added), 2)
        self.assertEqual(driver.added[0]["expiry"], 1700000000)
        self.assertEqual(driver.refresh_count, 1)

    def test_inject_cookies_missing_file_returns_false(self):
        driver = FakeDriver()
        self.assertFalse(inject_cookies(driver, "missing-cookies.json"))
        self.assertEqual(driver.visited, [])

    def test_login_session_reuses_valid_session_and_persists(self):
        driver = FakeDriver(_session_cookies("123"))
        store = FakeStore()

        result = login_session(driver, "123", "not-used.json", store=store)

        self.assertTrue(result.ok)
        self.assertEqual(driver.visited, [FACEBOOK_HOME, FACEBOOK_ME])
        self.assertEqual(driver.added, [])
        self.assertIn("123", store.saved)

    def test_login_session_injects_cookies_when_uid_differs(self):
        driver = FakeDriver(_session_cookies("999"))
        store = FakeStore()

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cookies.json")
            with open(path, "w", encoding="utf-8") as file:
                json.dump(
                    [
                        {"name": "c_user", "value": "123"},
                        {"name": "xs", "value": "new-token"},
                    ],
                    file,
                )
            result = login_session(driver, "123", path, store=store)

        self.assertTrue(result.ok)
        self.assertEqual(len(driver.added), 2)
        self.assertEqual(driver.added[0]["name"], "c_user")
        self.assertIn("123", store.saved)

    def test_persist_cookies_returns_none_when_store_fails(self):
        class BrokenStore:
            def save(self, uid, cookies):
                raise OSError("disk full")

        self.assertIsNone(persist_cookies(FakeDriver(), BrokenStore(), "123"))

    def test_login_with_cookies_marks_fatal_on_driver_error(self):
        class BrokenDriver(FakeDriver):
            def get(self, url):
                raise RuntimeError("browser closed")

        result = login_flow.login_with_cookies(BrokenDriver(), "123", [])
        self.assertEqual(result, LoginResult(False, "login_failed", fatal=True))


if __name__ == "__main__":
    unittest.main()
