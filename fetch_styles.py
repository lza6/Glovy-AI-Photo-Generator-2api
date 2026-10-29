"""抓取 Apero style-manager v3 全量风格库（3826 条）

凭据复用 apero_client 的加载逻辑（环境变量 APERO_API_KEY / config.json / fetch_rc.py）。
用法: python fetch_styles.py [输出文件名]
"""

import json
import os
import sys

from apero_client import AperoClient


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "styles_v3.json"
    client = AperoClient(proxy=os.environ.get("APERO_PROXY") or None)
    if not client.api_key:
        print("缺少 api_key：设置 APERO_API_KEY / config.json / 先跑 fetch_rc.py", file=sys.stderr)
        return 2
    styles = client.all_styles()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(styles, fh, ensure_ascii=False, indent=1)
    projects = sorted({s.get("project") for s in styles if s.get("project")})
    print(f"saved {len(styles)} styles / {len(projects)} projects → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
