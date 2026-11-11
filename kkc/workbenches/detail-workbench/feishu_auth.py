"""Browser device authorization and Windows-protected Feishu login storage."""

import base64
import contextlib
import ctypes
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SCOPES = ("bitable:app:readonly", "wiki:node:read", "offline_access")
DEVICE_ENDPOINT = "https://accounts.feishu.cn/oauth/v1/device_authorization"
TOKEN_ENDPOINT = "https://accounts.feishu.cn/oauth/v3/token"
STATE_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "KocoDetailWorkbench/Feishu/connection.dat"
PREFIX = b"KDW-FEISHU-1\0"
_THREAD_LOCK = threading.RLock()
_MAX_RESPONSE = 512 * 1024


class AuthError(ValueError):
    pass


class ConfigurationRequired(AuthError):
    pass


class LoginRequired(AuthError):
    pass


class _OAuthRejection(AuthError):
    def __init__(self, error, code=None):
        self.error, self.code = error, code
        super().__init__(_error_hint(error, code))


@dataclass(frozen=True)
class LoginFlow:
    url: str
    user_code: str
    expires_at: float
    interval: int
    app_id: str
    generation: str = field(repr=False)
    device_code: str = field(repr=False)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = build_opener(_NoRedirect)


def _error_hint(error, code=None):
    if error in {"invalid_client", "unauthorized_client"} or code in {20130, 20140, 20048, 20069}:
        return "飞书应用连接未通过校验。请检查 App ID、App Secret、应用发布状态及应用的 OAuth 认证方式。"
    if error in {"invalid_scope", "insufficient_scope"} or code in {20027, 20068}:
        return "飞书应用尚未开通或发布所需读取权限。请让管理员在应用中配置工作台列出的权限后重试。"
    if error == "access_denied":
        return "飞书授权已被取消。可重新点击「连接飞书」完成授权。"
    if error in {"invalid_grant", "expired_token"}:
        return "飞书授权已失效。请重新点击「连接飞书」。"
    if error in {"authorization_pending", "slow_down"}:
        return "正在等待浏览器中的飞书授权。"
    suffix = f"（{code}）" if isinstance(code, int) else ""
    return f"飞书授权未完成{suffix}。请检查应用权限和连接设置后重试。"


def _oauth_request(endpoint, values, basic=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "DetailWorkbench/2.1"}
    if basic is not None:
        headers["Authorization"] = "Basic " + base64.b64encode(":".join(basic).encode("utf-8")).decode("ascii")
    request = Request(endpoint, data=urlencode(values).encode("ascii"), headers=headers)
    status = 200
    try:
        with _OPENER.open(request, timeout=18) as response:
            status = response.status
            raw = response.read(_MAX_RESPONSE + 1)
    except HTTPError as error:
        status = error.code
        with error:
            raw = error.read(_MAX_RESPONSE + 1)
    except (OSError, URLError, ValueError):
        raise AuthError("暂时无法连接飞书授权服务。请检查网络后重试。") from None
    if status == 429:
        raise AuthError("飞书授权服务请求较频繁，请稍后重试。现有连接仍保留。")
    if status >= 500:
        raise AuthError("飞书授权服务暂时不可用，请稍后重试。现有连接仍保留。")
    if len(raw) > _MAX_RESPONSE:
        raise AuthError("飞书授权响应过大，请稍后重试。")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AuthError("飞书授权服务没有返回可读取的数据，请稍后重试。") from None
    if not isinstance(result, dict):
        raise AuthError("飞书授权响应格式异常，请重试。")
    code, error = result.get("code", 0), result.get("error", "")
    if error or code != 0 or status >= 400:
        raise _OAuthRejection(str(error), code)
    return result


def _dpapi(value, *, decrypt=False):
    if os.name != "nt":
        raise AuthError("此版本的飞书连接使用 Windows 用户加密存储，请在 Windows 上连接。")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    incoming = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(incoming, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise AuthError("Windows 无法读取或保存此电脑的飞书连接。请在当前 Windows 用户下重新配置连接。")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(outgoing.data, 0, outgoing.size)
        kernel.LocalFree(outgoing.data)
        ctypes.memset(incoming, 0, len(value))


@contextlib.contextmanager
def _locked():
    with _THREAD_LOCK:
        if os.name != "nt":
            raise AuthError("此版本的飞书连接需要 Windows 用户加密存储。")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        digest = hashlib.sha256(str(STATE_FILE.resolve()).casefold().encode()).hexdigest()[:24]
        handle = kernel.CreateMutexW(None, False, "Local\\KocoDetailWorkbench.Feishu." + digest)
        if not handle:
            raise AuthError("Windows 无法锁定飞书连接文件，请关闭重复窗口后重试。")
        acquired = False
        try:
            result = kernel.WaitForSingleObject(handle, 45000)
            acquired = result in {0, 0x80}
            if not acquired:
                raise AuthError("另一工作台正在更新飞书连接，请稍后重试。")
            yield
        finally:
            if acquired:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)


