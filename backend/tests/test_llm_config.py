"""LLM 配置接口的 api_key 掩码（P0）：出参不含明文、编辑不覆盖已存密钥。"""

from sqlalchemy import select

from app.models import LLMConfig, UserRole
from tests.conftest import auth_token, create_user

SECRET = "sk-super-secret-1234"
MASKED = "sk-****1234"


def _payload(**overrides) -> dict:
    data = {
        "name": "cfg1",
        "provider_key": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": SECRET,
        "model": "deepseek-chat",
    }
    data.update(overrides)
    return data


async def _admin_headers(client, db, username="admin_llm"):
    await create_user(db, UserRole.SCHOOL_ADMIN, username, real_name="管理员")
    token = await auth_token(client, username)
    return {"Authorization": f"Bearer {token}"}


async def test_api_key_is_masked_in_all_outputs(client, db):
    headers = await _admin_headers(client, db)

    created = await client.post("/api/admin/llm-configs", json=_payload(), headers=headers)
    assert created.status_code == 200, created.text
    assert created.json()["api_key"] == MASKED
    assert SECRET not in created.text

    listed = await client.get("/api/admin/llm-configs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["api_key"] == MASKED
    assert SECRET not in listed.text


async def test_update_keeps_secret_when_masked_or_blank(client, db):
    headers = await _admin_headers(client, db, "admin_llm2")
    await client.post("/api/admin/llm-configs", json=_payload(), headers=headers)
    cfg = (await db.execute(select(LLMConfig))).scalars().first()

    # 前端把掩码原样回传：后端必须保留真实密钥，而不是存回掩码字符串。
    masked = await client.put(
        f"/api/admin/llm-configs/{cfg.id}",
        json=_payload(name="renamed", api_key=MASKED),
        headers=headers,
    )
    assert masked.status_code == 200, masked.text
    await db.refresh(cfg)
    assert cfg.api_key == SECRET
    assert cfg.name == "renamed"

    # 留空同样表示“不修改”。
    blank = await client.put(
        f"/api/admin/llm-configs/{cfg.id}",
        json=_payload(api_key=""),
        headers=headers,
    )
    assert blank.status_code == 200, blank.text
    await db.refresh(cfg)
    assert cfg.api_key == SECRET


async def test_update_with_real_key_replaces_secret(client, db):
    headers = await _admin_headers(client, db, "admin_llm3")
    await client.post("/api/admin/llm-configs", json=_payload(), headers=headers)
    cfg = (await db.execute(select(LLMConfig))).scalars().first()

    new_key = "sk-brand-new-key-9999"
    resp = await client.put(
        f"/api/admin/llm-configs/{cfg.id}",
        json=_payload(api_key=new_key),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(cfg)
    assert cfg.api_key == new_key
    assert resp.json()["api_key"] == "sk-****9999"
