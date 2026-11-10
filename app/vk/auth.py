"""Interactive VK authorization built on vkpymusic 4.0.2."""
from __future__ import annotations

import secrets
from typing import Any

from vkpymusic import Service, VkMobileClient
from vkpymusic.vk_api import VkApiException, VkApiRequestBuilder, make_request_async

from app.storage.database import save_credentials


class VKAuthChallenge(Exception):
    def __init__(self, details: dict[str, Any]) -> None:
        super().__init__(str(details.get("error") or "VK authorization challenge"))
        self.details = details


class VKAuthError(Exception):
    pass


async def request_vk_token(login: str, password: str, *, code: str | None = None,
                           captcha_sid: str | None = None,
                           captcha_answer: str | None = None) -> str:
    request = VkApiRequestBuilder.build_req_auth(
        login=login, password=password, client=VkMobileClient, code=code
    )
    # Let VK choose the validation channel instead of forcing SMS.
    request.params.pop("force_sms", None)
    if captcha_sid and captcha_answer:
        request.params["captcha_sid"] = captcha_sid
        request.params["captcha_key"] = captcha_answer
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


def challenge_view(details: dict[str, Any], challenge_id: str,
                   error: str | None = None) -> dict[str, Any]:
    kind = str(details.get("error") or "")
    validation = str(details.get("validation_type") or "")
    if kind == "need_captcha":
        challenge = {
            "type": "captcha", "image": details.get("captcha_img"),
            "label": "Введите символы с изображения VK",
        }
    else:
        labels = {
            "2fa_sms": "Код из SMS",
            "2fa_callreset": "Последние четыре цифры номера входящего звонка",
            "2fa_app": "Код из приложения VK",
        }
        challenge = {
            "type": "verification_code", "validation_type": validation,
            "phone_mask": details.get("phone_mask"),
            "label": labels.get(validation, "Код подтверждения VK"),
            "hint": "Введите код или последние четыре цифры номера звонка, если VK выбрал звонок.",
        }
    return {"state": "challenge_required", "challenge_id": challenge_id,
            "challenge": challenge, "error": error}


class VKAuthManager:
    """Pending password/challenge state lives only in memory; final token is durable."""

    def __init__(self, database_path) -> None:
        self.database_path = database_path
        self.pending: dict[str, dict[str, Any]] = {}

    async def start(self, login: str, password: str) -> dict[str, Any]:
        if not login.strip() or not password:
            raise ValueError("Введите телефон/email и пароль VK")
        challenge_id = secrets.token_urlsafe(24)
        self.pending[challenge_id] = {
            "login": login.strip(), "password": password, "code": None,
            "captcha_sid": None, "captcha_answer": None,
            "pending_validation": None, "requested_sid": None,
        }
        return await self._attempt(challenge_id)

    async def submit(self, challenge_id: str, answer: str) -> dict[str, Any]:
        session = self.pending.get(challenge_id)
        if not session:
            raise ValueError("Сеанс авторизации истёк. Начните вход заново.")
        if session.get("captcha_sid"):
            session["captcha_answer"] = answer.strip()
        else:
            session["code"] = answer.strip()
        return await self._attempt(challenge_id)

    async def _attempt(self, challenge_id: str) -> dict[str, Any]:
        session = self.pending[challenge_id]
        try:
            token = await request_vk_token(
                session["login"], session["password"], code=session.get("code"),
                captcha_sid=session.get("captcha_sid"),
                captcha_answer=session.get("captcha_answer"),
            )
        except VKAuthChallenge as exc:
            details = exc.details
            error = str(details.get("error") or "")
            session["code"] = session["captcha_sid"] = session["captcha_answer"] = None
            if error == "invalid_client":
                self.pending.pop(challenge_id, None)
                raise VKAuthError("VK не принял логин или пароль") from exc
            if error == "9;Flood control" or details.get("error_type") == "password_bruteforce_attempt":
                self.pending.pop(challenge_id, None)
                raise VKAuthError("VK временно ограничил попытки входа. Попробуйте позже.") from exc
            if error == "need_validation":
                sid = str(details.get("validation_sid") or "")
                if sid and sid != session.get("requested_sid"):
                    await request_vk_validation(sid)
                    session["requested_sid"] = sid
                session["pending_validation"] = details
                return challenge_view(details, challenge_id)
            if error == "invalid_request" and session.get("pending_validation"):
                return challenge_view(session["pending_validation"], challenge_id,
                                      "VK не принял подтверждение. Проверьте код и повторите ввод.")
            if error == "need_captcha":
                session["captcha_sid"] = str(details.get("captcha_sid") or "")
                return challenge_view(details, challenge_id)
            self.pending.pop(challenge_id, None)
            raise VKAuthError(f"Неподдерживаемый ответ VK: {error or 'unknown'}") from exc
        except Exception:
            self.pending.pop(challenge_id, None)
            raise

        user_agent = VkMobileClient.user_agent
        service = Service(user_agent=user_agent, token=token)
        try:
            if not await service.is_token_valid_async():
                raise VKAuthError("VK выдал токен, но проверка токена не прошла")
            user = await service.get_user_info_async()
            user_id = str(getattr(user, "userid", "") or "")
        except VKAuthError:
            self.pending.pop(challenge_id, None)
            raise
        except Exception as exc:
            self.pending.pop(challenge_id, None)
            raise VKAuthError(f"Не удалось проверить токен VK ({type(exc).__name__})") from exc

        save_credentials(self.database_path, token, user_agent, user_id or None)
        self.pending.pop(challenge_id, None)
        return {"state": "authenticated", "authenticated": True, "user_id": user_id or None}

    def cancel(self, challenge_id: str) -> bool:
        session = self.pending.pop(challenge_id, None)
        if session:
            session["password"] = ""
        return session is not None

    def cancel_all(self) -> None:
        for session in self.pending.values():
            session["password"] = ""
        self.pending.clear()
