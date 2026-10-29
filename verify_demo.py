"""demo.html 真实浏览器路径验证（Playwright/Chromium）

覆盖: 首屏 → 健康状态 → 风格库渲染 → 搜索并选风格 → 上传图片 → 生成 → 出图 → 统计刷新
产出: shots/demo_idle.png / demo_style.png / demo_result.png
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("DEMO_URL", "http://127.0.0.1:8956/")
IMG = os.environ.get("DEMO_IMG", r"D:\apk-analysis\fravix\in1.jpg")
SHOTS = Path(__file__).parent / "shots"
SHOTS.mkdir(exist_ok=True)


def main() -> int:
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1200)
        badge = page.inner_text("#modeBadge")
        print("mode badge:", badge)
        page.screenshot(path=str(SHOTS / "demo_idle.png"), full_page=True)

        # 风格库
        n = page.locator("#styleList .style").count()
        print("style tiles:", n)
        assert n > 0, "风格库未渲染"

        # 搜索 + 选第一个
        page.fill("#styleSearch", "ghibli")
        page.wait_for_timeout(1500)
        n2 = page.locator("#styleList .style").count()
        print("ghibli tiles:", n2)
        assert n2 > 0, "搜索无结果"
        page.locator("#styleList .style").first.click()
        page.wait_for_timeout(400)
        hint = page.inner_text("#styleHint")
        print("style hint:", hint)
        page.screenshot(path=str(SHOTS / "demo_style.png"), full_page=True)

        # 上传图片
        page.set_input_files("#file", IMG)
        page.wait_for_timeout(600)
        assert page.is_visible("#preview"), "预览未显示"

        # 生成
        page.click("#go")
        print("generating …")
        got = False
        deadline = time.time() + 180
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            if page.locator("#gallery .card").count() > 0:
                card = page.locator("#gallery .card").first
                cls = card.get_attribute("class") or ""
                if "err" in cls:
                    print("ERROR card:", card.inner_text())
                else:
                    img = card.locator("img").first
                    w = img.evaluate("el => el.naturalWidth") if img.count() else 0
                    print("result naturalWidth:", w)
                    got = bool(w)
                    if got:
                        break
            if not page.is_disabled("#go") and time.time() > deadline - 170:
                pass
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOTS / "demo_result.png"), full_page=True)
        stats = page.inner_text("header")
        print("header stats:", " ".join(stats.split()))

        browser.close()

    if errors:
        print("CONSOLE ERRORS:")
        for e in errors[:10]:
            print("  ", e)
    print("RESULT:", "PASS" if got else "FAIL")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
