import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from starlette.requests import Request
from config import settings
from routers.auth import production_login_limit
from security import rate_limiter


class ProductionLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_login_unrestricted_production_limit_enforced(self):
        request = Request({'type':'http', 'client':('127.0.0.1', 1234), 'headers':[]})
        with patch.object(settings, 'ENVIRONMENT', 'development'), patch.object(rate_limiter, 'hit', AsyncMock(return_value=False)) as hit:
            await production_login_limit(request)
            hit.assert_not_awaited()
        with patch.object(settings, 'ENVIRONMENT', 'production'), patch.object(rate_limiter, 'hit', AsyncMock(return_value=False)) as hit:
            with self.assertRaises(HTTPException) as error:
                await production_login_limit(request)
            self.assertEqual(error.exception.status_code, 429)
            hit.assert_awaited_once_with('login:127.0.0.1', 20, 300)
