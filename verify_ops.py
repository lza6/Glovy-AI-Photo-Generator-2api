"""demo 页「图像处理能力」路径验证（enhance 出图 + mask 联动）

用法: python verify_ops.py   （需网关 LIVE 模式在 8956 运行）
"""

import time
from playwright.sync_api import sync_playwright
URL="http://127.0.0.1:8956/"; IMG=r"D:\apk-analysis\fravix\in1.jpg"
errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); pg=b.new_page(viewport={"width":1440,"height":1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(1000)
    pg.set_input_files("#file", IMG); pg.wait_for_timeout(400)
    pg.select_option("#op", "enhance")
    assert pg.is_visible("#maskRow") is False, "maskRow 不应显示"
    pg.fill("#prompt", "enhance details")
    pg.click("#go"); print("generating enhance …", flush=True)
    ok=False
    for _ in range(70):
        pg.wait_for_timeout(1500)
        if pg.locator("#gallery .card").count():
            c=pg.locator("#gallery .card").first
            if "err" in (c.get_attribute("class") or ""):
                print("ERR card:", c.inner_text()); break
            img=c.locator("img").first
            w=img.evaluate("el=>el.naturalWidth") if img.count() else 0
            if w: ok=True; print("ok naturalWidth", w); break
    pg.screenshot(path="shots/demo_op_enhance.png", full_page=True)
    # maskRow 联动
    pg.select_option("#op","remove-object"); pg.wait_for_timeout(300)
    print("maskRow visible for remove-object:", pg.is_visible("#maskRow"))
    b.close()
print("pageerrors:", errs[:3])
print("RESULT:", "PASS" if ok else "FAIL")
