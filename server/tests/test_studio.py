import io

from PIL import Image

from conftest import H, W, jpeg

from wardrobe import db


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (512, 640), (250, 250, 250)).save(b, "PNG")
    return b.getvalue()


def test_chatgpt_login_and_generation(client):
    owner = client.get("/api/v1/me").json()["user"]
    # worker comes online
    hb = client.post("/api/worker/heartbeat", json={"state": "idle", "accounts": {}}, headers=W).json()
    assert hb["pending_logins"] == []
    assert client.post("/api/worker/heartbeat", json={}).status_code == 403
    # owner connects ChatGPT from Studio
    start = client.post("/api/v1/chatgpt/connect", headers=H).json()
    rid = start["id"]
    hb = client.post("/api/worker/heartbeat", json={"accounts": {}}, headers=W).json()
    assert [p["id"] for p in hb["pending_logins"]] == [rid]
    client.post(f"/api/worker/login/{rid}/code", json={"url": "https://auth.openai.com/codex/device", "code": "ABCD-1234"},
                headers=W)
    st = client.get(f"/api/v1/chatgpt/connect/{rid}").json()
    assert st["user_code"] == "ABCD-1234" and st["status"] == "code"
    bad = client.post(f"/api/worker/login/{rid}/done", json={"email": "me@work.example"}, headers=W).json()
    assert bad["accept"] is False
    start = client.post("/api/v1/chatgpt/connect", headers=H).json()
    ok = client.post(f"/api/worker/login/{start['id']}/done", json={"email": "me@gmail.example", "plan": "plus"},
                     headers=W).json()
    assert ok == {"accept": True, "user_id": owner["id"]}
    client.post("/api/worker/heartbeat", json={"accounts": {owner["id"]: {"status": "connected", "email": "me@gmail.example",
                                                                         "plan": "plus"}}}, headers=W)
    # queue: a product picture needs no model photo; a 'me' template needs one
    item = client.post("/api/v1/items", json={"name": "Green polo", "category": "top", "colors": ["green"]}, headers=H).json()
    client.post(f"/api/v1/items/{item['id']}/photos", files=[("files", ("p.jpg", jpeg((20, 140, 60)), "image/jpeg"))],
                headers=H)
    r = client.post("/api/v1/studio/jobs", json={"template": "me-lifestyle", "item_ids": [item["id"]]}, headers=H)
    assert r.status_code == 422
    r = client.post("/api/v1/studio/jobs", json={"template": "white-bg-cloth-only", "item_ids": [item["id"]]}, headers=H)
    assert r.status_code == 200, r.text
    st = client.get("/api/v1/studio").json()
    assert st["available"] and st["counts"].get("queued") == 1
    # pause stops claims
    client.patch("/api/v1/studio/prefs", json={"paused": True}, headers=H)
    assert client.post("/api/worker/claim", json={"ready_users": [owner["id"]]}, headers=W).json()["job"] is None
    client.patch("/api/v1/studio/prefs", json={"paused": False}, headers=H)
    job = client.post("/api/worker/claim", json={"ready_users": [owner["id"]]}, headers=W).json()["job"]
    assert job and job["inputs"] and "Reference image" in job["prompt"]
    assert client.get(job["inputs"][0], headers=W).status_code == 200
    r = client.post(f"/api/worker/jobs/{job['id']}/complete", files={"file": ("r.png", png(), "image/png")},
                    data={"meta": '{"duration_s": 42}'}, headers=W)
    assert r.status_code == 200, r.text
    st = client.get("/api/v1/studio").json()
    assert st["usage"]["chatgpt_today"] == 1
    got = client.get(f"/api/v1/items/{item['id']}").json()
    assert any(p["role"] == "generated" for p in got["photos"])
    ai = client.get("/api/v1/photos", params={"source": "ai"}).json()
    assert ai["total"] >= 1
    # cancel a queued job
    j2 = client.post("/api/v1/studio/jobs", json={"template": "flat-lay", "item_ids": [item["id"]]}, headers=H).json()
    jid = j2["jobs"][0]["id"] if "jobs" in j2 else j2[0]["id"]
    client.post("/api/v1/studio/cancel", json={"ids": [jid]}, headers=H)
    assert db.one("SELECT status FROM gen_jobs WHERE id=?", (jid,))["status"] == "cancelled"
