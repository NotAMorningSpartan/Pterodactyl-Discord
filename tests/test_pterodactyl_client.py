import json
from unittest.mock import patch

import httpx
import pytest
import respx

from bot.config import Settings
from bot.pterodactyl.client import PterodactylAPIError, PterodactylClient
from bot.pterodactyl.models import ResourceUsage, Server
from tests.conftest import APP_API_KEY, CLIENT_API_KEY, PANEL_URL


@respx.mock
async def test_list_servers_paginates_and_parses_all_pages(client: PterodactylClient):
    page1 = {
        "data": [
            {"attributes": {"id": 1, "identifier": "abc111", "name": "Server One", "node": 1}},
        ],
        "meta": {
            "pagination": {
                "links": {"next": f"{PANEL_URL}/api/application/servers?page=2"},
            }
        },
    }
    page2 = {
        "data": [
            {"attributes": {"id": 2, "identifier": "def222", "name": "Server Two", "node": 2}},
        ],
        "meta": {"pagination": {"links": {}}},
    }
    route = respx.get(f"{PANEL_URL}/api/application/servers").mock(
        side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
    )

    servers = await client.list_servers()

    assert servers == [
        Server(id=1, identifier="abc111", name="Server One", node=1),
        Server(id=2, identifier="def222", name="Server Two", node=2),
    ]
    assert route.call_count == 2

    first_request = route.calls[0].request
    assert first_request.headers["Authorization"] == f"Bearer {APP_API_KEY}"
    assert first_request.headers["Accept"] == "Application/vnd.pterodactyl.v1+json"
    assert first_request.url.params["per_page"] == "50"


@respx.mock
async def test_get_power_state_returns_current_state(client: PterodactylClient):
    route = respx.get(f"{PANEL_URL}/api/client/servers/abc111/resources").mock(
        return_value=httpx.Response(200, json={"attributes": {"current_state": "running"}})
    )

    state = await client.get_power_state("abc111")

    assert state == "running"
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {CLIENT_API_KEY}"


@respx.mock
async def test_send_power_action_posts_signal(client: PterodactylClient):
    route = respx.post(f"{PANEL_URL}/api/client/servers/abc111/power").mock(
        return_value=httpx.Response(204)
    )

    await client.send_power_action("abc111", "restart")

    request = route.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {CLIENT_API_KEY}"
    assert json.loads(request.content) == {"signal": "restart"}


@respx.mock
async def test_send_power_action_raises_on_403(client: PterodactylClient):
    respx.post(f"{PANEL_URL}/api/client/servers/abc111/power").mock(
        return_value=httpx.Response(
            403, json={"errors": [{"code": "NoPermissionError", "detail": "Forbidden."}]}
        )
    )

    with pytest.raises(PterodactylAPIError) as exc_info:
        await client.send_power_action("abc111", "start")

    error = exc_info.value
    assert error.identifier == "abc111"
    assert error.status_code == 403
    assert "abc111" in str(error)
    assert "403" in str(error)


@respx.mock
async def test_get_power_state_raises_on_404(client: PterodactylClient):
    respx.get(f"{PANEL_URL}/api/client/servers/missing/resources").mock(
        return_value=httpx.Response(
            404, json={"errors": [{"code": "NotFoundHttpException", "detail": "Not found."}]}
        )
    )

    with pytest.raises(PterodactylAPIError) as exc_info:
        await client.get_power_state("missing")

    error = exc_info.value
    assert error.identifier == "missing"
    assert error.status_code == 404
    assert "missing" in str(error)
    assert "404" in str(error)


def _mock_server_details(identifier: str, *, disk_limit_mb: int) -> None:
    respx.get(f"{PANEL_URL}/api/client/servers/{identifier}").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "server",
                "attributes": {
                    "identifier": identifier,
                    "limits": {
                        "memory": 1024,
                        "swap": 0,
                        "disk": disk_limit_mb,
                        "io": 500,
                        "cpu": 100,
                    },
                },
            },
        )
    )


@respx.mock
async def test_get_resource_usage_running(client: PterodactylClient):
    respx.get(f"{PANEL_URL}/api/client/servers/abc111/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "stats",
                "attributes": {
                    "current_state": "running",
                    "is_suspended": False,
                    "resources": {
                        "memory_bytes": 536870912,
                        "memory_limit_bytes": 1073741824,
                        "cpu_absolute": 12.5,
                        "disk_bytes": 2147483648,
                        "network": {"rx_bytes": 1000, "tx_bytes": 2000},
                        "uptime": 3661000,
                    },
                },
            },
        )
    )
    _mock_server_details("abc111", disk_limit_mb=5120)

    usage = await client.get_resource_usage("abc111")

    assert usage == ResourceUsage(
        current_state="running",
        is_suspended=False,
        memory_bytes=536870912,
        memory_limit_bytes=1073741824,
        cpu_absolute=12.5,
        disk_bytes=2147483648,
        disk_limit_bytes=5120 * 1024 * 1024,
        network_rx_bytes=1000,
        network_tx_bytes=2000,
        uptime=3661000,
    )


