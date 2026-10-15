"""Tongji Yunpan (AnyShare) client.

This module implements the OAuth2 login flow used by the AnyShare web UI and
the small set of REST APIs needed for a CLI tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.parse
import zlib
from pathlib import Path
from typing import Any

import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

DEFAULT_BASE_URL = "https://yunpan.tongji.edu.cn"
USER_AGENT = "tongji-yunpan-cli/0.1"
SINGLE_UPLOAD_LIMIT = 5 * 1024**3
OAUTH_LOGIN_PATH = "/anyshare/oauth2/login"
OAUTH_SIGNIN_PATH = "/oauth2/signin"
OAUTH_REFRESH_PATH = "/anyshare/oauth2/login/refreshToken"

# 2048-bit RSA public key used by the AnyShare login page (also used by pansh).
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4E+eiWRwffhRIPQYvlXU
jf0b3HqCmosiCxbFCYI/gdfDBhrTUzbt3fL3o/gRQQBEPf69vhJMFH2ZMtaJM6oh
E3yQef331liPVM0YvqMOgvoID+zDa1NIZFObSsjOKhvZtv9esO0REeiVEPKNc+Dp
6il3x7TV9VKGEv0+iriNjqv7TGAexo2jVtLm50iVKTju2qmCDG83SnVHzsiNj70M
iviqiLpgz72IxjF+xN4bRw8I5dD0GwwO8kDoJUGWgTds+VckCwdtZA65oui9Osk5
t1a4pg6Xu9+HFcEuqwJTDxATvGAz1/YW0oUisjM0ObKTRDVSfnTYeaBsN6L+M+8g
CwIDAQAB
-----END PUBLIC KEY-----"""


class YunpanError(Exception):
    """Raised when an AnyShare API call fails."""

    def __init__(self, message: str, status: int | None = None, data: Any = None):
        super().__init__(message)
        self.status = status
        self.data = data


