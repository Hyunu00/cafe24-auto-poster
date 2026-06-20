import base64
import httpx
from config import Config


def _auth_header(config: Config) -> str:
    """WordPress Basic Auth 헤더 값을 반환."""
    token = base64.b64encode(
        f"{config.wp_username}:{config.wp_app_password}".encode()
    ).decode()
    return f"Basic {token}"


async def fetch_categories(config: Config) -> list[dict]:
    """WordPress 카테고리 목록을 id, name 형태로 반환 (미분류 제외)."""
    url = f"{config.wp_url}/wp-json/wp/v2/categories"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            url,
            headers={"Authorization": _auth_header(config)},
            params={"per_page": 100, "hide_empty": False},
        )
        resp.raise_for_status()
    return [c for c in resp.json() if c.get("slug") != "uncategorized"]
