from conftest import H, drain, jpeg

from wardrobe import vision


def fake_analyze(owner_id, sha, hint=""):
    from wardrobe import db
    p = db.one("SELECT filename FROM photos WHERE sha256=?", (sha,))
    name = (p or {}).get("filename") or ""
    if name.startswith("flat"):
        return {"kind": "flat_lay", "people": 0, "summary": "two items on a bed", "items": [
            {"bbox": [0.05, 0.05, 0.45, 0.6], "category": "top", "subcategory": "t-shirt", "name": "White tee",
             "colors": ["white"], "seasons": ["summer"], "occasions": ["casual"], "confidence": 0.9},
            {"bbox": [0.5, 0.1, 0.95, 0.9], "category": "bottom", "subcategory": "jeans", "name": "Blue jeans",
             "colors": ["blue"], "seasons": ["all-season"], "occasions": ["casual"], "confidence": 0.85}]}
    if name.startswith("tag"):
        return {"kind": "tag", "items": [], "tag": {"brand": "Levi's", "size": "32", "mrp": "3,999", "currency": "INR",
                                                    "materials": "98% cotton 2% elastane"}}
    return {"kind": "worn", "people": 1, "items": [
        {"bbox": [0.3, 0.3, 0.7, 0.95], "category": "bottom", "subcategory": "jeans", "name": "Blue jeans",
         "colors": ["blue"], "confidence": 0.8}]}


def fake_group(owner_id, crops, existing):
    by_name = {}
    for cid, _sha, label in crops:
        by_name.setdefault(label.split(" (")[0], []).append(cid)
    return [{"crops": c, "existing": None, "confidence": 0.95, "reason": "same"} for c in by_name.values()]


def fake_assign(owner_id, items, tags, receipts):
    jeans = next(ref for ref, _sha, desc in items if "jeans" in desc.lower())
    return {"tags": [{"tag": "T1", "item": jeans}], "lines": []}


def test_folder_import(client, monkeypatch):
    monkeypatch.setattr(vision, "analyze", fake_analyze)
    monkeypatch.setattr(vision, "group", fake_group)
    monkeypatch.setattr(vision, "assign", fake_assign)
    monkeypatch.setattr(vision, "describe", lambda d: f"{d.get('name')}")
    b = client.post("/api/v1/batches", json={"note": "haul", "hints": {"store": "Mall of India", "price": 2499}},
                    headers=H).json()
    assert b["analyze"] is True
    files = [("files", ("flat1.jpg", jpeg((240, 240, 240)), "image/jpeg")),
             ("files", ("worn1.jpg", jpeg((30, 60, 160)), "image/jpeg")),
             ("files", ("tag1.jpg", jpeg((120, 100, 90)), "image/jpeg"))]
    r = client.post(b["upload_url"].replace("http://testserver", ""), files=files)
    assert r.status_code == 200, r.text
    drain()
    view = client.get(f"/api/v1/batches/{b['id']}").json()
    assert view["batch"]["status"] == "review", view["batch"]
    props = {p["data"]["name"]: p for p in view["proposals"]}
    assert set(props) == {"White tee", "Blue jeans"}
    jeans = props["Blue jeans"]
    assert {l["role"] for l in jeans["links"]} == {"shows", "worn", "tag"}
    assert jeans["data"]["brand"] == "Levi's" and jeans["data"]["original_price"] == 3999
    assert jeans["data"]["store"] == "Mall of India" and jeans["data"]["provenance"]["store"] == "user"
    r = client.post(f"/api/v1/batches/{b['id']}/commit", json={"which": "all"}, headers=H)
    assert r.status_code == 200, r.text
    items = client.get("/api/v1/items", params={"q": "jeans"}).json()["items"]
    assert items and items[0]["original_price"] == 3999 and items[0]["worn_count_photos"] == 1
    me = client.get("/api/v1/photos", params={"person": "me", "kind": "worn"}).json()
    assert me["total"] >= 1