def _read():
    try:
        content = STATE_FILE.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError:
        raise AuthError("无法读取飞书连接配置，请检查当前用户的本地应用数据目录。") from None
    if len(content) > 128 * 1024 or not content.startswith(PREFIX):
        raise AuthError("飞书连接文件格式异常，请在连接设置中重新配置应用。")
    try:
        data = json.loads(_dpapi(content[len(PREFIX):], decrypt=True))
    except (ValueError, UnicodeError):
        raise AuthError("飞书连接内容无法读取，请在连接设置中重新配置应用。") from None
    if not isinstance(data, dict):
        raise AuthError("飞书连接内容格式异常，请重新配置应用。")
    return data


def _save(data):
    encrypted = PREFIX + _dpapi(json.dumps(data, ensure_ascii=True, allow_nan=False).encode("utf-8"))
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=STATE_FILE.parent, prefix=".connection-", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            for attempt in range(4):
                try:
                    os.replace(pending, STATE_FILE)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05)
        finally:
            pending.unlink(missing_ok=True)
    except OSError:
        raise AuthError("无法保存飞书连接，请检查当前用户的本地应用数据目录后重试。") from None


def _credentials(data):
    app_id = data.get("app_id") or os.environ.get("FEISHU_APP_ID", "").strip()
    secret = data.get("app_secret") or os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not isinstance(app_id, str) or not re.fullmatch(r"cli_[A-Za-z0-9]{1,100}", app_id) or not isinstance(secret, str) or not secret:
        raise ConfigurationRequired("请先在「连接设置」中填写一次飞书应用的 App ID 和 App Secret，再连接飞书。")
    return app_id, secret


def _status(data):
    try:
        app_id, _ = _credentials(data)
        configured = True
    except ConfigurationRequired:
        app_id, configured = "", False
    now = time.time()
    expires = float(data.get("expires_at", 0))
    refresh_expires = float(data.get("refresh_expires_at", 0))
    connected = bool(configured and (data.get("access_token") and expires > now or
                                     data.get("refresh_token") and (refresh_expires == 0 or refresh_expires > now)))
    return {"configured": configured, "connected": connected, "needs_login": not connected,
            "app_id": app_id, "expires_at": expires, "refresh_expires_at": refresh_expires,
            "scopes": list(data.get("scopes") or [])}


def connection_status():
    # Atomic replacement makes a local status read independent of network refresh.
    try:
        return _status(_read())
    except (AuthError, TypeError, ValueError):
        return {"configured": False, "connected": False, "needs_login": True, "app_id": "",
                "expires_at": 0, "refresh_expires_at": 0, "scopes": [],
                "error": "此电脑的飞书连接无法读取，请在连接设置中重新配置应用。"}


def configure_app(app_id, app_secret):
    app_id, app_secret = str(app_id).strip(), str(app_secret).strip()
    if not re.fullmatch(r"cli_[A-Za-z0-9]{1,100}", app_id) or not app_secret or len(app_secret) > 4096 or any(ord(char) < 32 for char in app_secret):
        raise ConfigurationRequired("请填写有效的 App ID 和 App Secret。App ID 以 cli_ 开头。")
    with _locked():
        try:
            old = _read()
        except AuthError:
            old = {}
        if old.get("app_id") == app_id and old.get("app_secret") == app_secret:
            return _status(old)
        data = {"app_id": app_id, "app_secret": app_secret, "revision": uuid.uuid4().hex}
        _save(data)
        return _status(data)


def begin_login():
    with _locked():
        data = _read()
        app_id, secret = _credentials(data)
        result = _oauth_request(DEVICE_ENDPOINT, {"client_id": app_id, "scope": " ".join(SCOPES)}, basic=(app_id, secret))
        url = result.get("verification_uri_complete") or result.get("verification_uri")
        device_code, user_code = result.get("device_code"), result.get("user_code", "")
        try:
            parts = urlsplit(url)
            valid_url = parts.scheme == "https" and (parts.hostname == "feishu.cn" or (parts.hostname or "").endswith(".feishu.cn"))
            if not valid_url or parts.username or parts.password or parts.port not in (None, 443):
                raise ValueError
            interval, lifetime = int(result.get("interval", 5)), int(result["expires_in"])
            if not isinstance(device_code, str) or not device_code or not isinstance(user_code, str) or not 1 <= lifetime <= 3600:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise AuthError("飞书没有返回有效的浏览器授权入口，请检查应用的 OAuth 配置。") from None
        generation = uuid.uuid4().hex
        data["login_generation"] = generation
        _save(data)
        return LoginFlow(url, user_code, time.time() + lifetime, max(1, min(interval, 60)), app_id, generation, device_code)


