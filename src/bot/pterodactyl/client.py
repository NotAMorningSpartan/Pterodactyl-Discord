from __future__ import annotations

from typing import Any, Self

import httpx

from bot.config import Settings
from bot.pterodactyl.models import PowerAction, PowerState, Server

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
        self._http = httpx.AsyncClient(base_url=settings.pterodactyl_url.rstrip("/"))

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

    async def send_power_action(self, identifier: str, action: PowerAction) -> None:
        response = await self._http.post(
            f"/api/client/servers/{identifier}/power",
            json={"signal": action},
            headers=self._headers(self._client_api_key),
        )
        self._raise_for_status(response, identifier)
