"""Interactive VK authorization with image and browser CAPTCHA support."""
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from vkpymusic import Service, VkMobileClient
from vkpymusic.vk_api import VkApiException, VkApiRequestBuilder, make_request_async

from app.storage.database import save_credentials

PENDING_TTL_SECONDS = 10 * 60
MAX_CAPTCHA_REFRESHES = 3
_ALLOWED_CAPTCHA_HOSTS = {"id.vk.com", "id.vk.ru"}
_ALLOWED_CAPTCHA_IMAGE_HOSTS = {"api.vk.com", "vk.com", "login.vk.com", "id.vk.com", "id.vk.ru"}


class VKAuthChallenge(Exception):
    def __init__(self, details: dict[str, Any]) -> None:
        super().__init__(str(details.get("error") or "VK authorization challenge"))
        self.details = details


class VKAuthError(Exception):
    pass


def validate_browser_captcha_link(value: Any) -> str:
    """Accept only VK ID's HTTPS CAPTCHA page; never reflect arbitrary URLs."""
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ValueError("VK returned an invalid CAPTCHA link")
    if any(ord(char) < 32 for char in value):
        raise ValueError("VK returned an invalid CAPTCHA link")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("VK returned an invalid CAPTCHA link") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_CAPTCHA_HOSTS
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/not_robot_captcha"
        or not parsed.query
    ):
        raise ValueError("VK returned an unsupported CAPTCHA link")
    return value


def validate_legacy_captcha_image(value: Any) -> str:
    """Accept only HTTPS CAPTCHA images hosted by VK."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("VK returned an invalid CAPTCHA image URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("VK returned an invalid CAPTCHA image URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_CAPTCHA_IMAGE_HOSTS
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.endswith(("/captcha.php", "/captcha"))
        or not parsed.query
    ):
        raise ValueError("VK returned an unsupported CAPTCHA image URL")
    return value


def build_auth_request(
    login: str,
    password: str,
    *,
    code: str | None = None,
    captcha_sid: str | None = None,
    captcha_answer: str | None = None,
    captcha_success_token: str | None = None,
):
    """Build VK's password grant without forcing SMS or solving CAPTCHA locally."""
    request = VkApiRequestBuilder.build_req_auth(
        login=login, password=password, client=VkMobileClient, code=code
    )
    # vkpymusic 4.0.2 hard-codes force_sms=1. Let VK choose SMS/call/app.
    request.params.pop("force_sms", None)
    if captcha_sid and captcha_answer:
        request.params["captcha_sid"] = captcha_sid
        request.params["captcha_key"] = captcha_answer
    if captcha_success_token:
        # VK ID's browser CAPTCHA token is distinct from the legacy image key.
        request.params["success_token"] = captcha_success_token
    return request


async def request_vk_token(
    login: str,
    password: str,
    *,
    code: str | None = None,
    captcha_sid: str | None = None,
    captcha_answer: str | None = None,
    captcha_success_token: str | None = None,
) -> str:
    request = build_auth_request(
        login,
        password,
        code=code,
        captcha_sid=captcha_sid,
        captcha_answer=captcha_answer,
        captcha_success_token=captcha_success_token,
    )
    try:
        response = await make_request_async(request)
    except VkApiException as err:
        details = err.details if isinstance(err.details, dict) else {}
        if details.get("error"):
            raise VKAuthChallenge(details) from err
        raise VKAuthError(f"VK rejected authorization (error {err.error_code})") from err
    token = response.data.get("access_token")
    if not token:
        raise VKAuthError("VK response did not contain an access token")
    return str(token)


async def request_vk_validation(sid: str) -> None:
    request = VkApiRequestBuilder.build_req_2fa_code(client=VkMobileClient, sid=sid)
    try:
        await make_request_async(request)
    except VkApiException as err:
        details = err.details if isinstance(err.details, dict) else {}
        message = details.get("error_msg") or details.get("error") or err.error_msg
        raise VKAuthError(f"VK could not start verification: {message}") from err


def _supports_device_approval(validation_type: str) -> bool:
    value = validation_type.casefold()
    return any(part in value for part in ("push", "max", "approve", "confirm", "message"))


