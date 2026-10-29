"""Glovy / Apero 集团 AI 生图网关 — 纯协议客户端

目标 App: Glovy - AI Photo Generator 1.9.0
    package  com.aiphotogenerator.aivideomaker.photoslideshow
    内部 SDK com.apero.aigenerate (Apero / VisionLab 白标模板)

协议（静态确认 + 实测通过，详见 docs/REVERSE-REPORT.md）:
  base            https://api-img-gen-wrapper.aperogroup.ai     (ApiClient / BuildConfig.URL_IMAGE_AI)
  时间戳          GET  /timestamp                                → data.timestamp(ms)
  签名            RSA/ECB/PKCS1Padding  Base64( pubkey, f"{ts}@@@{api_key}@@@{rand}" )
                  注意: 服务端只验「能被私钥解开」+ ts 窗口，keyid 白名单在业务端点才校验
  公共头          x-api-signature / x-api-timestamp / x-api-keyid / x-api-token
                  x-api-bundleId / App-name / App-version / Country-code / device
  上传            GET  /api/v5/image-ai/presigned-link           → data.{url,path}
                  PUT  {url}  (不要带签名头)
  图生图/风格化   POST /api/v5/image-ai  {file|files, styleId?, positivePrompt?, ...}
  文生图          POST /api/v5/premium/text-2-image {positivePrompt, styleId?, width, height, seed?}
  图生视频        GET  /api/v5/image-2-video/presigned-link     (video-gen-core)
                  POST /api/v5/image-2-video {files, positivePrompt, ...}
                  GET  /api/v5/image-2-video/video/{videoId}      → videoStatus 轮询
  风格库          GET  https://api-style-manager.aperogroup.ai/v3/styles?page=N   (3826 条)
                  GET  https://api-style-manager.aperogroup.ai/category            (590 类目)

用法:
    from apero_client import AperoClient
    c = AperoClient()
    print(c.text2image("a cyberpunk cat", style_id="64b260c21d50d66f545ea9f8"))
"""

from __future__ import annotations

import base64
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ----------------------------------------------------------------------------- 常量
IMAGE_BASE = "https://api-img-gen-wrapper.aperogroup.ai"
VIDEO_BASE = "https://video-gen-core.aperogroup.ai"
STYLE_BASE = "https://api-style-manager.aperogroup.ai"

# 各业务服务 host。实测：presigned 上传链只在 wrapper 上有路由，其它 host 的
# /api/v5/*/presigned-link 一律 404 —— 传图统一走 wrapper，业务调用才分发到专用 host。
HOSTS = {
    "wrapper": IMAGE_BASE,
    "video": VIDEO_BASE,
    "beauty": "https://beauty-core.aperogroup.ai",
    "enhance": "https://enhance-core.aperogroup.ai",
    "outpaint": "https://core-outpaint.aperogroup.ai",
    "restore": "https://image-restore-core.aperogroup.ai",
    "segment": "https://segment-core.aperogroup.ai",
    "objectrm": "https://objectremoval-core.aperogroup.ai",
    "cloth": "https://cloth-change-core.aperogroup.ai",
    "fitting": "https://fitting-core.aperogroup.ai",
    "premium": "https://art-premium-core.aperogroup.ai",
}

# 图像处理能力表（实测 2026-10-29 全部 201 成功）
OPERATIONS: Dict[str, Dict[str, Any]] = {
    "enhance":          {"host": "wrapper",  "path": "/api/v5/image-enhance",     "needs": ["image"], "desc": "画质增强"},
    "restore":          {"host": "wrapper",  "path": "/api/v5/image-restore",     "needs": ["image"], "desc": "老照片修复"},
    "outpaint":         {"host": "wrapper",  "path": "/api/v5/image-outpainting", "needs": ["image"], "desc": "扩图"},
    "remove-bg":        {"host": "wrapper",  "path": "/api/v5/remove-background", "needs": ["image"], "desc": "抠背景"},
    "remove-object":    {"host": "wrapper",  "path": "/api/v5/remove-object",     "needs": ["image", "mask"], "desc": "去物体"},
    "qwen-edit":        {"host": "wrapper",  "path": "/api/v5.1/qwen-editing",    "needs": ["image"], "desc": "自然语言编辑"},
    "beauty":           {"host": "beauty",   "path": "/api/v5/beauty",            "needs": ["image"], "desc": "人像美颜"},
    "clothes":          {"host": "cloth",    "path": "/api/v5/clothes-changing",  "needs": ["image"], "desc": "AI 换装（单图）"},
    "fitting":          {"host": "fitting",  "path": "/api/v5/fitting",           "needs": ["image", "cloth_image"], "desc": "服装试穿（双图）"},
    "segment":          {"host": "segment",  "path": "/api/v5/segment",           "needs": ["image"], "desc": "图像分割"},
    "inpainting":       {"host": "wrapper",  "path": "/api/v1/image-inpainting",  "needs": ["image", "mask"], "desc": "局部重绘（multipart）"},
}

