from jwcrypto import jwk
from starlette.responses import JSONResponse
from starlette.requests import Request
import uuid
from typing import Any

import jwt
import time
import json
import hashlib
import httpx
import logging

from jwt import PyJWK, PyJWKClient

logger = logging.getLogger(__name__)
AUTH_HEADER_PREFIX = "Bearer "


class PushNotificationAuth:
    def _calculate_request_body_sha256(self, data: dict[str, Any]):
        body_str = json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            indent=None,
        )
        return hashlib.sha256(body_str.encode()).hexdigest()


class PushNotificationSenderAuth(PushNotificationAuth):
    def __init__(self):
        self.public_keys = []
        self.private_key_jwk: PyJWK = None

    @staticmethod
    async def verify_push_notification_url(url: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                validation_token = str(uuid.uuid4())
                response = await client.get(url, params={"validation_token": validation_token})
                response.raise_for_status()
                is_verified = response.text == validation_token
                logger.info(f"Verified push-notification URL :{url}->{is_verified}")
                return is_verified
            except Exception as e:
                logger.error(f"Failed to verify push-notification URL {url}: {e}")
        return False

    def generate_jwk(self):
        key = jwk.JWK.generate(kty="RSA", size=2048, kid=str(uuid.uuid4()), use='sig')
        self.public_keys.append(key.export_public(as_dict=True))
        self.private_key_jwk = PyJWK.from_json(key.export_private())

    def handle_jwks_endpoint(self, _request: Request):
        return JSONResponse({"keys": self.public_keys})

    def _generate_jwt(self, data: dict[str, Any]):
        iat = int(time.time())
        return jwt.encode({"iat": iat,
                           "request_body_sha256": self._calculate_request_body_sha256(data)},
                          key=self.private_key_jwk,
                          headers={"kid": self.private_key_jwk.key_id},
                          algorithm="RS256")

    async def send_push_notification(self, url: str, data: dict[str, Any]):
        jwt_token = self._generate_jwt(data)
        headers = {"Authorization": f'Bearer {jwt_token}'}
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                logger.info(f"Sent push-notification to {url}")
            except Exception as e:
                logger.error(f"Failed to send push-notification to {url}: {e}")


class PushNotificationReceiverAuth(PushNotificationAuth):
    def __init__(self):
        self.public_keys_jwks = []
        self.jwks_client = []

    async def load_jwks(self, jwks_url: str):
        self.jwks_client = PyJWKClient(jwks_url)

    async def verify_push_notification(self, request: Request) -> bool:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith(AUTH_HEADER_PREFIX):
            logger.error("Authorization header is missing or invalid")
            return False

        token = auth_header[len(AUTH_HEADER_PREFIX):]
        signing_key = self.jwks_client.get_signing_key_from_jwt(token)

        decode_token = jwt.decode(token, signing_key.key, algorithms=["RS256"],
                                  options={"require": ['iat', "request_body_sha256"]})

        actual_body_sha256 = self._calculate_request_body_sha256(await request.json())
        if actual_body_sha256 != decode_token["request_body_sha256"]:
            raise ValueError("Invalid request body")

        if time.time() - decode_token["iat"] > 60 * 5:
            raise ValueError("Token expired")

        return True