def challenge_view(
    details: dict[str, Any],
    challenge_id: str,
    error: str | None = None,
) -> dict[str, Any]:
    kind = str(details.get("error") or "")
    validation = str(details.get("validation_type") or "")
    if kind == "need_captcha":
        redirect_uri = details.get("redirect_uri")
        if redirect_uri:
            try:
                link = validate_browser_captcha_link(redirect_uri)
            except ValueError:
                challenge = {
                    "type": "unsupported_captcha",
                    "label": "VK запросил браузерную CAPTCHA, но прислал ссылку неизвестного формата.",
                    "hint": "Не открывайте сторонние ссылки. Используйте ручное подключение токена ниже или начните вход заново.",
                }
            else:
                challenge = {
                    "type": "browser_captcha",
                    "link": link,
                    "label": "Пройдите проверку VK в блоке ниже",
                    "hint": "Ссылка одноразовая. Завершите проверку и сразу нажмите «Проверить и продолжить».",
                }
        elif details.get("captcha_sid") and details.get("captcha_img"):
            try:
                image_url = validate_legacy_captcha_image(details.get("captcha_img"))
            except ValueError:
                challenge = {
                    "type": "unsupported_captcha",
                    "label": "VK прислал изображение CAPTCHA с неизвестного адреса.",
                    "hint": "В целях безопасности изображение не загружено. Начните вход заново или используйте ручное подключение токена.",
                }
            else:
                challenge = {
                    "type": "captcha",
                    "image": image_url,
                    "label": "Введите символы с изображения VK",
                }
        else:
            challenge = {
                "type": "unsupported_captcha",
                "label": "VK запросил CAPTCHA неподдерживаемого формата.",
                "hint": "Используйте ручное подключение проверенного access token ниже или начните вход заново.",
            }
    else:
        labels = {
            "2fa_sms": "Код из SMS",
            "2fa_callreset": "Последние четыре цифры номера входящего звонка",
            "2fa_app": "Код из приложения VK",
        }
        approval_supported = _supports_device_approval(validation)
        challenge = {
            "type": "verification_code",
            "validation_type": validation,
            "phone_mask": details.get("phone_mask"),
            "label": labels.get(validation, "Код подтверждения VK"),
            "approval_supported": approval_supported,
            "hint": (
                "Введите код или подтвердите вход в приложении VK/MAX на другом устройстве и отметьте это ниже."
                if approval_supported
                else "Введите код подтверждения. Для проверки звонком введите последние четыре цифры номера."
            ),
        }
    return {
        "state": "challenge_required",
        "challenge_id": challenge_id,
        "challenge": challenge,
        "error": error,
    }


