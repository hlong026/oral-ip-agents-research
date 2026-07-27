"""带签名与 Range 支持的媒体下载 API。"""

import mimetypes
import re

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

from app.core import storage

router = APIRouter()
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


@router.head("/media/{key:path}", include_in_schema=False)
@router.get("/media/{key:path}", name="media")
async def media_file(key: str, request: Request) -> Response:
    """以短期签名 URL 提供本地或 S3 媒体，并支持视频 Range 请求。"""
    if not storage.verify_media_signature(
        key,
        request.query_params.get("exp"),
        request.query_params.get("sig"),
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "媒体访问链接无效或已过期")
    try:
        total = await storage.size(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在") from exc

    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    headers = {"accept-ranges": "bytes"}
    start, end, response_status = 0, total - 1, status.HTTP_200_OK
    range_header = request.headers.get("range")
    match = _RANGE_RE.match(range_header.strip()) if range_header else None
    if match:
        spec_start, spec_end = match.group(1), match.group(2)
        if spec_start:
            start = int(spec_start)
            end = min(int(spec_end), total - 1) if spec_end else total - 1
        elif spec_end:
            start = max(total - int(spec_end), 0)
            end = total - 1
        if (not spec_start and not spec_end) or start > end or start >= total:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"content-range": f"bytes */{total}"},
            )
        response_status = status.HTTP_206_PARTIAL_CONTENT
        headers["content-range"] = f"bytes {start}-{end}/{total}"

    headers["content-length"] = str(max(end - start + 1, 0))
    if request.method == "HEAD" or total == 0:
        return Response(status_code=response_status, headers=headers, media_type=content_type)
    return StreamingResponse(
        storage.stream_range(key, start, end),
        status_code=response_status,
        headers=headers,
        media_type=content_type,
    )