# ----------------------------------------------------------------------------- 凭据
# api_key 是上游租户凭据，不随仓库分发。三种获取方式（优先级从高到低）：
#   1. 环境变量 APERO_API_KEY
#   2. 同目录 config.json 的 {"api_key": "sk-..."}
#   3. python fetch_rc.py --app <app>   从 Firebase Remote Config 现取
API_KEY_ENV = "APERO_API_KEY"


def load_api_key(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    key = os.environ.get(API_KEY_ENV)
    if key:
        return key
    cfg = Path(__file__).with_name("config.json")
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get("api_key", "")
        except Exception:
            return ""
    return ""


# 协议公钥与包名来自 APK 静态资源（反编译可得，非秘密），是签名的必需输入
DEFAULT_PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA5z8DrSdxAFy5ju27JzxUDGD5OdPRnKVrXPypiBVT7NK4ltgbcud3+"
    "Li3H1DiAFNvaSDPumZMEbAkfGWZ6s3KtiI7TRmZwQ2yyH6mug6GhrCLD6CZJUQ2CPmhO3JYTYOgN53E6hwm/Teb9I156S04qHjLLLB"
    "xk9Mklu5X06kdhMBYwHFAZ3oByeoWUryrQC0Mv9C5ZahKzoQNuJNL2sv+ws2e5Zaj8Rid4AjhvqB6dYhWP4QM+0IiNjs/j08aRgcyOr"
    "enbQEIieU+XF6mQWF2Jfg317e0KjWnpru+uPVVgrEn9rNvQeXu2u4SZhT6rnLQzBLbJrngNcNw3gXfxxsoowIDAQAB"
)
DEFAULT_BUNDLE_ID = "com.hairai.hairstyletryon.haircolorchanger"
DEFAULT_APP_NAME = "AI_AIP862_com.hairai.hairstyletryon.haircolorchanger_Android_Vision_Lab"
DEFAULT_APP_VERSION = "2.1.1"
DEFAULT_API_TOKEN = "not_get_api_token"
OKHTTP_UA = "okhttp/4.12.0"


class AperoError(RuntimeError):
    """上游业务错误（statusCode != 200 或 HTTP >= 400）。"""


class AperoClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        public_key: str = DEFAULT_PUBLIC_KEY,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        app_name: str = DEFAULT_APP_NAME,
        app_version: str = DEFAULT_APP_VERSION,
        country_code: str = "US",
        timeout: int = 180,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = load_api_key(api_key)
        self.bundle_id = bundle_id
        self.app_name = app_name
        self.app_version = app_version
        self.country_code = country_code
        self.timeout = timeout
        self.session = session or requests.Session()
        self._offset_ms: Optional[int] = None
        self._pub = serialization.load_der_public_key(base64.b64decode(public_key))
        proxy = proxy if proxy is not None else os.environ.get("APERO_PROXY", "")
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

    # ------------------------------------------------------------------ 签名 / 头
    def _req(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("proxies", self.proxies)
        kw.setdefault("verify", False)
        return self.session.request(method, url, **kw)

    def server_timestamp(self) -> int:
        """同步服务器时间。/timestamp 也要带完整签名头（边缘层 412 校验），但不校验 api key。"""
        r = self._req("GET", f"{IMAGE_BASE}/timestamp", headers=self.headers(ts=int(time.time() * 1000)))
        r.raise_for_status()
        ts = int(r.json()["data"]["timestamp"])
        self._offset_ms = ts - int(time.time() * 1000)
        return ts

    def now_ms(self) -> int:
        if self._offset_ms is None:
            try:
                return self.server_timestamp()
            except Exception:
                return int(time.time() * 1000)
        return int(time.time() * 1000) + self._offset_ms

    def sign(self, ts: int) -> str:
        payload = f"{ts}@@@{self.api_key}@@@{int(random.random() * 33554432)}".encode()
        return base64.b64encode(self._pub.encrypt(payload, padding.PKCS1v15())).decode()

    def headers(self, ts: Optional[int] = None) -> Dict[str, str]:
        ts = int(ts if ts is not None else self.now_ms())
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "device": "android",
            "x-api-signature": self.sign(ts),
            "x-api-timestamp": str(ts),
            "x-api-keyid": self.api_key,
            "x-api-token": DEFAULT_API_TOKEN,
            "x-api-bundleId": self.bundle_id,
            "App-name": self.app_name,
            "App-version": self.app_version,
            "Country-code": self.country_code,
            "User-Agent": OKHTTP_UA,
        }

    @staticmethod
    def _unwrap(r: requests.Response) -> Any:
        try:
            body = r.json()
        except Exception:
            raise AperoError(f"HTTP {r.status_code} non-json: {r.text[:300]}")
        if r.status_code >= 400:
            msg = body.get("message") if isinstance(body, dict) else body
            code = body.get("errorCode") if isinstance(body, dict) else None
            raise AperoError(f"HTTP {r.status_code} {code}: {msg}")
        code = body.get("statusCode")
        if code is not None and int(code) != 200:
            raise AperoError(f"statusCode={code} message={body.get('message')!r}")
        return body.get("data", body)

    # ------------------------------------------------------------------ 上传
    def presigned_link(self, kind: str = "image") -> Dict[str, str]:
        base = IMAGE_BASE if kind == "image" else VIDEO_BASE
        path = "/api/v5/image-ai/presigned-link" if kind == "image" else "/api/v5/image-2-video/presigned-link"
        return self._unwrap(self._req("GET", base + path, headers=self.headers()))

    def upload(self, upload_url: str, content: bytes, content_type: str = "image/jpeg") -> None:
        # App 端 NetworkConstant.NOT_ADD_HEADER_METHODS = ["PUT"]：上传不带签名头
        r = self._req("PUT", upload_url, data=content, headers={"Content-Type": content_type})
        if r.status_code >= 400:
            raise AperoError(f"upload HTTP {r.status_code}: {r.text[:200]}")

    def upload_image(self, image_bytes: bytes, content_type: str = "image/jpeg", kind: str = "image") -> str:
        link = self.presigned_link(kind)
        self.upload(link["url"], image_bytes, content_type)
        return link["path"]

    # ------------------------------------------------------------------ 生成
    def image_edit(
        self,
        files: List[str] | str,
        style_id: Optional[str] = None,
        positive_prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        image_size: Optional[int] = None,
    ) -> Dict[str, str]:
        """图生图 / 风格化。files 为 upload_image 返回的 path。"""
        body: Dict[str, Any] = {"file": files if isinstance(files, str) else files[0]}
        if isinstance(files, list) and len(files) > 1:
            body["files"] = files
        if style_id:
            body["styleId"] = style_id
        if positive_prompt:
            body["positivePrompt"] = positive_prompt
        if negative_prompt:
            body["negativePrompt"] = negative_prompt
        if seed is not None:
            body["seed"] = seed
        if image_size is not None:
            body["imageSize"] = image_size
        return self._unwrap(self._req("POST", f"{IMAGE_BASE}/api/v5/image-ai", json=body, headers=self.headers()))

    def text2image(
        self,
        prompt: str,
        style_id: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        width: int = 768,
        height: int = 768,
        seed: Optional[int] = None,
    ) -> Dict[str, str]:
        body: Dict[str, Any] = {"positivePrompt": prompt, "width": width, "height": height}
        if style_id:
            body["styleId"] = style_id
        if negative_prompt:
            body["negativePrompt"] = negative_prompt
        if seed is not None:
            body["seed"] = seed
        return self._unwrap(
            self._req("POST", f"{IMAGE_BASE}/api/v5/premium/text-2-image", json=body, headers=self.headers())
        )

    def image2video(
        self,
        image_path: str,
        positive_prompt: Optional[str] = None,
        mode: str = "i2v",
        keep_face: bool = False,
        width: Optional[int] = None,
        height: Optional[int] = None,
        lora_name: Optional[str] = None,
        model: Optional[str] = None,
        notification_provider: str = "firebase",
        notification_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"files": [image_path], "mode": mode, "keepFace": keep_face,
                                "notificationProvider": notification_provider}
        for k, v in (("positivePrompt", positive_prompt), ("width", width), ("height", height),
                     ("loraName", lora_name), ("model", model), ("notificationId", notification_id)):
            if v is not None:
                body[k] = v
        return self._unwrap(self._req("POST", f"{VIDEO_BASE}/api/v5/image-2-video", json=body, headers=self.headers()))

    def video_info(self, video_id: str) -> Dict[str, Any]:
        return self._unwrap(
            self._req("GET", f"{VIDEO_BASE}/api/v5/image-2-video/video/{video_id}", headers=self.headers())
        )

    def wait_video(self, video_id: str, timeout_s: int = 300, interval_s: float = 4.0) -> Dict[str, Any]:
        """轮询视频任务。状态在 data.result.videoStatus（成功时 result 里带 url/file）。"""
        deadline = time.time() + timeout_s
        last: Dict[str, Any] = {}
        while time.time() < deadline:
            last = self.video_info(video_id)
            res = last.get("result") or {}
            st = str(res.get("videoStatus") or "").upper()
            if st in ("SUCCESS", "COMPLETED", "FAILED", "ERROR", "CANCELED"):
                return last
            time.sleep(interval_s)
        return last

    # ------------------------------------------------------------------ 通用图像处理
    def run_operation(
        self,
        name: str,
        image_bytes: bytes,
        mask_bytes: Optional[bytes] = None,
        cloth_bytes: Optional[bytes] = None,
        prompt: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        content_type: str = "image/jpg",
    ) -> Any:
        """执行 `OPERATIONS` 中的任一图像处理能力（enhance/restore/outpaint/remove-bg/
        remove-object/qwen-edit/beauty/clothes/fitting/segment/inpainting）。

        传图一律走 wrapper 的 presigned 链；业务调用分发到对应 host。
        """
        spec = OPERATIONS.get(name)
        if spec is None:
            raise AperoError(f"unknown operation: {name}")
        base = HOSTS[spec["host"]]
        url = base + spec["path"]
        need = spec["needs"]

        if name == "inpainting":
            # 该端点要求 multipart/form-data（Body 为原始 RequestBody），不走 presigned
            mask_path = self.upload_image(mask_bytes, content_type) if mask_bytes else ""
            headers = {k: v for k, v in self.headers().items() if k.lower() != "content-type"}
            return self._unwrap(
                self._req(
                    "POST", url,
                    files={"file": ("image.jpg", image_bytes, "image/jpeg")},
                    data={"mask": mask_path, "prompt": prompt or ""},
                    headers=headers,
                )
            )

        path = self.upload_image(image_bytes, content_type)
        body: Dict[str, Any] = {}
        if name == "qwen-edit":
            body = {"files": [path], "mode": "IMAGE_EDITING", "acceptNSFW": False}
            if prompt:
                body["positivePrompt"] = prompt
        elif name == "remove-object":
            if not mask_bytes:
                raise AperoError("remove-object 需要 mask 图")
            body = {"file": path, "mask": self.upload_image(mask_bytes, content_type)}
        elif name == "fitting":
            if not cloth_bytes:
                raise AperoError("fitting 需要 cloth_image（服装图）")
            body = {"inputImage": path, "clothImage": self.upload_image(cloth_bytes, content_type),
                    "clothType": (extra or {}).get("clothType", "upper_body")}
        else:
            body = {"file": path}
            if prompt:
                body["prompt"] = prompt
                body["positivePrompt"] = prompt
        if extra:
            body.update({k: v for k, v in extra.items() if k not in body})
        return self._unwrap(self._req("POST", url, json=body, headers=self.headers()))

    # ------------------------------------------------------------------ 风格库
    def styles(self, page: int = 1) -> Dict[str, Any]:
        return self._unwrap(self._req("GET", f"{STYLE_BASE}/v3/styles?page={page}", headers=self.headers()))

    def categories(self) -> Dict[str, Any]:
        return self._unwrap(self._req("GET", f"{STYLE_BASE}/category", headers=self.headers()))

    def all_styles(self) -> List[Dict[str, Any]]:
        out, page = [], 1
        while True:
            d = self.styles(page)
            out.extend(d["items"])
            if page >= d.get("totalPages", 1):
                return out
            page += 1

    def health(self) -> Dict[str, Any]:
        r = self._req("GET", f"{IMAGE_BASE}/health", headers=self.headers())
        return r.json()


if __name__ == "__main__":
    import json
    import sys

    c = AperoClient()
    print("server ts:", c.server_timestamp())
    print("health:", json.dumps(c.health())[:200])
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as fh:
            path = c.upload_image(fh.read())
        print("edit:", json.dumps(c.image_edit(path, positive_prompt="portrait, soft light")))
