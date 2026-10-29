"""从 APK 的 Firebase 项目拉取 Remote Config（拿 api_key / 风格配置）

流程（全部为 Firebase 官方 REST，无需真机、无需 Play Integrity）:
  1. POST firebaseinstallations.googleapis.com/v1/projects/{project}/installations  → fid + authToken
  2. POST firebaseremoteconfig.googleapis.com/v1/projects/{project}/namespaces/firebase:fetch
     → entries{}（新版 App 里叫 app_api_key / app_bundle_id / app_public_key，老版叫 api_key）

用法:
  python fetch_rc.py --app glovy            # 输出 rc_glovy.json，只打印关键字段
  python fetch_rc.py --app fravix
  python fetch_rc.py --project x --appid y --pkg z --gkey AIza... --cert SHA1

注意: 需要能访问 Google 的网络（国内用 APERO_PROXY）。
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import sys
import uuid

import requests

PROXY = os.environ.get("APERO_PROXY", "")

APPS = {
    # Glovy / AIP893 —— 该 key 已被上游置为 Not active（ERR15），保留用于对照
    "glovy": dict(
        project="aip999-photo-video-slideshow",
        appid="1:699734493584:android:aeb86c4cd39521de204b15",
        pkg="com.aiphotogenerator.aivideomaker.photoslideshow",
        gkey="AIzaSyDklS05WRgQYDwXSQSJHR9KPcWZutI8A-s",
        cert="C8D25CDE81A3E1D9BAB2846AF3BBBAC1AA9F1A7A",  # Modyolo 重签名
        version="1.9.0",
    ),
    # Fravix / AIP862 —— 实测 key 有效，当前 2API 默认使用
    "fravix": dict(
        project="aip862-ai-hair-changer",
        appid="1:1096519110136:android:bcb66291e035a6d3b0da0d",
        pkg="com.hairai.hairstyletryon.haircolorchanger",
        gkey="AIzaSyBZZDuG71TR_FsIvNSlAu5TlvBz2GYXvMM",
        cert="142EB80763FA71FEA546D89F8612234EB4A55C5A",
        version="2.1.1",
    ),
}


def _proxies() -> dict | None:
    return {"http": PROXY, "https": PROXY} if PROXY else None


def install(project: str, appid: str, pkg: str, gkey: str, cert: str) -> tuple[str, str]:
    fid = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip("=")[:22]
    r = requests.post(
        f"https://firebaseinstallations.googleapis.com/v1/projects/{project}/installations",
        headers={"Content-Type": "application/json", "X-Android-Package": pkg, "X-Android-Cert": cert,
                 "x-goog-api-key": gkey, "User-Agent": "Firebase-Installations/17.0.0 (Android)"},
        json={"appId": appid, "authVersion": "FIS_v2", "fid": fid, "sdkVersion": "a:17.0.0"},
        timeout=40, proxies=_proxies(),
    )
    r.raise_for_status()
    j = r.json()
    return j["fid"], j["authToken"]["token"]


def fetch_rc(project: str, appid: str, pkg: str, gkey: str, cert: str, fid: str, token: str, version: str) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    body = {
        "app_id": appid,
        "app_instance_id": fid,
        "package_name": pkg,
        "country_code": "US",
        "language_code": "en",
        "platform_version": "34",
        "sdk_version": "22.0.6",
        "time_zone": "UTC",
        "app_version": version,
        "app_build": version,
        "first_open_time": (now - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    r = requests.post(
        f"https://firebaseremoteconfig.googleapis.com/v1/projects/{project}/namespaces/firebase:fetch?key={gkey}",
        headers={"Content-Type": "application/json", "X-Android-Package": pkg, "X-Android-Cert": cert,
                 "X-Goog-Api-Key": gkey, "X-Goog-Firebase-Installations-Auth": token,
                 "User-Agent": "Firebase-RC/22.0.6 (Android)"},
        json=body, timeout=40, proxies=_proxies(),
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(APPS), help="预置 App")
    ap.add_argument("--project")
    ap.add_argument("--appid")
    ap.add_argument("--pkg")
    ap.add_argument("--gkey")
    ap.add_argument("--cert")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--out")
    args = ap.parse_args()

    cfg = APPS[args.app] if args.app else {}
    merged = {
        "project": args.project or cfg.get("project"),
        "appid": args.appid or cfg.get("appid"),
        "pkg": args.pkg or cfg.get("pkg"),
        "gkey": args.gkey or cfg.get("gkey"),
        "cert": args.cert or cfg.get("cert"),
        "version": args.version if args.version != "1.0.0" else cfg.get("version", "1.0.0"),
    }
    missing = [k for k, v in merged.items() if not v]
    if missing:
        print("缺少参数:", missing, file=sys.stderr)
        return 2

    fid, token = install(merged["project"], merged["appid"], merged["pkg"], merged["gkey"], merged["cert"])
    rc = fetch_rc(merged["project"], merged["appid"], merged["pkg"], merged["gkey"], merged["cert"], fid, token,
                  merged["version"])
    entries = rc.get("entries", {})
    print(f"entries: {len(entries)}")
    for k in ("api_key", "app_api_key", "app_bundle_id", "app_app_name", "app_public_key"):
        if k in entries:
            v = entries[k]
            print(f"  {k} = {v[:24]}..." if k.endswith("key") else f"  {k} = {v}")
    out = args.out or f"rc_{args.app or 'custom'}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rc, fh, ensure_ascii=False, indent=1)
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
