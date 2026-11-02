import io
import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="wardrobe-test-")
os.environ.update({
    "WARDROBE_DATA_DIR": _tmp,
    "WARDROBE_CREDENTIALS_DIR": os.path.join(_tmp, "creds"),
    "WARDROBE_AUTH": "none,chatgpt",
    "WARDROBE_OWNER_EMAIL": "owner@example.com",
    "WARDROBE_CUTOUTS": "off",
    "WARDROBE_WORKER_TOKEN": "test-worker-token",
    "WARDROBE_OPENROUTER_API_KEY": "test-key",
    "WARDROBE_BLOCKED_CHATGPT_DOMAINS": "work.example",
    "WARDROBE_PUBLIC_URL": "http://testserver",
})

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from wardrobe import db, jobs  # noqa: E402
from wardrobe.main import app  # noqa: E402

H = {"x-wardrobe-client": "web"}
W = {"Authorization": "Bearer test-worker-token"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def jpeg(color=(20, 40, 120), size=(600, 800)) -> bytes:
    b = io.BytesIO()
    img = Image.new("RGB", size, (235, 235, 235))
    img.paste(Image.new("RGB", (size[0] // 2, size[1] // 2), color), (size[0] // 4, size[1] // 4))
    img.save(b, "JPEG")
    return b.getvalue()


def drain():
    while jobs.run_one():
        pass
