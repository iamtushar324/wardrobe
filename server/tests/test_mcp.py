from conftest import H


def rpc(client, tok, method, params=None, ident=1):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}},
                       headers={"Authorization": f"Bearer {tok}"}).json()


def test_mcp_flow(client):
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                       headers={"Authorization": "Bearer wd_bad"}).status_code == 401
    tok = client.post("/api/v1/tokens", json={"label": "mcp-test"}, headers=H).json()["token"]
    init = rpc(client, tok, "initialize", {"protocolVersion": "2025-06-18"})
    assert init["result"]["serverInfo"]["name"] == "wardrobe"
    names = {t["name"] for t in rpc(client, tok, "tools/list")["result"]["tools"]}
    assert {"wardrobe_search", "wardrobe_create_import", "wardrobe_generate"} <= names
    r = rpc(client, tok, "tools/call", {"name": "wardrobe_add_item", "arguments": {
        "name": "Black kurta", "category": "ethnic", "colors": ["black"], "occasions": ["festive"]}})
    assert not r["result"]["isError"], r
    item_id = r["result"]["structuredContent"]["id"]
    r = rpc(client, tok, "tools/call", {"name": "wardrobe_search", "arguments": {"occasion": "festive"}})
    assert r["result"]["structuredContent"]["items"][0]["id"] == item_id
    r = rpc(client, tok, "tools/call", {"name": "wardrobe_create_import", "arguments": {"note": "agent"}})
    assert r["result"]["structuredContent"]["upload_url"].startswith("http://testserver/api/v1/upload/up_")
    r = rpc(client, tok, "tools/call", {"name": "wardrobe_delete_item", "arguments": {"item_id": item_id, "confirm": False}})
    assert r["result"]["isError"]
    r = rpc(client, tok, "tools/call", {"name": "wardrobe_add_photo_urls",
                                        "arguments": {"batch_id": "x", "urls": ["http://127.0.0.1/a.jpg"]}})
    assert r["result"]["isError"] or r["result"]["structuredContent"]["errors"]


def test_oauth_discovery_is_not_the_web_app(client):
    # MCP clients probe these after a 401; an HTML page here breaks their JSON parsing.
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
