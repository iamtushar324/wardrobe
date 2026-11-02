from conftest import H, jpeg


def test_item_crud_and_filters(client):
    r = client.post("/api/v1/items", json={"name": "Navy oxford shirt", "category": "top", "colors": ["navy blue"],
                                           "seasons": ["summer"], "occasions": ["office"], "price": 1999,
                                           "store": "Uniqlo"}, headers=H)
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["colors"][0]["name"] == "navy"
    assert item["provenance"]["price"] == "user"
    client.post("/api/v1/items", json={"name": "Wool coat", "category": "outerwear", "colors": ["camel"],
                                       "seasons": ["winter"]}, headers=H)
    summer = client.get("/api/v1/items", params={"season": "summer"}).json()
    assert [i["name"] for i in summer["items"]] == ["Navy oxford shirt"]
    assert {f["value"] for f in summer["facets"]["season"]} >= {"summer", "winter"}
    assert client.get("/api/v1/items", params={"q": "oxf"}).json()["total"] == 1
    assert client.get("/api/v1/items", params={"color": "camel"}).json()["items"][0]["name"] == "Wool coat"
    r = client.patch(f"/api/v1/items/{item['id']}", json={"status": "donated"}, headers=H)
    assert r.json()["status"] == "donated"
    assert client.get("/api/v1/items", params={"q": "oxford"}).json()["total"] == 0
    assert client.get("/api/v1/items", params={"q": "oxford", "status": "all"}).json()["total"] == 1


def test_photos_links_and_media(client):
    item = client.post("/api/v1/items", json={"name": "Red tee", "category": "top"}, headers=H).json()
    r = client.post(f"/api/v1/items/{item['id']}/photos", files=[("files", ("a.jpg", jpeg((200, 30, 30)), "image/jpeg"))],
                    data={"role": "shows"}, headers=H)
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/items/{item['id']}").json()
    assert got["cover"]["md"].startswith("/media/")
    assert client.get(got["cover"]["md"]).status_code == 200
    assert client.get("/media/" + "0" * 64 + "/md").status_code == 404
    # duplicate upload is detected
    r = client.post("/api/v1/photos", files=[("files", ("b.jpg", jpeg((200, 30, 30)), "image/jpeg"))], headers=H)
    assert r.json()["results"][0].get("duplicate")


def test_cookie_writes_need_client_header(client):
    # Dev mode (auth=none) has no cookie, so the header is not needed; a token write never needs it.
    tok = client.post("/api/v1/tokens", json={"label": "pytest"}, headers=H).json()["token"]
    r = client.post("/api/v1/items", json={"name": "Agent sock", "category": "innerwear"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["created_by"].startswith("agent:pytest:")
    ro = client.post("/api/v1/tokens", json={"label": "ro", "read_only": True}, headers=H).json()["token"]
    r = client.post("/api/v1/items", json={"name": "x"}, headers={"Authorization": f"Bearer {ro}"})
    assert r.status_code == 403
    assert client.get("/api/v1/items", headers={"Authorization": "Bearer wd_nope"}).status_code == 401
