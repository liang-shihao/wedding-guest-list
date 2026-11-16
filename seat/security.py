"""Admin session tokens, login brute-force guard, public rate limiter."""
import hashlib
import hmac
import threading

TOKEN_TTL = 7 * 86400


def _key(password: str) -> bytes:
    return hashlib.sha256(b"wedding-seat:" + password.encode("utf-8")).digest()


def _sign(password: str, expiry: str) -> str:
    return hmac.new(_key(password), expiry.encode("ascii"), hashlib.sha256).hexdigest()


def make_token(password: str, now: float) -> str:
    expiry = str(int(now) + TOKEN_TTL)
    return f"{expiry}.{_sign(password, expiry)}"


def check_token(password: str, token, now: float) -> bool:
    if not token or not isinstance(token, str) or token.count(".") != 1:
        return False
    expiry, sig = token.split(".")
    if not expiry.isdigit():
        return False
    if not hmac.compare_digest(_sign(password, expiry), sig):
        return False
    return int(expiry) > now


class LoginGuard:
    def __init__(self, max_fail=5, window=600, lock=600):
        self.max_fail, self.window, self.lock = max_fail, window, lock
        self._fails = {}
        self._locked_until = {}
        self._mu = threading.Lock()

    def is_locked(self, ip, now) -> bool:
        with self._mu:
            return self._locked_until.get(ip, 0) > now

    def fail(self, ip, now) -> None:
        with self._mu:
            recent = [t for t in self._fails.get(ip, []) if now - t < self.window]
            recent.append(now)
            if len(recent) >= self.max_fail:
                self._locked_until[ip] = now + self.lock
                recent = []
            self._fails[ip] = recent

    def success(self, ip) -> None:
        with self._mu:
            self._fails.pop(ip, None)
            self._locked_until.pop(ip, None)


class RateLimiter:
    """Fixed-window counter per IP."""

    def __init__(self, limit=300, window=60):
        self.limit, self.window = limit, window
        self._buckets = {}
        self._mu = threading.Lock()

    def allow(self, ip, now) -> bool:
        slot = int(now // self.window)
        with self._mu:
            if len(self._buckets) > 10000:
                self._buckets = {k: v for k, v in self._buckets.items() if v[0] == slot}
            s, n = self._buckets.get(ip, (slot, 0))
            if s != slot:
                s, n = slot, 0
            if n >= self.limit:
                self._buckets[ip] = (s, n)
                return False
            self._buckets[ip] = (s, n + 1)
            return True


def client_ip(socket_ip: str, headers, trust_proxy: bool) -> str:
    if trust_proxy:
        xff = headers.get("X-Forwarded-For", "") if headers else ""
        first = xff.split(",")[0].strip()
        if first:
            return first
    return socket_ip