def _parse_next_data(html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        raise YunpanError("无法从登录页提取 __NEXT_DATA__")
    return json.loads(match.group(1))


def rsa_encrypt_password(password: str, public_key_pem: str = PUBLIC_KEY_PEM) -> str:
    """Encrypt a password with the AnyShare RSA public key (PKCS#1 v1.5)."""
    key = RSA.import_key(public_key_pem)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def _authrequest_to_request(authrequest: list[str]) -> tuple[str, str, dict[str, str]]:
    method = authrequest[0]
    url = authrequest[1]
    headers: dict[str, str] = {}
    for raw in authrequest[2:]:
        if ":" in raw:
            key, value = raw.split(":", 1)
            headers[key.strip()] = value.strip()
    return method, url, headers


def file_hashes(path: str | Path, chunk_size: int = 1024 * 1024) -> tuple[int, str, str, str]:
    """Return (size, md5_hex_upper, crc32_hex_upper, slice_md5_hex_upper)."""
    p = Path(path)
    size = 0
    md5 = hashlib.md5()
    crc = 0
    slice_md5 = hashlib.md5()
    slice_limit = 200 * 1024
    slice_remaining = slice_limit
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            md5.update(chunk)
            crc = zlib.crc32(chunk, crc)
            if slice_remaining > 0:
                take = chunk[:slice_remaining]
                slice_md5.update(take)
                slice_remaining -= len(take)
    return (
        size,
        md5.hexdigest().upper(),
        f"{crc & 0xffffffff:08X}",
        slice_md5.hexdigest().upper(),
    )


class YunpanClient:
    """Small synchronous client for Tongji Yunpan's AnyShare REST API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: dict[str, str] | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 60.0,
        on_token_updated: Any = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: dict[str, str] = dict(token or {})
        self.username = username
        self.password = password
        self.on_token_updated = on_token_updated
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
            }
        )
        self._apply_token()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def _apply_token(self) -> None:
        access = self.token.get("access_token")
        refresh = self.token.get("refresh_token")
        id_token = self.token.get("id_token")
        host = urllib.parse.urlparse(self.base_url).hostname or "yunpan.tongji.edu.cn"
        if access:
            self.session.headers["Authorization"] = f"Bearer {access}"
        if refresh:
            self.session.cookies.set("client.oauth2_refresh_token", refresh, domain=host, path="/")
        if access:
            self.session.cookies.set("client.oauth2_token", access, domain=host, path="/")
        if id_token:
            self.session.cookies.set("id_token", id_token, domain=host, path="/")

    def login(self, username: str | None = None, password: str | None = None) -> dict[str, str]:
        username = username or self.username
        password = password or self.password
        if not username or not password:
            raise YunpanError("需要用户名和密码")
        self.username = username
        self.password = password
        self.session.cookies.clear()

        # 1. Start the OAuth2 authorization flow and land on the login page.
        params = {
            "lang": "zh-cn",
            "redirect": "/anyshare/zh-cn/homepage",
        }
        r = self.session.get(
            self.base_url + OAUTH_LOGIN_PATH,
            params=params,
            allow_redirects=True,
            timeout=self.timeout,
        )
        r.raise_for_status()
        page_props = _parse_next_data(r.text)["props"]["pageProps"]
        challenge = page_props["challenge"]
        csrf = page_props["csrftoken"]
        device = page_props.get("device") or {
            "name": "",
            "description": "",
            "client_type": "web",
            "udids": [],
        }

        # 2. Submit the local AnyShare account.
        signin_body = {
            "_csrf": csrf,
            "challenge": challenge,
            "account": username,
            "password": rsa_encrypt_password(password),
            "vcode": {"id": "", "content": ""},
            "dualfactorauthinfo": {"validcode": {"vcode": ""}, "OTP": {"OTP": ""}},
            "remember": False,
            "device": device,
        }
        r2 = self.session.post(
            self.base_url + OAUTH_SIGNIN_PATH,
            json=signin_body,
            timeout=self.timeout,
        )
        r2.raise_for_status()
        data = r2.json()
        redirect = data.get("redirect")
        if not redirect:
            raise YunpanError(f"登录接口未返回跳转地址: {data}")
        redirect = urllib.parse.urljoin(self.base_url + "/", redirect)

        # 3. Follow the login/consent redirects to the web callback, which sets
        #    the access/refresh/id cookies.
        self.session.get(redirect, allow_redirects=True, timeout=self.timeout)

        self.token = {
            "access_token": self.session.cookies.get("client.oauth2_token") or "",
            "refresh_token": self.session.cookies.get("client.oauth2_refresh_token") or "",
            "id_token": self.session.cookies.get("id_token") or "",
        }
        if not self.token["access_token"]:
            raise YunpanError("登录成功但未获取到访问令牌")
        self._apply_token()
        if self.on_token_updated:
            self.on_token_updated()
        return self.token

    def refresh_token(self) -> bool:
        """Try the AnyShare refresh endpoint. Returns True if token changed."""
        old_access = self.token.get("access_token")
        r = self.session.get(
            self.base_url + OAUTH_REFRESH_PATH,
            timeout=self.timeout,
        )
        if r.status_code != 200:
            return False
        new_access = self.session.cookies.get("client.oauth2_token")
        new_refresh = self.session.cookies.get("client.oauth2_refresh_token")
        new_id = self.session.cookies.get("id_token")
        if new_access:
            self.token["access_token"] = new_access
            if new_refresh:
                self.token["refresh_token"] = new_refresh
            if new_id:
                self.token["id_token"] = new_id
            self._apply_token()
            if self.on_token_updated:
                self.on_token_updated()
            return new_access != old_access
        return False

    # ------------------------------------------------------------------
    # REST helpers
    # ------------------------------------------------------------------
    def api(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self.base_url + "/api" + ("/" + path.lstrip("/") if path else "")
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if response.status_code == 401:
            refreshed = self.refresh_token()
            if not refreshed and self.username and self.password:
                self.login()
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = response.text
            raise YunpanError(
                f"API {method} {path} failed: HTTP {response.status_code} - {data}",
                status=response.status_code,
                data=data,
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.api("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.api("POST", path, **kwargs)

    # ------------------------------------------------------------------
    # High-level operations
    # ------------------------------------------------------------------
    def whoami(self) -> dict[str, Any]:
        return self.post("/eacp/v1/user/get", json={})

    def list_doc_libs(self) -> list[dict[str, Any]]:
        data = self.get("/efast/v1/entry-doc-lib?sort=doc_lib_name&direction=asc")
        return data or []

    def personal_lib(self) -> dict[str, Any]:
        for lib in self.list_doc_libs():
            if lib.get("type") == "user_doc_lib":
                return lib
        raise YunpanError("未找到个人文档库")

    def resolve_path(self, path: str) -> dict[str, Any]:
        """Resolve a human-readable name path to an AnyShare object.

        An empty path / '.', '/', or '~' resolves to the personal doc library.
        """
        path = (path or "").strip()
        if path in ("", ".", "/", "~"):
            lib = self.personal_lib()
            return {
                "docid": lib["id"],
                "name": lib["name"],
                "size": -1,
                "rev": lib.get("rev", ""),
                "type": "user_doc_lib",
            }
        if path == "~":
            lib = self.personal_lib()
            path = lib["name"]
        elif path.startswith("~/"):
            lib = self.personal_lib()
            path = lib["name"] + path[1:]

        path = path.lstrip("/")
        try:
            data = self.post("/efast/v1/file/getinfobypath", json={"namepath": path})
        except YunpanError as exc:
            if exc.status and exc.status in (400, 403, 404):
                raise YunpanError(f"远程路径不存在或无权限: {path}") from exc
            raise
        if not data:
            raise YunpanError(f"远程路径不存在或无权限: {path}")
        return data

    def list_dir(self, docid: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        data = self.post("/efast/v1/dir/list", json={"docid": docid}) or {}
        return data.get("dirs", []), data.get("files", [])

    def create_dir(self, parent_docid: str, name: str, ondup: int = 2) -> dict[str, Any]:
        return self.post("/efast/v1/dir/create", json={"docid": parent_docid, "name": name, "ondup": ondup})

    def _share_item_type(self, info: dict[str, Any]) -> str:
        return "folder" if info.get("size", 0) == -1 else "file"

    def list_share_links(self, path: str, link_type: str = "anonymous") -> list[dict[str, Any]]:
        """Return existing share links for a remote file/folder."""
        info = self.resolve_path(path)
        item_type = self._share_item_type(info)
        encoded_docid = urllib.parse.quote(info["docid"], safe="")
        data = self.get(
            f"/shared-link/v1/document/{item_type}/{encoded_docid}?type={link_type}"
        )
        return data or []

    def create_share_link(
        self,
        path: str,
        *,
        title: str | None = None,
        expires_at: str = "2099-12-31T23:59:59+08:00",
        password: str = "",
        limited_times: int = -1,
        allow: list[str] | None = None,
        reuse_existing: bool = True,
    ) -> dict[str, Any]:
        """Create (or reuse) an AnyShare anonymous share link.

        Returns a dict containing at least `id` and the browser-facing
        long-term URL in `url` (``https://<host>/link/<id>``).
        """
        info = self.resolve_path(path)
        item_type = self._share_item_type(info)
        item_title = title or info.get("name") or Path(path).name or "share"
        allow = allow or ["display", "preview", "download"]
        if reuse_existing:
            existing = self.list_share_links(path)
            if existing:
                first = existing[0]
                link_id = first.get("id") or first.get("link_id") or ""
                return {
                    "id": link_id,
                    "url": f"{self.base_url}/link/{link_id}" if link_id else "",
                    "docid": info["docid"],
                    "item_type": item_type,
                    "title": first.get("title") or item_title,
                    "created_at": first.get("created_at"),
                    "expires_at": first.get("expires_at"),
                    "password": first.get("password", ""),
                    "limited_times": first.get("limited_times", -1),
                    "allow": (first.get("item") or {}).get("allow", allow),
                    "created": False,
                }
        payload = {
            "item": {"id": info["docid"], "type": item_type, "allow": allow},
            "title": item_title,
            "expires_at": expires_at,
            "password": password,
            "limited_times": limited_times,
        }
        response = self.post("/shared-link/v1/document/anonymous", json=payload)
        if not isinstance(response, dict):
            raise YunpanError(f"创建分享链接失败，服务端返回: {response}")
        link_id = response.get("id") or response.get("link_id")
        if not link_id:
            raise YunpanError(f"创建分享链接失败，未返回 link id: {response}")
        return {
            "id": link_id,
            "url": f"{self.base_url}/link/{link_id}",
            "docid": info["docid"],
            "item_type": item_type,
            "title": item_title,
            "expires_at": expires_at,
            "password": password,
            "limited_times": limited_times,
            "allow": allow,
            "created": True,
        }

    @staticmethod
    def _share_link_id(share: str) -> str:
        share = share.strip()
        # Accept a full /link/<id> URL, or just the link id.
        if "://" in share or "/" in share:
            share = share.split("?", 1)[0].rstrip("/")
            return share.rsplit("/", 1)[-1]
        return share

    def resolve_share_link(self, share: str, filename: str | None = None) -> dict[str, Any]:
        """Resolve a long-term share link to a fresh signed direct-download URL.

        This does not need a logged-in account: it uses the link token cookie
        set by ``GET /link/<link_id>``.
        """
        link_id = self._share_link_id(share)
        if not link_id:
            raise YunpanError("分享链接为空")
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        r = session.get(
            f"{self.base_url}/link/{link_id}",
            allow_redirects=False,
            timeout=self.timeout,
        )
        link_token = session.cookies.get(f"link_token:{link_id}")
        if not link_token:
            raise YunpanError(
                f"无法获取分享链接令牌（HTTP {r.status_code}），请检查链接是否有效、是否已过期或需要密码"
            )
        headers = {"Authorization": f"Bearer {link_token}"}
        link_info = session.get(
            f"{self.base_url}/api/shared-link/v1/links/{link_id}",
            headers=headers,
            timeout=self.timeout,
        )
        if link_info.status_code != 200:
            raise YunpanError(f"读取分享信息失败: HTTP {link_info.status_code} {link_info.text[:200]}")
        info = link_info.json()
        if info.get("password_required"):
            raise YunpanError("该分享链接需要访问密码，当前 CLI 暂不支持带密码的分享链接解析")
        item_type = (info.get("item") or {}).get("type")
        if item_type != "file":
            raise YunpanError("当前分享不是单文件分享，无法直接解析为下载链接；请在浏览器中打开分享链接")
        items = session.get(
            f"{self.base_url}/api/efast/v1/entry-item",
            headers=headers,
            timeout=self.timeout,
        )
        if items.status_code != 200:
            raise YunpanError(f"读取分享文件失败: HTTP {items.status_code} {items.text[:200]}")
        entries = items.json() or []
        if isinstance(entries, dict):
            entries = [entries]
        if not entries:
            raise YunpanError("分享链接中没有文件")
        entry = entries[0]
        docid = entry.get("id") or entry.get("docid")
        if not docid:
            raise YunpanError(f"分享文件中没有 docid: {entry}")
        save_name = filename or info.get("title") or entry.get("name") or "download"
        download = session.post(
            f"{self.base_url}/api/efast/v1/file/osdownload",
            headers=headers,
            json={"docid": docid, "authtype": "QUERY_STRING", "savename": save_name},
            timeout=self.timeout,
        )
        if download.status_code != 200:
            raise YunpanError(f"解析下载链接失败: HTTP {download.status_code} {download.text[:200]}")
        data = download.json()
        authrequest = data.get("authrequest") or []
        if len(authrequest) < 2:
            raise YunpanError(f"分享下载接口未返回直链: {data}")
        return {
            "link_id": link_id,
            "docid": docid,
            "name": data.get("name") or save_name,
            "size": data.get("size", entry.get("size", 0)),
            "rev": data.get("rev") or entry.get("rev", ""),
            "url": authrequest[1],
            "expires_at": info.get("expires_at"),
            "raw": data,
        }

    def download_share_link(
        self,
        share: str,
        local_path: str | Path | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> Path:
        info = self.resolve_share_link(share, filename=filename)
        if local_path is None:
            local_path = Path(info.get("name") or "download")
        local = Path(local_path)
        if local.exists() and not force:
            raise YunpanError(f"本地文件已存在: {local}，使用 --force 覆盖")
        local.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(info["url"], stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            with local.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return local

    def upload_file(self, local_path: str | Path, remote_dir: str, name: str | None = None, ondup: int = 2) -> dict[str, Any]:
        target = self.resolve_path(remote_dir)
        if target.get("size", -1) != -1:
            raise YunpanError(f"上传目标不是目录: {remote_dir}")
        parent_docid = target["docid"]
        local = Path(local_path)
        if not local.is_file():
            raise YunpanError(f"本地文件不存在: {local}")
        filename = name or local.name
        size, md5, crc32, _slice_md5 = file_hashes(local)
        if size > SINGLE_UPLOAD_LIMIT:
            raise YunpanError(
                f"文件大小 {size} 超过单文件上传上限 {SINGLE_UPLOAD_LIMIT} 字节，"
                "当前版本暂未实现超大文件分片上传"
            )

        # Quick check: if the same content already exists, use the server-side
        # "instant upload" endpoint.
        pre = self.post("/efast/v1/file/predupload", json={"length": size, "slice_md5": _slice_md5})
        if pre and pre.get("match"):
            dup = self.post(
                "/efast/v1/file/dupload",
                json={
                    "docid": parent_docid,
                    "length": size,
                    "md5": md5,
                    "crc32": crc32,
                    "name": filename,
                    "ondup": ondup,
                    "client_mtime": int(time.time() * 1000),
                },
            )
            if dup.get("success"):
                dup.setdefault("size", size)
                dup.setdefault("md5", md5)
                dup.setdefault("crc32", crc32)
                return dup

        # Normal single-PUT upload (AnyShare supports up to 5 GiB here).
        began = self.post(
            "/efast/v1/file/osbeginupload",
            json={
                "docid": parent_docid,
                "length": size,
                "name": filename,
                "ondup": ondup,
                "client_mtime": int(time.time() * 1000),
                "csflevel": 0,
                "editedrev": "",
            },
        )
        method, url, headers = _authrequest_to_request(began["authrequest"])
        with local.open("rb") as f:
            put = requests.request(method, url, headers=headers, data=f, timeout=max(self.timeout, 300))
        if not (200 <= put.status_code < 300):
            raise YunpanError(f"对象存储上传失败: HTTP {put.status_code} {put.text[:200]}")

        ended = self.post(
            "/efast/v1/file/osendupload",
            json={
                "docid": began["docid"],
                "rev": began["rev"],
                "md5": md5,
                "crc32": crc32,
            },
        )
        return {
            "docid": began["docid"],
            "name": began.get("name") or filename,
            "rev": began["rev"],
            "size": size,
            "md5": md5,
            "crc32": crc32,
            "end": ended,
        }

    def get_download_info(self, path: str, filename: str | None = None, rev: str | None = None) -> dict[str, Any]:
        info = self.resolve_path(path)
        if info.get("size", 0) == -1:
            raise YunpanError(f"不是文件: {path}")
        body: dict[str, Any] = {
            "docid": info["docid"],
            "authtype": "QUERY_STRING",
            "savename": filename or info.get("name") or "download",
        }
        if rev:
            body["rev"] = rev
        data = self.post("/efast/v1/file/osdownload", json=body)
        auth = data.get("authrequest") or []
        if len(auth) < 2:
            raise YunpanError("下载接口未返回直链")
        return {
            "docid": info["docid"],
            "name": data.get("name") or info.get("name") or "",
            "size": data.get("size", info.get("size", 0)),
            "rev": data.get("rev") or rev or info.get("rev", ""),
            "url": auth[1],
            "authrequest": auth,
            "raw": data,
        }

    def download_file(self, path: str, local_path: str | Path | None = None, force: bool = False, filename: str | None = None) -> Path:
        info = self.get_download_info(path, filename=filename)
        if local_path is None:
            local_path = Path(info["name"] or Path(path).name)
        local = Path(local_path)
        if local.exists() and not force:
            raise YunpanError(f"本地文件已存在: {local}，使用 --force 覆盖")
        local.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(info["url"], stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            with local.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        return local
