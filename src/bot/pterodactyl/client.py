from __future__ import annotations

import logging
from typing import Any, Self

import httpx

from bot.config import Settings
from bot.pterodactyl.models import PowerAction, PowerState, ResourceUsage, Server

logger = logging.getLogger("bot")

ACCEPT_HEADER = "Application/vnd.pterodactyl.v1+json"


class PterodactylAPIError(Exception):
    def __init__(self, identifier: str, status_code: int, detail: str) -> None:
        self.identifier = identifier
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"Pterodactyl API error for '{identifier}': {status_code} {detail}"
        )


class PterodactylClient:
    def __init__(self, settings: Settings) -> None:
        self._app_api_key = settings.pterodactyl_app_api_key
        self._client_api_key = settings.pterodactyl_client_api_key

        if settings.pterodactyl_skip_ssl_verify:
            logger.warning(
                "PTERODACTYL_SKIP_SSL_VERIFY is enabled: TLS certificate verification is "
                "disabled for all Pterodactyl API requests. This makes the API keys sent in "
                "the Authorization header interceptable by anyone able to see this traffic. "
                "Only use this as a stopgap on a trusted network -- fix the panel's "
                "certificate instead when possible."
            )

        self._http = httpx.AsyncClient(
            base_url=settings.pterodactyl_url.rstrip("/"),
            verify=not settings.pterodactyl_skip_ssl_verify,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Accept": ACCEPT_HEADER,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response, identifier: str) -> None:
        if response.is_success:
            return
        detail = response.text
        try:
            errors = response.json().get("errors") or []
            if errors and errors[0].get("detail"):
                detail = errors[0]["detail"]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            pass
        raise PterodactylAPIError(identifier, response.status_code, detail)

    async def list_servers(self) -> list[Server]:
        servers: list[Server] = []
        url: str | None = "/api/application/servers"
        params: dict[str, Any] | None = {"per_page": 50}

        while url is not None:
            response = await self._http.get(
                url, params=params, headers=self._headers(self._app_api_key)
            )
            self._raise_for_status(response, identifier="list_servers")
            payload = response.json()

            for entry in payload["data"]:
                attrs = entry["attributes"]
                servers.append(
                    Server(
                        id=attrs["id"],
                        identifier=attrs["identifier"],
                        name=attrs["name"],
                        node=attrs["node"],
                    )
                )

            url = payload.get("meta", {}).get("pagination", {}).get("links", {}).get("next")
            params = None

        return servers

    async def get_power_state(self, identifier: str) -> PowerState:
        response = await self._http.get(
            f"/api/client/servers/{identifier}/resources",
            headers=self._headers(self._client_api_key),
        )
        self._raise_for_status(response, identifier)
        return response.json()["attributes"]["current_state"]

    async def get_resource_usage(self, identifier: str) -> ResourceUsage:
        resources_response = await self._http.get(
            f"/api/client/servers/{identifier}/resources",
            headers=self._headers(self._client_api_key),
        )
        self._raise_for_status(resources_response, identifier)
        attrs = resources_response.json()["attributes"]
        resources = attrs["resources"]
        network = resources.get("network") or {}

        # /resources only reports current usage -- memory/disk limits live on the
        # server-details endpoint (attributes.limits, in MiB; 0 means unlimited).
        details_response = await self._http.get(
            f"/api/client/servers/{identifier}",
            headers=self._headers(self._client_api_key),
        )
        self._raise_for_status(details_response, identifier)
        limits = details_response.json()["attributes"]["limits"]

        return ResourceUsage(
            current_state=attrs["current_state"],
            is_suspended=attrs["is_suspended"],
            memory_bytes=resources["memory_bytes"],
            memory_limit_bytes=limits["memory"] * 1024 * 1024,
            cpu_absolute=resources["cpu_absolute"],
            disk_bytes=resources["disk_bytes"],
            disk_limit_bytes=limits["disk"] * 1024 * 1024,
            network_rx_bytes=network.get("rx_bytes", 0),
            network_tx_bytes=network.get("tx_bytes", 0),
            uptime=resources["uptime"],
        )

    async def send_power_action(self, identifier: str, action: PowerAction) -> None:
        response = await self._http.post(
            f"/api/client/servers/{identifier}/power",
            json={"signal": action},
            headers=self._headers(self._client_api_key),
        )
        self._raise_for_status(response, identifier)
