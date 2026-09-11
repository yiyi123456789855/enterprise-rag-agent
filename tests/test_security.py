import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import get_settings
from api.security import (
    _claims_to_context,
    _decode_oidc_token,
    get_auth_context,
    require_api_key,
    require_roles,
)
from app.auth import AuthContext
from app.config import Settings


class SecurityTests(unittest.TestCase):
    def tearDown(self):
        for name in (
            "APP_API_KEY",
            "APP_ENV",
            "AUTH_MODE",
            "OIDC_ISSUER",
            "OIDC_AUDIENCE",
            "OIDC_JWKS_URL",
        ):
            os.environ.pop(name, None)
        get_settings.cache_clear()

    def test_configured_api_key_is_required(self):
        os.environ["APP_API_KEY"] = "server-secret"
        get_settings.cache_clear()

        with self.assertRaises(HTTPException) as context:
            require_api_key("wrong-key")
        self.assertEqual(context.exception.status_code, 401)
        self.assertIsNone(require_api_key("server-secret"))

    def test_production_refuses_legacy_identity_mode(self):
        settings = Settings(app_environment="production", auth_mode="legacy")
        with self.assertRaisesRegex(RuntimeError, "Production requires AUTH_MODE=oidc"):
            settings.validate()

    def test_oidc_requires_complete_provider_configuration(self):
        settings = Settings(auth_mode="oidc")
        with self.assertRaisesRegex(RuntimeError, "OIDC configuration is incomplete"):
            settings.validate()

    def test_claims_become_trusted_auth_context(self):
        settings = Settings(auth_mode="oidc")
        context = _claims_to_context(
            {
                "sub": " user-123 ",
                "tenant_id": "company-a",
                "departments": ["研发部", "研发部", "算法组"],
                "roles": "document-editor,auditor",
            },
            settings,
        )
        self.assertEqual(context.user_id, "user-123")
        self.assertEqual(context.tenant_id, "company-a")
        self.assertEqual(context.departments, ("研发部", "算法组"))
        self.assertEqual(context.roles, frozenset({"document-editor", "auditor"}))

    def test_missing_tenant_claim_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            _claims_to_context({"sub": "user-123"}, Settings(auth_mode="oidc"))
        self.assertEqual(context.exception.status_code, 401)

    def test_oidc_context_uses_verified_claims(self):
        os.environ.update(
            {
                "AUTH_MODE": "oidc",
                "OIDC_ISSUER": "https://id.example.com",
                "OIDC_AUDIENCE": "rag-api",
                "OIDC_JWKS_URL": "https://id.example.com/jwks",
            }
        )
        get_settings.cache_clear()
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
        with patch(
            "api.security._decode_oidc_token",
            return_value={"sub": "trusted-user", "tenant_id": "trusted-tenant"},
        ):
            context = get_auth_context(credentials, None)
        self.assertEqual(context.user_id, "trusted-user")
        self.assertEqual(context.tenant_id, "trusted-tenant")
        self.assertFalse(context.legacy)

    def test_role_requirement_is_enforced_only_for_oidc(self):
        user = AuthContext("user", "tenant", roles=frozenset({"reader"}))
        with self.assertRaises(HTTPException) as context:
            require_roles(user, "knowledge-admin")
        self.assertEqual(context.exception.status_code, 403)

        legacy = AuthContext("", "", legacy=True)
        self.assertIsNone(require_roles(legacy, "knowledge-admin"))

    def test_real_rsa_signature_and_audience_are_verified(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        settings = Settings(
            auth_mode="oidc",
            oidc_issuer="https://id.example.com",
            oidc_audience="rag-api",
            oidc_jwks_url="https://id.example.com/jwks",
        )
        claims = {
            "sub": "user-123",
            "tenant_id": "company-a",
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
        fake_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=private_key.public_key())
        )
        with patch("api.security._get_jwk_client", return_value=fake_client):
            decoded = _decode_oidc_token(token, settings)
            self.assertEqual(decoded["sub"], "user-123")

            wrong_audience = jwt.encode(
                {**claims, "aud": "another-api"},
                private_key,
                algorithm="RS256",
                headers={"kid": "test-key"},
            )
            with self.assertRaises(HTTPException) as context:
                _decode_oidc_token(wrong_audience, settings)
            self.assertEqual(context.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