class VKAuthManager:
    """Pending login/challenge data is short-lived memory state; only tokens persist."""

    _SENSITIVE_FIELDS = (
        "login",
        "password",
        "code",
        "captcha_answer",
        "captcha_success_token",
        "captcha_redirect_uri",
        "captcha_sid",
    )

    def __init__(self, database_path) -> None:
        self.database_path = database_path
        self.pending: dict[str, dict[str, Any]] = {}
        self._expiry_handles: dict[str, asyncio.TimerHandle] = {}

    def _discard(self, challenge_id: str) -> None:
        expiry = self._expiry_handles.pop(challenge_id, None)
        if expiry is not None:
            expiry.cancel()
        session = self.pending.pop(challenge_id, None)
        if session:
            for key in self._SENSITIVE_FIELDS:
                if key in session:
                    session[key] = ""

    def _expire_old_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, session in self.pending.items()
            if now - session.get("created_at", 0) > PENDING_TTL_SECONDS
        ]
        for key in expired:
            self._discard(key)

    async def start(self, login: str, password: str) -> dict[str, Any]:
        self._expire_old_sessions()
        if not login.strip() or not password:
            raise ValueError("Введите телефон/email и пароль VK")
        # A new login replaces abandoned pending logins and clears their secrets.
        self.cancel_all()
        challenge_id = secrets.token_urlsafe(24)
        self.pending[challenge_id] = {
            "login": login.strip(),
            "password": password,
            "code": None,
            "captcha_sid": None,
            "captcha_answer": None,
            "captcha_success_token": None,
            "captcha_redirect_uri": None,
            "captcha_kind": None,
            "captcha_refreshes": 0,
            "pending_validation": None,
            "requested_sid": None,
            "created_at": time.monotonic(),
        }
        loop = asyncio.get_running_loop()
        self._expiry_handles[challenge_id] = loop.call_later(
            PENDING_TTL_SECONDS, self._discard, challenge_id
        )
        return await self._attempt(challenge_id)

    async def submit(
        self,
        challenge_id: str,
        answer: str,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self._expire_old_sessions()
        session = self.pending.get(challenge_id)
        if not session:
            raise ValueError("Сеанс авторизации истёк. Начните вход заново.")
        value = answer.strip()
        captcha_kind = session.get("captcha_kind")
        if captcha_kind == "browser":
            if not value:
                raise ValueError("VK не вернул токен CAPTCHA")
            session["captcha_success_token"] = value
        elif captcha_kind == "image":
            if not value:
                raise ValueError("Введите символы с изображения VK")
            session["captcha_answer"] = value
        elif captcha_kind == "unsupported":
            raise ValueError("Эта CAPTCHA не поддерживается. Используйте ручное подключение токена.")
        elif value:
            session["code"] = value
        elif (
            approved
            and session.get("pending_validation")
            and _supports_device_approval(
                str(session["pending_validation"].get("validation_type") or "")
            )
        ):
            # Device approval is completed in the VK app; VK must be polled
            # with the same pending authorization request and no OTP code.
            session["code"] = None
        else:
            raise ValueError("Введите код или подтвердите вход на другом устройстве")
        return await self._attempt(challenge_id)

    async def refresh_captcha(self, challenge_id: str) -> dict[str, Any]:
        """Request a fresh VK CAPTCHA link after the one-use browser link expires."""
        self._expire_old_sessions()
        session = self.pending.get(challenge_id)
        if not session:
            raise ValueError("Сеанс авторизации истёк. Начните вход заново.")
        if session.get("captcha_kind") != "browser":
            raise ValueError("Для текущего шага обновление CAPTCHA недоступно")
        if session.get("captcha_refreshes", 0) >= MAX_CAPTCHA_REFRESHES:
            self._discard(challenge_id)
            raise VKAuthError("VK CAPTCHA несколько раз истекла. Начните вход заново.")
        session["captcha_refreshes"] += 1
        session["captcha_kind"] = None
        session["captcha_redirect_uri"] = None
        session["captcha_success_token"] = None
        return await self._attempt(challenge_id)

    async def _attempt(self, challenge_id: str) -> dict[str, Any]:
        session = self.pending[challenge_id]
        try:
            token = await request_vk_token(
                session["login"],
                session["password"],
                code=session.get("code"),
                captcha_sid=session.get("captcha_sid"),
                captcha_answer=session.get("captcha_answer"),
                captcha_success_token=session.get("captcha_success_token"),
            )
        except VKAuthChallenge as exc:
            details = exc.details
            error = str(details.get("error") or "")

            # One-time answers are consumed by each request, successful or not.
            session["code"] = None
            session["captcha_sid"] = None
            session["captcha_answer"] = None
            session["captcha_success_token"] = None

            if error == "invalid_client":
                self._discard(challenge_id)
                raise VKAuthError("VK не принял логин или пароль") from exc
            if error == "9;Flood control" or details.get("error_type") == "password_bruteforce_attempt":
                self._discard(challenge_id)
                raise VKAuthError("VK временно ограничил попытки входа. Попробуйте позже.") from exc

            if error == "need_captcha":
                session["pending_validation"] = None
                redirect_uri = details.get("redirect_uri")
                if redirect_uri:
                    try:
                        session["captcha_redirect_uri"] = validate_browser_captcha_link(redirect_uri)
                        session["captcha_kind"] = "browser"
                    except ValueError:
                        session["captcha_kind"] = "unsupported"
                        session["captcha_redirect_uri"] = None
                elif details.get("captcha_sid") and details.get("captcha_img"):
                    try:
                        validate_legacy_captcha_image(details.get("captcha_img"))
                    except ValueError:
                        session["captcha_kind"] = "unsupported"
                    else:
                        session["captcha_kind"] = "image"
                        session["captcha_sid"] = str(details["captcha_sid"])
                else:
                    session["captcha_kind"] = "unsupported"
                return challenge_view(details, challenge_id)

            if error == "need_validation":
                session["captcha_kind"] = None
                session["captcha_redirect_uri"] = None
                session["pending_validation"] = details
                sid = str(details.get("validation_sid") or "")
                if sid and sid != session.get("requested_sid"):
                    try:
                        await request_vk_validation(sid)
                    except VKAuthError:
                        self._discard(challenge_id)
                        raise
                    session["requested_sid"] = sid
                return challenge_view(details, challenge_id)

            if error == "invalid_request" and session.get("captcha_kind") in {"browser", "image"}:
                # The browser token/image answer was rejected or expired. Drop it and
                # ask VK for a fresh challenge instead of reusing a consumed link.
                session["captcha_kind"] = None
                session["captcha_redirect_uri"] = None
                if session.get("captcha_refreshes", 0) < MAX_CAPTCHA_REFRESHES:
                    session["captcha_refreshes"] += 1
                    return await self._attempt(challenge_id)
                self._discard(challenge_id)
                raise VKAuthError(
                    "VK не принял ответ CAPTCHA. Слишком много повторов; начните вход заново."
                ) from exc

            if error == "invalid_request" and session.get("pending_validation"):
                return challenge_view(
                    session["pending_validation"],
                    challenge_id,
                    "VK не принял подтверждение. Проверьте код и повторите ввод.",
                )

            self._discard(challenge_id)
            raise VKAuthError(f"Неподдерживаемый ответ VK: {error or 'unknown'}") from exc
        except Exception:
            self._discard(challenge_id)
            raise

        user_agent = VkMobileClient.user_agent
        service = Service(user_agent=user_agent, token=token)
        try:
            if not await service.is_token_valid_async():
                raise VKAuthError("VK выдал токен, но проверка токена не прошла")
            user = await service.get_user_info_async()
            user_id = str(getattr(user, "userid", "") or "")
            save_credentials(self.database_path, token, user_agent, user_id or None)
        except VKAuthError:
            self._discard(challenge_id)
            raise
        except Exception as exc:
            self._discard(challenge_id)
            raise VKAuthError(f"Не удалось проверить токен VK ({type(exc).__name__})") from exc

        self._discard(challenge_id)
        return {"state": "authenticated", "authenticated": True, "user_id": user_id or None}

    def cancel(self, challenge_id: str) -> bool:
        existed = challenge_id in self.pending
        self._discard(challenge_id)
        return existed

    def cancel_all(self) -> None:
        for challenge_id in list(self.pending):
            self._discard(challenge_id)
