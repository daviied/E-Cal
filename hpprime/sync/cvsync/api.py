"""A small client for the CalcVault web app's API (backend/app/main.py).

The app has one shared password and a signed session cookie that lasts 30
days. The cookie is kept in the sync tool's own folder so the password is
asked for once a month, not on every sync; the password itself is never
written down.
"""
import http.cookiejar
import json
import os
import urllib.error
import urllib.request


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, base_url, cookie_path):
        self.base = base_url.rstrip("/")
        self.cookie_path = cookie_path
        self.jar = http.cookiejar.LWPCookieJar(cookie_path)
        if os.path.exists(cookie_path):
            try:
                self.jar.load(ignore_discard=True, ignore_expires=False)
            except (OSError, http.cookiejar.LoadError):
                pass
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail")
            except (ValueError, AttributeError):
                detail = None
            raise ApiError(e.code, detail or "%s %s failed (%d)" % (method, path, e.code))
        except urllib.error.URLError as e:
            raise ApiError(0, "cannot reach %s (%s)" % (self.base, e.reason))
        return json.loads(raw.decode("utf-8")) if raw else None

    # -- session

    def authed(self):
        try:
            return bool(self._call("GET", "/api/session").get("authed"))
        except ApiError:
            return False

    def login(self, password):
        self._call("POST", "/api/login", {"password": password})
        os.makedirs(os.path.dirname(self.cookie_path) or ".", exist_ok=True)
        self.jar.save(ignore_discard=True)
        try:
            os.chmod(self.cookie_path, 0o600)
        except OSError:
            pass
        if not self.authed():
            raise ApiError(401, "logged in, but the session cookie was not kept. If the "
                                "server runs without HTTPS, set HTTPS_ONLY=false there.")

    # -- data

    def tree(self):
        return self._call("GET", "/api/tree")

    def get_calc(self, cid):
        return self._call("GET", "/api/calculators/%d" % int(cid))

    def create_folder(self, name, parent_id):
        return self._call("POST", "/api/folders", {"name": name, "parent_id": parent_id})

    def update_folder(self, fid, name, parent_id):
        return self._call("PATCH", "/api/folders/%d" % int(fid), {"name": name, "parent_id": parent_id})

    def delete_folder(self, fid):
        return self._call("DELETE", "/api/folders/%d" % int(fid))

    def create_calc(self, name, folder_id):
        return self._call("POST", "/api/calculators", {"name": name, "folder_id": folder_id})

    def update_calc(self, cid, name, folder_id, data):
        return self._call("PATCH", "/api/calculators/%d" % int(cid),
                          {"name": name, "folder_id": folder_id, "data": data})

    def delete_calc(self, cid):
        return self._call("DELETE", "/api/calculators/%d" % int(cid))