def _session_values(result, previous=None):
    previous = previous or {}
    token, refresh = result.get("access_token"), result.get("refresh_token")
    token_type = result.get("token_type", "Bearer")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=\-]{1,16384}", token) or str(token_type).casefold() != "bearer":
        raise AuthError("飞书返回的授权类型无法用于当前工作台，请检查应用的 OAuth 配置。")
    try:
        lifetime = int(result["expires_in"])
        if not 1 <= lifetime <= 7 * 86400:
            raise ValueError
        refresh_lifetime = int(result.get("refresh_token_expires_in", result.get("refresh_expires_in", 0)))
        if refresh_lifetime < 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise AuthError("飞书返回的授权有效期格式异常，请重新连接。") from None
    now = time.time()
    if refresh is not None and (not isinstance(refresh, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=\-]{1,16384}", refresh)):
        raise AuthError("飞书返回的续期凭证格式异常，请重新连接。")
    if refresh:
        refresh_expiry = now + refresh_lifetime if refresh_lifetime else 0
    else:
        refresh = previous.get("refresh_token", "")
        refresh_expiry = previous.get("refresh_expires_at", 0)
    scopes = result.get("scope", "")
    scopes = scopes.split() if isinstance(scopes, str) and scopes else previous.get("scopes", [])
    return {"access_token": token, "refresh_token": refresh, "expires_at": now + lifetime,
            "refresh_expires_at": refresh_expiry, "scopes": scopes}


def complete_login(flow, cancel_event=None):
    if not isinstance(flow, LoginFlow):
        raise LoginRequired("请重新点击「连接飞书」开始授权。")
    cancel_event = cancel_event or threading.Event()
    interval = flow.interval
    while time.time() < flow.expires_at:
        if cancel_event.wait(min(interval, max(0, flow.expires_at - time.time()))):
            raise LoginRequired("本次飞书连接已取消。")
        with _locked():
            data = _read()
            app_id, secret = _credentials(data)
            if app_id != flow.app_id or data.get("login_generation") != flow.generation:
                raise LoginRequired("本次授权已被新的连接设置替代，请重新连接飞书。")
            try:
                result = _oauth_request(TOKEN_ENDPOINT, {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                        "device_code": flow.device_code, "client_id": app_id, "client_secret": secret})
            except _OAuthRejection as error:
                if error.error == "authorization_pending":
                    continue
                if error.error == "slow_down":
                    interval = min(interval + 5, 60)
                    continue
                if error.error in {"access_denied", "invalid_grant", "expired_token"}:
                    data.pop("login_generation", None)
                    _save(data)
                    raise LoginRequired(str(error)) from None
                raise
            if cancel_event.is_set():
                raise LoginRequired("本次飞书连接已取消。")
            session = _session_values(result)
            if not session["refresh_token"]:
                raise ConfigurationRequired("此次授权没有取得自动续期权限。请在应用中开通 offline_access，并启用「刷新 user_access_token」（若有此开关），发布后重新连接。")
            data.update(session)
            data.pop("login_generation", None)
            _save(data)
            return _status(data)
    raise LoginRequired("浏览器授权已超时，请重新点击「连接飞书」。")


def get_access_token(*, force_refresh=False):
    with _locked():
        data = _read()
        app_id, secret = _credentials(data)
        now = time.time()
        if not force_refresh and data.get("access_token") and float(data.get("expires_at", 0)) > now + 120:
            return data["access_token"]
        refresh_expiry = float(data.get("refresh_expires_at", 0))
        if not data.get("refresh_token") or refresh_expiry and refresh_expiry <= now:
            raise LoginRequired("飞书尚未连接或登录已过期，请点击「连接飞书」。")
        try:
            result = _oauth_request(TOKEN_ENDPOINT, {"grant_type": "refresh_token", "refresh_token": data["refresh_token"],
                                    "client_id": app_id, "client_secret": secret})
        except _OAuthRejection as error:
            if error.error in {"invalid_grant", "expired_token", "access_denied"}:
                data = {key: value for key, value in data.items() if key in {"app_id", "app_secret", "revision"}}
                _save(data)
                raise LoginRequired("飞书登录已失效，请重新点击「连接飞书」。") from None
            raise
        data.update(_session_values(result, data))
        _save(data)
        return data["access_token"]


def disconnect():
    with _locked():
        data = _read()
        data = {key: value for key, value in data.items() if key in {"app_id", "app_secret", "revision"}}
        _save(data)
        return _status(data)
