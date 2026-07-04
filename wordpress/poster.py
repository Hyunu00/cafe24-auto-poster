import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from config import Config
from wordpress.media import upload_featured_image, replace_body_images

LOG_PATH = Path("logs/post_log.json")


def _auth_header(config: Config) -> str:
    """WordPress Basic Auth 헤더 값을 반환."""
    token = base64.b64encode(
        f"{config.wp_username}:{config.wp_app_password}".encode()
    ).decode()
    return f"Basic {token}"


def _load_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def _save_log(logs: list[dict]) -> None:
    LOG_PATH.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


async def post_to_wordpress(topic: str, post: dict, config: Config, category_id: int | None = None) -> bool:
    """본문 이미지 치환 + 대표 이미지 업로드 후 WordPress에 글을 등록.

    본문 → 대표 순으로 처리하며 seen_urls를 공유해 같은 글에 동일 이미지 X.
    """
    url = f"{config.wp_url}/wp-json/wp/v2/posts"
    headers = {
        "Authorization": _auth_header(config),
        "Content-Type": "application/json",
    }

    # 한 글 내에서 중복 회피용 — 본문/대표 이미지가 공유
    seen_urls: set[str] = set()

    # 1. 본문 이미지 먼저 (검색어가 더 구체적이라 좋은 매치를 우선 가져감)
    content_with_images = await replace_body_images(
        post["content"],
        post.get("image_queries", []),
        config,
        seen_urls,
    )

    # 2. 대표 이미지 (본문에서 안 쓴 이미지 중에서)
    hero_queries = post.get("hero_image_query") or [topic]
    media_id = await upload_featured_image(hero_queries, config, seen_urls)

    payload = {
        "title": post["title"],
        "content": content_with_images,
        "excerpt": post.get("excerpt", ""),
        "status": config.post_status,
        "categories": [category_id if category_id is not None else config.post_category_id],
    }
    if media_id:
        payload["featured_media"] = media_id

    await asyncio.sleep(2)

    log_entry: dict = {
        "topic": topic,
        "category_id": category_id,
        "title": post["title"],
        "format": post.get("format"),
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "post_id": None,
        "featured_media_id": media_id,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            log_entry["success"] = True
            log_entry["post_id"] = data.get("id")
            print(f"[OK] 포스팅 완료: {post['title']} (ID: {data.get('id')})")
            return True
    except Exception as e:
        log_entry["error"] = str(e)
        print(f"[ERROR] 포스팅 실패: {e}")
        return False
    finally:
        logs = _load_log()
        logs.append(log_entry)
        _save_log(logs)
