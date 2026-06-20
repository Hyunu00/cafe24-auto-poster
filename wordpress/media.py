import base64
import httpx
from config import Config


def _auth_header(config: Config) -> str:
    token = base64.b64encode(
        f"{config.wp_username}:{config.wp_app_password}".encode()
    ).decode()
    return f"Basic {token}"


async def fetch_pexels_image(topic: str, config: Config) -> tuple[bytes, str] | None:
    """Pexels에서 주제에 맞는 이미지를 다운로드해 (bytes, 파일명) 반환."""
    headers = {"Authorization": config.pexels_api_key}
    params = {"query": topic, "per_page": 1, "orientation": "landscape"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get("https://api.pexels.com/v1/search", headers=headers, params=params)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            return None

        image_url = photos[0]["src"]["large2x"]
        img_resp = await client.get(image_url)
        img_resp.raise_for_status()

    # 파일명은 ASCII만 허용 — 한글 포함 시 httpx 헤더 오류 발생
    filename = f"featured_{abs(hash(topic)) % 100000}.jpg"
    return img_resp.content, filename


async def upload_featured_image(topic: str, config: Config) -> int | None:
    """이미지를 WordPress 미디어 라이브러리에 업로드하고 media ID 반환."""
    result = await fetch_pexels_image(topic, config)
    if not result:
        print(f"[WARN] Pexels에서 이미지를 찾지 못했습니다: {topic}")
        return None

    image_bytes, filename = result
    url = f"{config.wp_url}/wp-json/wp/v2/media"
    headers = {
        "Authorization": _auth_header(config),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/jpeg",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, content=image_bytes)
        resp.raise_for_status()
        media_id = resp.json().get("id")
        print(f"[INFO] 대표 이미지 업로드 완료 (media ID: {media_id})")
        return media_id
