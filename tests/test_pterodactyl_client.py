import json

import httpx
import pytest
import respx

from bot.pterodactyl.client import PterodactylAPIError, PterodactylClient
from bot.pterodactyl.models import Server
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
