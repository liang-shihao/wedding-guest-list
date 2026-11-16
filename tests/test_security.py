import unittest

from seat.security import LoginGuard, RateLimiter, check_token, client_ip, make_token

WEEK = 7 * 86400


class TokenTest(unittest.TestCase):
    def test_roundtrip(self):
        self.assertTrue(check_token("pw", make_token("pw", 1000), 1001))

    def test_expired(self):
        self.assertFalse(check_token("pw", make_token("pw", 0), WEEK + 1))

    def test_wrong_password(self):
        self.assertFalse(check_token("other", make_token("pw", 0), 1))

    def test_garbage(self):
        for t in ("abc", "", "1.2.3", "999999999999.zz", None):
            self.assertFalse(check_token("pw", t, 1))

    def test_tampered_expiry(self):
        exp, sig = make_token("pw", 0).split(".")
        self.assertFalse(check_token("pw", f"{int(exp) + WEEK}.{sig}", 1))


class GuardTest(unittest.TestCase):
    def test_locks_after_5(self):
        g = LoginGuard()
        for t in range(5):
            self.assertFalse(g.is_locked("1.1.1.1", t))
            g.fail("1.1.1.1", t)
        self.assertTrue(g.is_locked("1.1.1.1", 5))
        self.assertFalse(g.is_locked("2.2.2.2", 5))
        self.assertFalse(g.is_locked("1.1.1.1", 4 + 600 + 1))

    def test_success_resets(self):
        g = LoginGuard()
        for t in range(4):
            g.fail("ip", t)
        g.success("ip")
        g.fail("ip", 5)
        self.assertFalse(g.is_locked("ip", 6))

    def test_window(self):
        g = LoginGuard()
        for i in range(5):
            g.fail("ip", i * 601)
        self.assertFalse(g.is_locked("ip", 4 * 601 + 1))


class RateLimiterTest(unittest.TestCase):
    def test_limit(self):
        r = RateLimiter()
        for _ in range(300):
            self.assertTrue(r.allow("a", 0))
        self.assertFalse(r.allow("a", 1))
        self.assertTrue(r.allow("b", 1))
        self.assertTrue(r.allow("a", 61))


class ClientIpTest(unittest.TestCase):
    def test_client_ip(self):
        h = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        self.assertEqual(client_ip("9.9.9.9", h, False), "9.9.9.9")
        self.assertEqual(client_ip("9.9.9.9", h, True), "1.2.3.4")
        self.assertEqual(client_ip("9.9.9.9", {}, True), "9.9.9.9")


if __name__ == "__main__":
    unittest.main()
