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


def _connect(client, owner_id):
    client.post("/api/worker/heartbeat", json={"accounts": {owner_id: {"status": "connected", "email": "me@gmail.example",
                                                                      "plan": "plus"}}}, headers=W)
    if not db.one("SELECT 1 FROM chatgpt_accounts WHERE user_id=? AND status='connected'", (owner_id,)):
        start = client.post("/api/v1/chatgpt/connect", headers=H).json()
        client.post(f"/api/worker/login/{start['id']}/done", json={"email": "me@gmail.example", "plan": "plus"}, headers=W)
    client.patch("/api/v1/studio/prefs", json={"paused": False, "min_interval_s": 0}, headers=H)


def test_try_on_edits_my_photo(client):
    from conftest import drain

    owner = client.get("/api/v1/me").json()["user"]
    _connect(client, owner["id"])
    client.post("/api/v1/studio/cancel", json={"all_queued": True}, headers=H)
    shirt = client.post("/api/v1/items", json={"name": "Navy oxford shirt", "category": "top", "subcategory": "shirt",
                                               "colors": ["navy"]}, headers=H).json()
    client.post(f"/api/v1/items/{shirt['id']}/photos", files=[("files", ("s.jpg", jpeg((20, 30, 90)), "image/jpeg"))],
                headers=H)
    me_photo = client.post("/api/v1/photos", files=[("files", ("me.jpg", jpeg((200, 150, 120), (600, 900)), "image/jpeg"))],
                           data={"kind": "worn"}, headers=H).json()["results"][0]["photo_id"]
    # the template list keeps try-on out of the normal templates
    assert client.post("/api/v1/studio/jobs", json={"template": "tryon", "item_ids": [shirt["id"]]}, headers=H).status_code == 422
    r = client.post("/api/v1/studio/tryon", json={"photo_id": me_photo, "item_ids": [shirt["id"]], "options": {
        "background": "studio", "crop": "card", "cover": True, "variants": 2, "extra": "remove the bag on the bed"}},
        headers=H)
    assert r.status_code == 200, r.text
    jobs = r.json()["jobs"]
    assert len(jobs) == 2 and all(j["template"] == "tryon" for j in jobs)
    assert jobs[0]["base"]["sha"] and jobs[0]["options"]["crop"] == "card"
    prompt = jobs[0]["prompt"]
    assert "Edit image 1" in prompt and "image 2: navy" in prompt.lower() and "remove the bag" in prompt
    assert "#FFFFFF" in prompt and "vertical" in prompt
    job = client.post("/api/worker/claim", json={"ready_users": [owner["id"]]}, headers=W).json()["job"]
    assert job["template"] == "tryon" and len(job["inputs"]) == 2 and job["aspect"] == "portrait"
    base_sha = db.one("SELECT sha256 FROM photos WHERE id=?", (me_photo,))["sha256"]
    assert job["inputs"][0].endswith(base_sha)
    r = client.post(f"/api/worker/jobs/{job['id']}/complete", files={"file": ("r.png", png(), "image/png")},
                    data={"meta": '{"duration_s": 30}'}, headers=W)
    assert r.status_code == 200 and r.json()["finishing"] is True
    assert db.one("SELECT status FROM gen_jobs WHERE id=?", (job["id"],))["status"] == "running"
    drain()  # framing happens in the background worker
    done = db.one("SELECT * FROM gen_jobs WHERE id=?", (job["id"],))
    assert done["status"] == "done" and done["result_photo_id"]
    res = db.one("SELECT * FROM photos WHERE id=?", (done["result_photo_id"],))
    assert res["kind"] == "worn" and res["ai"] and abs(res["width"] / res["height"] - 0.75) < 0.01
    item = client.get(f"/api/v1/items/{shirt['id']}").json()
    cover = next(p for p in item["photos"] if p["photo"]["id"] == done["result_photo_id"])
    assert item["cover_link_id"] == cover["link_id"]
    mine = client.get("/api/v1/photos", params={"person": "me", "kind": "worn"}).json()
    assert done["result_photo_id"] in [p["id"] for p in mine["photos"]]
    assert client.post("/api/v1/studio/tryon", json={"photo_id": me_photo, "item_ids": []}, headers=H).status_code == 422
    client.post("/api/v1/studio/cancel", json={"all_queued": True}, headers=H)


def test_framing():
    from wardrobe.finish import frame_box

    # a person in the middle of a tall picture: a 3:4 card around them, inside the picture
    x0, y0, x1, y1 = frame_box((1024, 1536), (380, 200, 640, 1400), 3 / 4)
    assert x0 >= 0 and y0 >= 0 and x1 <= 1024 and y1 <= 1536
    assert abs((x1 - x0) / (y1 - y0) - 0.75) < 0.01 and x0 < 380 and x1 > 640
    # nothing found: centred crop to the shape
    assert frame_box((1000, 1000), None, 3 / 4) == (125, 0, 875, 1000)
    # a tall narrow photo with the person head to toe: the card pads the sides instead of cutting the head off
    x0, y0, x1, y1 = frame_box((1472, 3200), (300, 120, 1180, 3150), 3 / 4)
    assert y0 <= 120 - 10 and y1 >= 3150 and x0 < 0 and x1 > 1472
    assert abs((x1 - x0) / (y1 - y0) - 0.75) < 0.01
    # a person at the side of a wide photo: the box slides inside the picture rather than padding
    x0, y0, x1, y1 = frame_box((2000, 1000), (100, 100, 500, 900), 3 / 4)
    assert x0 == 0 and 0 <= y0 and y1 <= 1000 and x1 > 500
    # legs already out of shot: no margin below the photo's edge, so no padding just for that
    x0, y0, x1, y1 = frame_box((2400, 3200), (700, 1000, 1700, 3200), 1.0)
    assert y1 == 3200 and x0 >= 0 and x1 <= 2400
    # tight: the margins stop at the picture's edge
    assert frame_box((600, 800), (0, 0, 600, 700), 0.0, allow_pad=False) == (0, 0, 600, 724)


def test_padding_keeps_the_photo_look():
    from PIL import Image

    from wardrobe.finish import _crop

    img = Image.new("RGB", (100, 300), (200, 30, 30))
    out = _crop(img, (-50, 0, 150, 300), "blur")
    assert out.size == (200, 300) and out.mode == "RGB"
    r, g, b = out.getpixel((5, 150))
    assert r > g and r > b  # the padding takes the photo's colour, not black or grey bars
    clear = _crop(img.convert("RGBA"), (-50, 0, 150, 300), "clear")
    assert clear.getpixel((5, 150))[3] == 0 and clear.getpixel((100, 150))[3] == 255
