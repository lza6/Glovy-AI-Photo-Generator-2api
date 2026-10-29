"""Glovy 2API 本地压测

用法:
  python bench.py --mode mock  --total 200 --concurrency 10
  python bench.py --mode real  --total 10  --concurrency 2 --kind t2i    # 真实上游，低量
  python bench.py --mode real  --total 6   --concurrency 1 --kind i2i

注意: real 模式会真实消耗上游算力，默认上限 30 次，避免把免费/共享额度打穿。
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import requests

ROOT = Path(__file__).parent
TEST_IMAGE = Path("D:/apk-analysis/fravix/in1.jpg")
STYLE_ID = "64b260c21d50d66f545ea9f8"  # Ghibi (AnimecoreAI)


def one(base: str, kind: str, prompt: str, style_id: str | None) -> Dict[str, Any]:
    t0 = time.time()
    try:
        if kind == "t2i":
            r = requests.post(f"{base}/api/v1/text2image", timeout=300,
                              json={"prompt": prompt, "style_id": style_id, "width": 768, "height": 768})
        else:
            with open(TEST_IMAGE, "rb") as fh:
                files = {"image": ("in1.jpg", fh.read(), "image/jpeg")}
            data = {"prompt": prompt}
            if style_id:
                data["style_id"] = style_id
            r = requests.post(f"{base}/api/v1/generate", files=files, data=data, timeout=300)
        ms = (time.time() - t0) * 1000
        ok = r.status_code == 200
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        return {"ok": ok, "ms": ms, "status": r.status_code,
                "err": None if ok else str(body)[:200], "url": (body or {}).get("url") if ok else None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "ms": (time.time() - t0) * 1000, "status": 0, "err": f"{type(exc).__name__}: {exc}"[:200], "url": None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8956")
    ap.add_argument("--mode", default="mock", choices=["mock", "real"])
    ap.add_argument("--kind", default="t2i", choices=["t2i", "i2i"])
    ap.add_argument("--total", type=int, default=50)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--style", default=STYLE_ID)
    ap.add_argument("--no-style", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.mode == "real" and args.total > 30:
        raise SystemExit("real 模式上限 30 次，请降低 --total（保护上游额度）")

    style = None if args.no_style else args.style
    base = args.url.rstrip("/")
    print(f"bench {args.mode}/{args.kind} total={args.total} concurrency={args.concurrency} style={style}")

    prompts = ["a cinematic portrait of a woman, soft rim light, 85mm",
               "a cozy cabin in snowy forest, golden hour",
               "cyberpunk street market at night, neon reflections",
               "a watercolor landscape with mountains and mist"]

    results: List[Dict[str, Any]] = []
    lock = threading.Lock()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(one, base, args.kind, prompts[i % len(prompts)], style) for i in range(args.total)]
        for i, f in enumerate(futs, 1):
            res = f.result()
            with lock:
                results.append(res)
                mark = "ok " if res["ok"] else "ERR"
                print(f"  [{i}/{args.total}] {mark} {res['ms']:.0f}ms {'' if res['ok'] else res['err']}")
    wall = time.time() - t0

    oks = [r for r in results if r["ok"]]
    lat = sorted(r["ms"] for r in oks)
    def pct(p: float) -> float:
        if not lat:
            return 0.0
        return round(lat[min(len(lat) - 1, int(round(p / 100 * (len(lat) - 1))))], 1)

    summary = {
        "mode": args.mode, "kind": args.kind, "total": args.total, "concurrency": args.concurrency,
        "ok": len(oks), "fail": len(results) - len(oks),
        "success_rate": round(len(oks) / len(results) * 100, 2),
        "wall_s": round(wall, 2),
        "rps": round(len(results) / wall, 2),
        "p50_ms": pct(50), "p90_ms": pct(90), "p95_ms": pct(95),
        "mean_ms": round(statistics.mean(lat), 1) if lat else 0,
        "min_ms": round(lat[0], 1) if lat else 0, "max_ms": round(lat[-1], 1) if lat else 0,
        "errors": [r["err"] for r in results if not r["ok"]][:10],
        "sample_url": oks[0]["url"] if oks else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    out = Path(args.out) if args.out else ROOT / f"bench_{args.mode}_{args.kind}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