@respx.mock
async def test_get_resource_usage_offline_is_zeroed(client: PterodactylClient):
    respx.get(f"{PANEL_URL}/api/client/servers/abc111/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "stats",
                "attributes": {
                    "current_state": "offline",
                    "is_suspended": False,
                    "resources": {
                        "memory_bytes": 0,
                        "memory_limit_bytes": 1073741824,
                        "cpu_absolute": 0,
                        "disk_bytes": 0,
                        "network": {"rx_bytes": 0, "tx_bytes": 0},
                        "uptime": 0,
                    },
                },
            },
        )
    )
    _mock_server_details("abc111", disk_limit_mb=5120)

    usage = await client.get_resource_usage("abc111")

    assert usage.current_state == "offline"
    assert usage.memory_bytes == 0
    assert usage.cpu_absolute == 0
    assert usage.disk_bytes == 0
    assert usage.network_rx_bytes == 0
    assert usage.network_tx_bytes == 0
    assert usage.uptime == 0


@respx.mock
async def test_get_resource_usage_unlimited_disk_is_zero(client: PterodactylClient):
    respx.get(f"{PANEL_URL}/api/client/servers/abc111/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "stats",
                "attributes": {
                    "current_state": "running",
                    "is_suspended": False,
                    "resources": {
                        "memory_bytes": 536870912,
                        "memory_limit_bytes": 1073741824,
                        "cpu_absolute": 12.5,
                        "disk_bytes": 2147483648,
                        "network": {"rx_bytes": 1000, "tx_bytes": 2000},
                        "uptime": 3661000,
                    },
                },
            },
        )
    )
    _mock_server_details("abc111", disk_limit_mb=0)

    usage = await client.get_resource_usage("abc111")

    assert usage.disk_limit_bytes == 0


@respx.mock
async def test_get_resource_usage_raises_on_404(client: PterodactylClient):
    respx.get(f"{PANEL_URL}/api/client/servers/missing/resources").mock(
        return_value=httpx.Response(
            404, json={"errors": [{"code": "NotFoundHttpException", "detail": "Not found."}]}
        )
    )

    with pytest.raises(PterodactylAPIError) as exc_info:
        await client.get_resource_usage("missing")

    assert exc_info.value.identifier == "missing"


@respx.mock
async def test_get_resource_usage_raises_on_404_from_details_call(client: PterodactylClient):
    respx.get(f"{PANEL_URL}/api/client/servers/abc111/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "stats",
                "attributes": {
                    "current_state": "running",
                    "is_suspended": False,
                    "resources": {
                        "memory_bytes": 0,
                        "memory_limit_bytes": 0,
                        "cpu_absolute": 0,
                        "disk_bytes": 0,
                        "network": {"rx_bytes": 0, "tx_bytes": 0},
                        "uptime": 0,
                    },
                },
            },
        )
    )
    respx.get(f"{PANEL_URL}/api/client/servers/abc111").mock(
        return_value=httpx.Response(
            404, json={"errors": [{"code": "NotFoundHttpException", "detail": "Not found."}]}
        )
    )

    with pytest.raises(PterodactylAPIError) as exc_info:
        await client.get_resource_usage("abc111")

    assert exc_info.value.status_code == 404
    assert exc_info.value.status_code == 404


def test_verifies_ssl_by_default(settings: Settings):
    with patch("bot.pterodactyl.client.httpx.AsyncClient") as mock_async_client:
        PterodactylClient(settings)

    assert mock_async_client.call_args.kwargs["verify"] is True


def test_skip_ssl_verify_disables_verification_and_warns(settings: Settings, caplog):
    settings.pterodactyl_skip_ssl_verify = True

    with caplog.at_level("WARNING", logger="bot"):
        with patch("bot.pterodactyl.client.httpx.AsyncClient") as mock_async_client:
            PterodactylClient(settings)

    assert mock_async_client.call_args.kwargs["verify"] is False
    messages = [record.getMessage() for record in caplog.records]
    assert any("PTERODACTYL_SKIP_SSL_VERIFY" in msg for msg in messages)
