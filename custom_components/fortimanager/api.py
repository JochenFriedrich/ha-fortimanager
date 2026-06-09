"""FortiManager JSON-RPC API client."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

class FortiManagerAuthError(Exception):
    """Raised on authentication failure."""


class FortiManagerConnectionError(Exception):
    """Raised on connection failure."""


class FortiManagerClient:
    """Async JSON-RPC client for FortiManager."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = True,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._session_token: str | None = None
        self._owned_session = session is None
        self._session = session or aiohttp.ClientSession()

    @property
    def base_url(self) -> str:
        return f"https://{self._host}:{self._port}/jsonrpc"

    async def _request(self, method: str, params: list[dict]) -> Any:
        payload: dict[str, Any] = {
            "id": 1,
            "method": method,
            "params": params,
            "verbose": 1,
        }
        if self._session_token:
            payload["session"] = self._session_token

        try:
            async with self._session.post(
                self.base_url,
                json=payload,
                ssl=self._verify_ssl,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientConnectorError as err:
            raise FortiManagerConnectionError(f"Cannot connect to FortiManager: {err}") from err
        except aiohttp.ClientError as err:
            raise FortiManagerConnectionError(f"Request failed: {err}") from err

        result = data.get("result", [{}])[0]
        status = result.get("status", {})
        code = status.get("code", -1)

        if code != 0:
            msg = status.get("message", "Unknown error")
            if code in (-6, -11):
                raise FortiManagerAuthError(f"Authentication failed: {msg}")
            raise FortiManagerConnectionError(f"API error {code}: {msg}")

        return data

    async def login(self) -> None:
        """Authenticate and store session token."""
        result = await self._request(
            "exec",
            [{"url": "sys/login/user", "data": {"user": self._username, "passwd": self._password}}],
        )
        self._session_token = result["session"]
        _LOGGER.debug("FortiManager login successful")

    async def logout(self) -> None:
        """Log out and invalidate the session."""
        if self._session_token:
            try:
                await self._request("exec", [{"url": "sys/logout"}])
            except Exception:  # noqa: BLE001
                pass
            self._session_token = None

    async def get_devices(self) -> list[dict]:
        """Return list of managed devices."""
        if not self._session_token:
            await self.login()

        try:
            result = await self._request(
                "get",
                [
                    {
                        "url": "dvmdb/device",
                        "loadsub": 1,
                        "option": ["get meta", "get used"],
                    }
                ],
            )
        except FortiManagerAuthError:
            # Session may have expired — re-login once
            _LOGGER.debug("Session expired, re-authenticating")
            self._session_token = None
            await self.login()
            result = await self._request(
                "get",
                [{"url": "dvmdb/device", "loadsub": 1}],
            )

        result = result.get("result", [{}])[0]
        data = result.get("data")
        return data if isinstance(data, list) else []

    async def close(self) -> None:
        """Clean up."""
        await self.logout()
        if self._owned_session:
            await self._session.close()
