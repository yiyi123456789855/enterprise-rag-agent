import os
import unittest

from fastapi import HTTPException

from api.dependencies import get_settings
from api.security import require_api_key


class SecurityTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("APP_API_KEY", None)
        get_settings.cache_clear()

    def test_configured_api_key_is_required(self):
        os.environ["APP_API_KEY"] = "server-secret"
        get_settings.cache_clear()

        with self.assertRaises(HTTPException) as context:
            require_api_key("wrong-key")
        self.assertEqual(context.exception.status_code, 401)
        self.assertIsNone(require_api_key("server-secret"))


if __name__ == "__main__":
    unittest.main()

