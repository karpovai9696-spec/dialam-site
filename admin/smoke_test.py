#!/usr/bin/env python3
"""Smoke/security test админки для CI. Запускает копию admin во временном каталоге."""
import http.cookiejar
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def request(opener, base, path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "admin")
    tmp = tempfile.mkdtemp(prefix="dialam-admin-test-")
    dst = os.path.join(tmp, "admin")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "data", "exports", "__pycache__", "sessions.json", "audit.log", "*.db"))
    port = free_port()
    env = os.environ.copy()
    env["ADMIN_PASSWORD"] = "test-password"
    proc = subprocess.Popen([sys.executable, "server.py", "--host", "127.0.0.1",
                             "--port", str(port)], cwd=dst, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                status, _, _ = request(urllib.request.build_opener(), base, "/api/health")
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise SystemExit("admin server did not start")

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        status, body, headers = request(opener, base, "/api/login", "POST",
                                        {"password": "test-password"})
        assert status == 200, (status, body)
        csrf = json.loads(body)["csrf_token"]
        assert len(csrf) == 64
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert "Secure" not in headers.get("Set-Cookie", "")  # HTTP test server

        status, _, _ = request(urllib.request.build_opener(), base, "/api/sites")
        assert status == 401

        status, _, _ = request(opener, base, "/api/sites/1/items", "POST",
                               {"type": "news", "data": {"title": "ci-test"},
                                "sort_order": 0})
        assert status == 403, status

        status, body, _ = request(opener, base, "/api/sites/1/items", "POST",
                                  {"type": "news",
                                   "data": {"title": "ci-test", "published": False},
                                   "sort_order": 0},
                                  {"X-CSRF-Token": csrf})
        assert status == 201, (status, body)
        item_id = json.loads(body)["id"]
        status, _, _ = request(opener, base, f"/api/items/{item_id}", "DELETE",
                               headers={"X-CSRF-Token": csrf})
        assert status == 200, status
        print("admin smoke/security test: OK")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
