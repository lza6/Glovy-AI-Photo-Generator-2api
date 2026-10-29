"""兄弟端点全量实测：enhance / restore / outpaint / qwen-editing / segment /
remove-background / remove-object / beauty / clothes / fitting / inpainting

每个端点：对应 host 的 presigned-link → S3 PUT → POST，记录 HTTP 码与响应首段。
输出 probe_siblings.json（证据）+ 控制台表格。

用法: python probe_siblings.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, ".")
from apero_client import IMAGE_BASE, AperoClient, AperoError

requests.packages.urllib3.disable_warnings()

IMG = Path("D:/apk-analysis/fravix/in1.jpg")
OUT = Path("probe_siblings.json")

HOSTS = {
    "wrapper": "https://api-img-gen-wrapper.aperogroup.ai",
    "enhance": "https://enhance-core.aperogroup.ai",
    "outpaint": "https://core-outpaint.aperogroup.ai",
    "restore": "https://image-restore-core.aperogroup.ai",
    "segment": "https://segment-core.aperogroup.ai",
    "objectrm": "https://objectremoval-core.aperogroup.ai",
    "beauty": "https://beauty-core.aperogroup.ai",
    "cloth": "https://cloth-change-core.aperogroup.ai",
    "fitting": "https://fitting-core.aperogroup.ai",
}

# (标签, host, 上传路径, 调用路径, body 模板)  body 里 {path} 会被替换成上传后的 path
CASES = [
    ("enhance",            "enhance", "/api/v5/image-enhance/presigned-link",            "/api/v5/image-enhance",            {"file": "{path}"}),
    ("restore",            "restore", "/api/v5/image-restore/presigned-link",            "/api/v5/image-restore",            {"file": "{path}"}),
    ("outpaint",           "outpaint", "/api/v5/image-outpainting/presigned-link",       "/api/v5/image-outpainting",        {"file": "{path}", "prompt": "extend the scene naturally", "upScale": 0.5, "leftScale": 0.0, "guidanceScale": 7}),
    ("remove-background",  "outpaint", "/api/v5/remove-background/presigned-link",       "/api/v5/remove-background",        {"file": "{path}"}),
    ("segment",            "segment", "/api/v5/segment/presigned-link",                  "/api/v5/segment",                  {"file": "{path}"}),
    ("remove-object",      "objectrm", "/api/v5/remove-object/presigned-link",           "/api/v5/remove-object",            {"file": "{path}", "mask": ""}),
    ("qwen-editing",       "wrapper", "/api/v5.1/qwen-editing/presigned-link",           "/api/v5.1/qwen-editing",           {"files": ["{path}"], "mode": "IMAGE_EDITING", "positivePrompt": "make it look like an oil painting", "acceptNSFW": False}),
    ("beauty-face",        "beauty",  "/api/v5/beauty/presigned-link",                   "/api/v5/beauty",                   {"file": "{path}", "smoothStrength": 0.5}),
    ("clothes-changing",   "cloth",   "/api/v5/clothes-changing/presigned-link",         "/api/v5/clothes-changing",         {"file": "{path}", "prompt": "wear a red jacket"}),
    ("fitting",            "fitting", "/api/v5/fitting/presigned-link",                  "/api/v5/fitting",                  {"file": "{path}", "prompt": "wear a blue shirt"}),
    ("inpainting",         "wrapper", None,                                              "/api/v1/image-inpainting",         {"file": "{path}", "mask": "", "prompt": "remove the object"}),
]


def run(c: AperoClient, img: bytes) -> list[dict]:
    out = []
    for tag, host, pre_path, api_path, body in CASES:
        rec = {"tag": tag, "host": HOSTS[host], "api": api_path}
        base = HOSTS[host]
        try:
            if pre_path:
                r = c._req("GET", base + pre_path, headers=c.headers(), timeout=60)
                rec["presigned_http"] = r.status_code
                if r.status_code != 200:
                    rec["presigned_body"] = r.text[:200]
                    out.append(rec)
                    continue
                link = r.json()["data"]
                up = c._req("PUT", link["url"], data=img, headers={"Content-Type": "image/jpg"}, timeout=90)
                rec["put_http"] = up.status_code
                path = link["path"]
            else:
                path = c.upload_image(img, kind="image")
            payload = json.loads(json.dumps(body).replace("{path}", path))
            t0 = time.time()
            r2 = c._req("POST", base + api_path, json=payload, headers=c.headers(), timeout=300)
            rec.update(http=r2.status_code, ms=round((time.time() - t0) * 1000), body=r2.text[:400])
            if r2.status_code == 200:
                try:
                    d = r2.json()
                    rec["result_url"] = ((d.get("data") or {}).get("url")
                                         or json.dumps(d)[:200])
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
        out.append(rec)
        print(f"[{tag:18s}] {rec.get('http', rec.get('error', rec.get('presigned_http')))} "
              f"{rec.get('ms','')} {str(rec.get('body') or rec.get('presigned_body') or '')[:110]}", flush=True)
    return out


def main() -> None:
    img = IMG.read_bytes()
    c = AperoClient(proxy=os.environ.get("APERO_PROXY") or "http://127.0.0.1:10808")
    res = run(c, img)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in res if r.get("http") == 200)
    print(f"\n{ok}/{len(res)} returned 200 → {OUT}")


if __name__ == "__main__":
    main()
