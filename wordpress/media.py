import asyncio
import base64
import re

import httpx

from config import Config


def _auth_header(config: Config) -> str:
    """WordPress Basic Auth 헤더 값을 반환."""
    token = base64.b64encode(
        f"{config.wp_username}:{config.wp_app_password}".encode()
    ).decode()
    return f"Basic {token}"


async def _search_pexels(query: str, config: Config, client: httpx.AsyncClient) -> list[str]:
    """Pexels에서 검색해 이미지 URL 후보 리스트 반환 (최대 5개). 못 찾으면 [] ."""
    try:
        resp = await client.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": config.pexels_api_key},
            params={"query": query, "per_page": 5, "orientation": "landscape"},
        )
        resp.raise_for_status()
        return [p["src"]["large2x"] for p in resp.json().get("photos", [])]
    except Exception as e:
        print(f"[WARN] Pexels 검색 실패 ({query}): {e}")
        return []


async def _search_unsplash(query: str, config: Config, client: httpx.AsyncClient) -> list[str]:
    """Unsplash에서 검색해 이미지 URL 후보 리스트 반환. 키 없으면 []."""
    if not config.unsplash_access_key:
        return []
    try:
        resp = await client.get(
            "https://api.unsplash.com/search/photos",
            headers={"Authorization": f"Client-ID {config.unsplash_access_key}"},
            params={"query": query, "per_page": 5, "orientation": "landscape"},
        )
        resp.raise_for_status()
        return [r["urls"]["regular"] for r in resp.json().get("results", [])]
    except Exception as e:
        print(f"[WARN] Unsplash 검색 실패 ({query}): {e}")
        return []


async def find_image_bytes(
    queries: list[str],
    config: Config,
    seen_urls: set[str],
) -> tuple[bytes, str, str] | None:
    """검색어 폴백 체인을 시도해 아직 안 쓴 이미지 받기.

    각 검색어마다 Pexels → Unsplash 후보를 펼쳐서, seen_urls에 없는 첫 이미지 사용.
    반환: (image_bytes, filename, original_url). 못 찾으면 None.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        for query in queries:
            if not query:
                continue
            candidates: list[str] = []
            candidates.extend(await _search_pexels(query, config, client))
            candidates.extend(await _search_unsplash(query, config, client))

            for url in candidates:
                if url in seen_urls:
                    continue
                try:
                    img_resp = await client.get(url, timeout=30)
                    img_resp.raise_for_status()
                    filename = f"img_{abs(hash(url)) % 1000000}.jpg"
                    seen_urls.add(url)
                    print(f"[INFO] 이미지 매칭: '{query}'")
                    return img_resp.content, filename, url
                except Exception as e:
                    print(f"[WARN] 이미지 다운로드 실패 ({url[:60]}...): {e}")
    return None


async def upload_image_to_wp(image_bytes: bytes, filename: str, config: Config) -> tuple[int, str] | None:
    """이미지를 WordPress 미디어 라이브러리에 업로드. (media_id, source_url) 반환."""
    url = f"{config.wp_url}/wp-json/wp/v2/media"
    headers = {
        "Authorization": _auth_header(config),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "image/jpeg",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, content=image_bytes)
            resp.raise_for_status()
            data = resp.json()
            return data["id"], data["source_url"]
    except Exception as e:
        print(f"[ERROR] WordPress 미디어 업로드 실패: {e}")
        return None


async def upload_featured_image(
    queries: list[str],
    config: Config,
    seen_urls: set[str],
) -> int | None:
    """대표 이미지: 검색 → 다운로드 → WP 업로드 → media_id 반환."""
    result = await find_image_bytes(queries, config, seen_urls)
    if not result:
        print(f"[WARN] 대표 이미지 검색 실패: {queries}")
        return None
    image_bytes, filename, _ = result
    uploaded = await upload_image_to_wp(image_bytes, filename, config)
    if not uploaded:
        return None
    media_id, _ = uploaded
    print(f"[INFO] 대표 이미지 업로드 완료 (media ID: {media_id})")
    return media_id


_PLACEHOLDER_RE = re.compile(r"__IMG_(\d+)__")


async def replace_body_images(
    html: str,
    image_queries: list[list[str]],
    config: Config,
    seen_urls: set[str],
) -> str:
    """본문 HTML의 __IMG_N__ 플레이스홀더를 실제 업로드 URL로 치환. seen_urls와 공유해 중복 회피."""
    placeholders = sorted({int(m) for m in _PLACEHOLDER_RE.findall(html)})
    if not placeholders:
        return html

    url_map: dict[int, str] = {}
    for idx in placeholders:
        if idx >= len(image_queries):
            continue
        queries = image_queries[idx]
        result = await find_image_bytes(queries, config, seen_urls)
        if not result:
            print(f"[WARN] 본문 이미지 #{idx} 검색 실패: {queries}")
            continue
        image_bytes, filename, _ = result
        uploaded = await upload_image_to_wp(image_bytes, filename, config)
        if not uploaded:
            continue
        _, source_url = uploaded
        url_map[idx] = source_url
        await asyncio.sleep(0.5)

    def _sub(match: re.Match) -> str:
        idx = int(match.group(1))
        return url_map.get(idx, "")

    return _PLACEHOLDER_RE.sub(_sub, html)
