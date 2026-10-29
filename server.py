"""Glovy (Apero 系) — 本地 2API 网关 + Demo

端口 8956

能力:
  * OpenAI 兼容:  POST /v1/images/generations   (文生图 / 风格化文生图)
                  POST /v1/images/edits         (图生图 / 风格化, multipart)
                  GET  /v1/models
  * 平台原生:     POST /api/v1/generate          (图生图, multipart, 支持风格路由)
                  POST /api/v1/text2image        (JSON)
                  POST /api/v1/video             (图生视频, 轮询)
  * 辅助:         GET  /            demo 页
                  GET  /styles      风格目录(3826 条, 支持按 project/关键字过滤)
                  GET  /health  /stats  /media  /debug/signature

环境变量:
  APERO_MOCK=1        全部请求走 mock（离线压测 / 无网环境）
  APERO_PROXY=http://127.0.0.1:10808   上游代理（国内网络必需）
  APERO_API_KEY=sk-xxx 覆盖上游 key
  PORT=8956

运行: python server.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import requests
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from apero_client import OPERATIONS, AperoClient, AperoError

ROOT = Path(__file__).parent
MOCK = os.environ.get("APERO_MOCK", "0") == "1"

# ---------------------------------------------------------------- 风格目录
STYLES: List[Dict[str, Any]] = []
if (ROOT / "styles_v3.json").exists():
    STYLES = json.loads((ROOT / "styles_v3.json").read_text(encoding="utf-8"))
STYLE_BY_ID = {s["_id"]: s for s in STYLES}

app = FastAPI(title="Glovy AI Photo Generator 2API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_client_kwargs: Dict[str, Any] = {}
if os.environ.get("APERO_PROXY"):
    _client_kwargs["proxy"] = os.environ["APERO_PROXY"]
if os.environ.get("APERO_API_KEY"):
    _client_kwargs["api_key"] = os.environ["APERO_API_KEY"]
_client = AperoClient(**_client_kwargs)

_stats = {
    "started_at": time.time(),
    "requests": 0,
    "ok": 0,
    "fail": 0,
    "latency_ms": deque(maxlen=500),
    "errors": deque(maxlen=30),
    "recent": deque(maxlen=30),
}


def _record(ok: bool, ms: float, detail: Optional[str] = None) -> None:
    _stats["requests"] += 1
    _stats["ok" if ok else "fail"] += 1
    _stats["latency_ms"].append(ms)
    if not ok and detail:
        _stats["errors"].append({"t": round(time.time(), 1), "error": detail[:300]})
    _stats["recent"].append({"t": round(time.time(), 1), "ok": ok, "ms": round(ms, 1)})


def _pct(values: Deque[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1))))], 1)


@app.on_event("startup")
async def _warm() -> None:
    if MOCK:
        print("[warmup] MOCK mode — 不连上游")
        return
    try:
        ts = await asyncio.to_thread(_client.server_timestamp)
        print(f"[warmup] server ts={ts} offset={_client._offset_ms}ms proxy={_client.proxies}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warmup] 时钟同步失败: {exc}（回退本机时间）")


# ---------------------------------------------------------------- 上游调用
def _mock_result(kind: str, prompt: str) -> Dict[str, Any]:
    return {
        "url": f"https://mock.local/{kind}/{uuid.uuid4().hex}.jpeg",
        "path": f"mock/{kind}/{uuid.uuid4().hex}.jpeg",
        "mock": True,
        "prompt": prompt[:120],
    }


async def _do_edit(raw: bytes, ctype: str, style_id: Optional[str], prompt: Optional[str],
                   negative: Optional[str], seed: Optional[int]) -> Dict[str, Any]:
    if MOCK:
        await asyncio.sleep(0.05)
        return _mock_result("edit", prompt or "")

    def _work() -> Dict[str, Any]:
        path = _client.upload_image(raw, ctype)
        return _client.image_edit(path, style_id=style_id, positive_prompt=prompt,
                                  negative_prompt=negative, seed=seed)

    t0 = time.time()
    try:
        data = await asyncio.to_thread(_work)
    except (AperoError, requests.RequestException) as exc:
        _record(False, (time.time() - t0) * 1000, str(exc))
        raise HTTPException(status_code=502, detail=f"upstream: {exc}") from exc
    _record(True, (time.time() - t0) * 1000)
    return {"type": "image", "url": data.get("url"), "path": data.get("path"),
            "elapsed_ms": round((time.time() - t0) * 1000)}


async def _do_t2i(prompt: str, style_id: Optional[str], negative: Optional[str],
                  width: int, height: int, seed: Optional[int]) -> Dict[str, Any]:
    if MOCK:
        await asyncio.sleep(0.05)
        return _mock_result("t2i", prompt)

    t0 = time.time()
    try:
        data = await asyncio.to_thread(_client.text2image, prompt, style_id, negative, width, height, seed)
    except (AperoError, requests.RequestException) as exc:
        _record(False, (time.time() - t0) * 1000, str(exc))
        raise HTTPException(status_code=502, detail=f"upstream: {exc}") from exc
    _record(True, (time.time() - t0) * 1000)
    return {"type": "image", "url": data.get("url"), "path": data.get("path"),
            "elapsed_ms": round((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- 基础端点
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((ROOT / "demo.html").read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "mock": MOCK,
        "bundle": _client.bundle_id,
        "app_version": _client.app_version,
        "styles": len(STYLES),
        "uptime_s": round(time.time() - _stats["started_at"], 1),
    }


@app.get("/stats")
async def stats() -> Dict[str, Any]:
    total = _stats["requests"]
    return {
        "uptime_s": round(time.time() - _stats["started_at"], 1),
        "requests": total,
        "ok": _stats["ok"],
        "fail": _stats["fail"],
        "success_rate": round(_stats["ok"] / total * 100, 2) if total else 0.0,
        "p50_ms": _pct(_stats["latency_ms"], 50),
        "p95_ms": _pct(_stats["latency_ms"], 95),
        "errors": list(_stats["errors"])[-10:],
        "recent": list(_stats["recent"]),
    }


@app.get("/styles")
async def styles(q: Optional[str] = None, project: Optional[str] = None,
                 limit: int = Query(60, ge=1, le=300)) -> Dict[str, Any]:
    items = STYLES
    if project:
        items = [s for s in items if s.get("project") == project]
    if q:
        ql = q.lower()
        items = [s for s in items if ql in (s.get("name") or "").lower()]
    return {
        "count": len(items),
        "projects": sorted({s.get("project") for s in STYLES if s.get("project")}),
        "items": [
            {"id": s["_id"], "name": s.get("name"), "project": s.get("project"),
             "thumbnail": s.get("key"), "prompt": (s.get("prompt") or "")[:180]}
            for s in items[:limit]
        ],
    }


@app.get("/media")
async def media(url: str = Query(...)) -> Response:
    allowed = ("static.aperogroup.ai", "s3.amazonaws.com", "static.apero.vn", "mock.local")
    if not any(h in url for h in allowed):
        raise HTTPException(status_code=400, detail="host not allowed")
    if "mock.local" in url:
        raise HTTPException(status_code=404, detail="mock url")
    r = await asyncio.to_thread(requests.get, url, timeout=90, proxies=_client.proxies, verify=False)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"cdn {r.status_code}")
    return Response(content=r.content, media_type=r.headers.get("Content-Type", "application/octet-stream"))


@app.get("/debug/signature")
async def debug_signature() -> Dict[str, Any]:
    ts = _client.now_ms()
    return {
        "api_key_masked": _client.api_key[:6] + "..." + _client.api_key[-4:],
        "timestamp": ts,
        "signature": _client.sign(ts)[:48] + "...",
        "headers": {k: (v[:36] + "..." if len(v) > 36 else v) for k, v in _client.headers().items()},
    }


# ---------------------------------------------------------------- 平台原生
@app.post("/api/v1/generate")
async def generate(
    image: UploadFile = File(...),
    style_id: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    seed: Optional[int] = Form(None),
) -> Dict[str, Any]:
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image > 12MB")
    ctype = "image/png" if "png" in (image.content_type or "") else "image/jpg"
    style = STYLE_BY_ID.get(style_id) if style_id else None
    if style_id and style is None:
        raise HTTPException(status_code=404, detail=f"unknown style_id {style_id}")
    final_prompt = prompt or (style or {}).get("prompt")
    out = await _do_edit(raw, ctype, style_id, final_prompt, negative_prompt, seed)
    out.update({"request_id": uuid.uuid4().hex[:12], "style_id": style_id})
    return out


class T2IReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    style_id: Optional[str] = None
    negative_prompt: Optional[str] = None
    width: int = Field(768, ge=256, le=1536)
    height: int = Field(768, ge=256, le=1536)
    seed: Optional[int] = None


@app.post("/api/v1/text2image")
async def text2image(req: T2IReq) -> Dict[str, Any]:
    out = await _do_t2i(req.prompt, req.style_id, req.negative_prompt, req.width, req.height, req.seed)
    out["request_id"] = uuid.uuid4().hex[:12]
    return out


@app.post("/api/v1/video")
async def video(
    image: UploadFile = File(...),
    prompt: Optional[str] = Form(None),
    mode: str = Form("IMAGE_TO_VIDEO"),
    timeout_s: int = Form(300),
) -> Dict[str, Any]:
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    if MOCK:
        return {"type": "video", "url": f"https://mock.local/video/{uuid.uuid4().hex}.mp4", "mock": True}
    ctype = "image/png" if "png" in (image.content_type or "") else "image/jpg"

    def _work() -> Dict[str, Any]:
        path = _client.upload_image(raw, ctype, kind="video")
        created = _client.image2video(path, positive_prompt=prompt, mode=mode)
        vid = created.get("videoId") or created.get("id")
        if not vid:
            return {"raw": created}
        return _client.wait_video(vid, timeout_s=timeout_s)

    t0 = time.time()
    try:
        info = await asyncio.to_thread(_work)
    except (AperoError, requests.RequestException) as exc:
        _record(False, (time.time() - t0) * 1000, str(exc))
        raise HTTPException(status_code=502, detail=f"upstream: {exc}") from exc
    if "raw" in info:
        _record(False, (time.time() - t0) * 1000, json.dumps(info)[:200])
        raise HTTPException(status_code=502, detail=f"video create: {info['raw']}")
    _record(True, (time.time() - t0) * 1000)
    res = info.get("result") or {}
    return {"type": "video", "status": res.get("videoStatus"),
            "url": res.get("resultFile") or res.get("videoUrl") or res.get("url"),
            "error": res.get("errorMessage"),
            "elapsed_ms": round((time.time() - t0) * 1000)}


@app.get("/api/v1/operations")
async def operations() -> Dict[str, Any]:
    """列出全部已实测打通的上游图像处理能力。"""
    return {"count": len(OPERATIONS), "items": [
        {"name": k, "desc": v["desc"], "needs": v["needs"], "path": v["path"]}
        for k, v in OPERATIONS.items()
    ]}


@app.post("/api/v1/op/{name}")
async def run_op(
    name: str,
    image: UploadFile = File(...),
    prompt: Optional[str] = Form(None),
    mask: Optional[UploadFile] = File(None),
    cloth: Optional[UploadFile] = File(None),
    extra: Optional[str] = Form(None, description="附加 JSON，如 {\"clothType\":\"upper_body\"}"),
) -> Dict[str, Any]:
    """统一入口：enhance / restore / outpaint / remove-bg / remove-object / qwen-edit /
    beauty / clothes / fitting / segment / inpainting"""
    spec = OPERATIONS.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown operation {name}; 见 /api/v1/operations")
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image > 12MB")
    if "mask" in spec["needs"] and mask is None:
        raise HTTPException(status_code=400, detail=f"{name} 需要 mask 图")
    if "cloth_image" in spec["needs"] and cloth is None:
        raise HTTPException(status_code=400, detail="fitting 需要 cloth 图")
    ctype = "image/png" if "png" in (image.content_type or "") else "image/jpg"
    mask_b = await mask.read() if mask else None
    cloth_b = await cloth.read() if cloth else None
    extra_d: Dict[str, Any] = {}
    if extra:
        try:
            extra_d = json.loads(extra)
        except Exception:
            raise HTTPException(status_code=400, detail="extra 必须是合法 JSON") from None

    if MOCK:
        return {"type": "op", "op": name, "url": f"https://mock.local/{name}/{uuid.uuid4().hex}.jpeg", "mock": True}

    t0 = time.time()
    try:
        data = await asyncio.to_thread(_client.run_operation, name, raw, mask_b, cloth_b, prompt, extra_d, ctype)
    except (AperoError, requests.RequestException) as exc:
        _record(False, (time.time() - t0) * 1000, f"{name}: {exc}")
        raise HTTPException(status_code=502, detail=f"upstream: {exc}") from exc
    _record(True, (time.time() - t0) * 1000)
    out = {"type": "op", "op": name, "elapsed_ms": round((time.time() - t0) * 1000)}
    if isinstance(data, dict):
        out["url"] = data.get("url")
        out["path"] = data.get("path")
        out["raw"] = None if out["url"] else data
    else:
        out["raw"] = str(data)[:300]
    out["request_id"] = uuid.uuid4().hex[:12]
    return out


# ---------------------------------------------------------------- OpenAI 兼容
@app.get("/v1/models")
async def v1_models() -> Dict[str, Any]:
    base = [
        {"id": "glovy/text2image", "object": "model", "owned_by": "apero", "created": 0},
        {"id": "glovy/image-edit", "object": "model", "owned_by": "apero", "created": 0},
        {"id": "glovy/flux-klein-editing", "object": "model", "owned_by": "apero", "created": 0},
        {"id": "glovy/video", "object": "model", "owned_by": "apero", "created": 0},
    ]
    base += [{"id": f"glovy/{k}", "object": "model", "owned_by": "apero", "created": 0} for k in OPERATIONS]
    return {"object": "list", "data": base}


class ImageGenReq(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = "glovy/text2image"
    n: int = Field(1, ge=1, le=4)
    size: str = "768x768"
    style_id: Optional[str] = None
    seed: Optional[int] = None
    response_format: str = "url"


@app.post("/v1/images/generations")
async def images_generations(req: ImageGenReq) -> Dict[str, Any]:
    try:
        w, h = (int(x) for x in req.size.lower().split("x"))
    except Exception:
        raise HTTPException(status_code=400, detail="size must be WxH") from None
    if not (256 <= w <= 1536 and 256 <= h <= 1536):
        raise HTTPException(status_code=400, detail="size out of range 256..1536")
    outs = []
    for _ in range(req.n):
        r = await _do_t2i(req.prompt, req.style_id, None, w, h, req.seed)
        outs.append({"url": r["url"], "revised_prompt": req.prompt})
    return {"created": int(time.time()), "data": outs}


@app.post("/v1/images/edits")
async def images_edits(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    model: str = Form("glovy/image-edit"),
    style_id: Optional[str] = Form(None),
    size: str = Form("768x768"),
    op: Optional[str] = Form(None, description="enhance/restore/outpaint/remove-bg/qwen-edit/beauty/clothes/segment"),
    mask: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    if len(prompt) > 2000:
        raise HTTPException(status_code=400, detail="prompt too long")
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image > 12MB")
    ctype = "image/png" if "png" in (image.content_type or "") else "image/jpg"

    # 能力路由：显式 op，或模型名写作 glovy/<op>
    op_name = op
    if not op_name and model.startswith("glovy/"):
        cand = model.split("/", 1)[1]
        if cand in OPERATIONS:
            op_name = cand
    if op_name:
        spec = OPERATIONS.get(op_name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"unknown op {op_name}")
        if "mask" in spec["needs"] and mask is None:
            raise HTTPException(status_code=400, detail=f"{op_name} needs mask")
        if MOCK:
            return {"created": int(time.time()),
                    "data": [{"url": f"https://mock.local/{op_name}/{uuid.uuid4().hex}.jpeg"}]}
        mask_b = await mask.read() if mask else None
        t0 = time.time()
        try:
            data = await asyncio.to_thread(_client.run_operation, op_name, raw, mask_b, None, prompt or None, {}, ctype)
        except (AperoError, requests.RequestException) as exc:
            _record(False, (time.time() - t0) * 1000, f"{op_name}: {exc}")
            raise HTTPException(status_code=502, detail=f"upstream: {exc}") from exc
        _record(True, (time.time() - t0) * 1000)
        return {"created": int(time.time()),
                "data": [{"url": (data or {}).get("url") if isinstance(data, dict) else None,
                          "revised_prompt": prompt}]}

    r = await _do_edit(raw, ctype, style_id, prompt, None, None)
    return {"created": int(time.time()), "data": [{"url": r["url"], "revised_prompt": prompt}]}


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8956"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
