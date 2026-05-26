"""Homebridge Config UI X API client.

Handles authentication (noauth + login), accessory discovery, and control
via the Homebridge REST API.
"""

from __future__ import annotations

import json as _json
import logging
import subprocess
import time

import httpx

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"Lightbulb", "Switch", "Outlet"}


class HomebridgeClient:
    """Async client for the Homebridge Config UI X REST API."""

    def __init__(
        self, host: str, port: int, username: str = "", password: str = ""
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expires: float = 0.0
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def configured(self) -> bool:
        return bool(self._host)

    @property
    def connected(self) -> bool:
        return self._token is not None and time.monotonic() < self._token_expires

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def connect(self) -> bool:
        """Authenticate and cache token. Returns True on success."""
        if not self.configured:
            return False
        if not self._client:
            await self.start()

        # Try noauth first (httpx, then curl fallback)
        data = await self._auth_post("/api/auth/noauth", {})
        if data and "access_token" in data:
            self._store_token(data)
            logger.info("Homebridge connected (noauth) at %s", self.base_url)
            return True

        # Try login if credentials are configured
        if self._username and self._password:
            data = await self._auth_post(
                "/api/auth/login",
                {"username": self._username, "password": self._password},
            )
            if data and "access_token" in data:
                self._store_token(data)
                logger.info("Homebridge connected (login) at %s", self.base_url)
                return True

        logger.warning("Cannot connect to Homebridge at %s", self.base_url)
        return False

    async def _auth_post(self, path: str, body: dict) -> dict | None:
        """POST to an auth endpoint, with curl fallback."""
        try:
            if self._client:
                resp = await self._client.post(
                    f"{self.base_url}{path}", json=body
                )
                if resp.status_code == 201:
                    return resp.json()
                return None
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.debug("httpx auth failed, trying curl for %s", path)

        return self._curl_request("POST", path, {}, body)

    async def get_accessories(self) -> list[dict]:
        """Return accessories filtered to lights/switches."""
        data = await self._request("GET", "/api/accessories")
        if data is None:
            return []
        return [
            {
                "uniqueId": a["uniqueId"],
                "serviceName": a.get("serviceName", ""),
                "type": a.get("type", ""),
                "values": a.get("values", {}),
            }
            for a in data
            if a.get("type") in SUPPORTED_TYPES
        ]

    async def get_accessory(self, unique_id: str) -> dict | None:
        """Return a single accessory by uniqueId."""
        return await self._request("GET", f"/api/accessories/{unique_id}")

    async def set_characteristic(
        self, unique_id: str, characteristic: str, value
    ) -> dict | None:
        """Set a characteristic on an accessory. Returns updated values."""
        return await self._request(
            "PUT",
            f"/api/accessories/{unique_id}",
            json={"characteristicType": characteristic, "value": value},
        )

    async def toggle(self, unique_id: str) -> bool | None:
        """Toggle the 'On' characteristic. Returns new state, or None on error."""
        accessory = await self.get_accessory(unique_id)
        if accessory is None:
            return None
        current = accessory.get("values", {}).get("On", False)
        new_value = not current
        result = await self.set_characteristic(
            unique_id, "On", 1 if new_value else 0
        )
        if result is not None:
            return new_value
        return None

    def update_config(self, host: str, port: int, username: str, password: str) -> None:
        """Update connection settings (clears cached token)."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._token = None
        self._token_expires = 0.0

    async def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        """Make an authenticated request, auto-reconnecting on 401."""
        if not self.connected:
            if not await self.connect():
                return None

        headers = {"Authorization": f"Bearer {self._token}"}
        json_body = kwargs.get("json")

        try:
            if self._client:
                resp = await self._client.request(
                    method, f"{self.base_url}{path}", headers=headers, **kwargs
                )
                if resp.status_code == 401:
                    if await self.connect():
                        headers = {"Authorization": f"Bearer {self._token}"}
                        resp = await self._client.request(
                            method, f"{self.base_url}{path}", headers=headers, **kwargs
                        )
                    else:
                        return None
                if resp.is_success:
                    return resp.json()
                logger.warning("Homebridge %s %s → %s", method, path, resp.status_code)
                return None
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.debug("httpx failed, falling back to curl for %s %s", method, path)

        return self._curl_request(method, path, headers, json_body)

    def _curl_request(
        self, method: str, path: str, headers: dict, json_body=None
    ) -> dict | list | None:
        """Fallback HTTP via curl (works through macOS network extensions)."""
        url = f"{self.base_url}{path}"
        cmd = ["curl", "-s", "--max-time", "10", "-X", method]
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
        if json_body is not None:
            cmd.extend(["-H", "Content-Type: application/json", "-d", _json.dumps(json_body)])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                return _json.loads(result.stdout)
        except (subprocess.TimeoutExpired, _json.JSONDecodeError, OSError) as e:
            logger.warning("curl fallback failed for %s %s: %s", method, path, e)
        return None

    def _store_token(self, data: dict) -> None:
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        if isinstance(expires_in, str):
            expires_in = 3600
        self._token_expires = time.monotonic() + expires_in - 60
