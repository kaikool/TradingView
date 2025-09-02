# app.py
# -*- coding: utf-8 -*-
import os
import time
from datetime import datetime
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from starlette.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

# ================== HARDCODE ==================
HARDCODE = {
    "USERNAME": "taotaufx",
    "PASSWORD": "jigno9-hurfyx-xibmYb",
    "SESSIONID": "o1hixcbxh1cvz59ri1u6d9juggsv9jko"
}

URLS = {
    "tvchart": "https://www.tradingview.com/chart",
    "tvcoins": "https://www.tradingview.com/accounts/tvcoins/",
    "signin":  "https://www.tradingview.com/accounts/signin/"
}

DEFAULT_CHART_ID = "fCLTltqk"  # hardcode theo yêu cầu

# ================== FastAPI ==================
app = FastAPI(title="TradingView Capture API (Hardcode)", version="1.1.0")

# Serve trang tĩnh
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html", status_code=307)

# ================== Session ==================
def _probe_sessionid(tvcoins_url: str, sessionid: str) -> bool:
    try:
        r = requests.get(tvcoins_url, headers={'cookie': f'sessionid={sessionid}'}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

def get_or_refresh_sessionid() -> str:
    sid = HARDCODE.get("SESSIONID")
    if not sid:
        raise RuntimeError("Chưa hardcode SESSIONID trong HARDCODE.")
    # Bỏ qua probe theo yêu cầu
    return sid

# ================== Selenium helpers ==================
def setup_driver(window_size="1920,1080", headless=True):
    opts = Options()
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--disable-notifications')
    opts.add_argument('--force-dark-mode')
    opts.add_argument(f'--window-size={window_size}')
    # bật headless (Cloud Run môi trường headless). Vẫn gửi Alt+S bình thường.
    if headless:
        opts.add_argument('--headless=new')
    # Cho phép clipboard API (phòng khi cần)
    opts.add_argument('--enable-blink-features=ClipboardCustomFormats')
    opts.add_argument('--enable-features=ClipboardDOM')

    driver = webdriver.Chrome(options=opts)

    # Thử “grant” quyền clipboard (không phải lúc nào cũng cần, nhưng an toàn)
    try:
        driver.execute_cdp_cmd("Browser.grantPermissions", {
            "origin": "https://www.tradingview.com",
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite", "notifications"]
        })
    except Exception:
        pass

    return driver

def inject_tv_session(driver, sessionid: str):
    driver.get("https://www.tradingview.com")
    # đợi cookie có thể set
    time.sleep(1)
    driver.add_cookie({
        'name': 'sessionid',
        'value': sessionid,
        'domain': '.tradingview.com',
        'path': '/',
        'secure': True,
        'httpOnly': True,
        'sameSite': 'Lax'
    })
    # refresh để áp dụng phiên
    driver.get("https://www.tradingview.com")
    time.sleep(1)

def _interval_from_timeframe(tf: str) -> str:
    """
    Map timeframe hiển thị -> query param interval của TradingView.
    - Số phút: 1,3,5,15,30 => '1','3','5','15','30'
    - Giờ: H1=60, H2=120, H4=240, H6=360, H12=720
    - Ngày/tuần/tháng: 'D','W','M'
    - Trả về chuỗi dùng cho &interval=
    """
    if not tf:
        return "D"
    s = tf.strip().upper()
    # Các dạng phổ biến
    if s in ("D", "1D"):
        return "D"
    if s in ("W", "1W"):
        return "W"
    if s in ("M", "1M", "MN"):
        return "M"

    if s.endswith("M"):  # phút
        try:
            m = int(s[:-1])
            return str(max(1, m))
        except:
            return "D"

    if s.startswith("H"):  # giờ
        try:
            h = int(s[1:])
            return str(h * 60)
        except:
            return "60"

    # fallback
    return "D"

def build_chart_url(chart_id: str, ticker: Optional[str], timeframe: Optional[str]) -> str:
    tvchart = URLS["tvchart"].rstrip('/')
    url = f"{tvchart}/{(chart_id or DEFAULT_CHART_ID).strip('/')}/"
    params = []
    if ticker and ticker != "NONE":
        params.append(f"symbol={ticker}")
    if timeframe:
        params.append(f"interval={_interval_from_timeframe(timeframe)}")
    if params:
        url += "?" + "&".join(params)
    return url

def trigger_alt_s_and_get_url(driver, wait_secs: int = 15) -> str:
    """
    Gửi Alt+S để mở snapshot dialog, rồi lấy link từ input trong modal (value^='https://www.tradingview.com/x/').
    """
    # Thử đóng overlay nào đó bằng ESC
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    time.sleep(0.5)

    # Gửi Alt+S
    ActionChains(driver).key_down(Keys.ALT).send_keys('s').key_up(Keys.ALT).perform()

    # Đợi modal + input chứa URL xuất hiện
    # Nhiều layout khác nhau, cách chắc ăn là tìm bất kỳ <input> có value bắt đầu bằng URL snapshot.
    target_prefixes = [
        "https://www.tradingview.com/x/",
        "https://www.tradingview.com/chart/"]  # phong hờ biến thể
    end = time.time() + wait_secs
    last_val = ""
    while time.time() < end:
        try:
            inputs = driver.find_elements(By.CSS_SELECTOR, "input,textarea")
            for el in inputs:
                val = (el.get_attribute("value") or "").strip()
                if any(val.startswith(p) for p in target_prefixes):
                    return val
                last_val = val or last_val
        except Exception:
            pass
        time.sleep(0.3)

    raise RuntimeError("Không lấy được URL snapshot từ modal Alt+S (UI có thể thay đổi).")

def capture_chart_screenshot_url(driver,
                                 chart_id: str,
                                 ticker: str = "NONE",
                                 timeframe: Optional[str] = "D",
                                 adjustment: int = 30,
                                 load_wait: int = 5) -> str:
    chart_url = build_chart_url(chart_id, ticker, timeframe)
    driver.get(chart_url)

    # cho chart load
    time.sleep(max(1, load_wait))

    # nắn timeline một chút (phím RIGHT)
    if adjustment and adjustment > 0:
        act = ActionChains(driver)
        act.send_keys(Keys.ESCAPE).perform()
        for _ in range(int(adjustment)):
            act.send_keys(Keys.RIGHT)
        act.perform()
        time.sleep(0.5)

    # kích Alt+S và đọc URL
    url = trigger_alt_s_and_get_url(driver, wait_secs=20)
    return url

def quit_driver(driver):
    try:
        driver.close()
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass

# ================== API models ==================
class CaptureRequest(BaseModel):
    chart: Optional[str] = DEFAULT_CHART_ID
    ticker: Optional[str] = "NONE"
    timeframe: Optional[str] = "D"       # NEW
    window_size: Optional[str] = "1920,1080"
    headless: Optional[bool] = True      # Cloud Run bắt buộc headless
    adjustment: Optional[int] = 30
    load_wait: Optional[int] = 5

# ================== Endpoints ==================
@app.get("/health")
def health():
    # Kiểm tra tối thiểu cho Selenium/Chrome
    selenium_ready = True
    try:
        # kiểm tra có thể khởi tạo rồi quit
        d = setup_driver(headless=True)
        d.get("https://www.tradingview.com")
        quit_driver(d)
    except Exception:
        selenium_ready = False

    return {"ok": True, "selenium_ready": selenium_ready, "time": datetime.now().isoformat()}

@app.post("/capture")
def capture(req: CaptureRequest):
    driver = None
    try:
        sid = get_or_refresh_sessionid()
        driver = setup_driver(window_size=req.window_size, headless=req.headless)
        inject_tv_session(driver, sid)
        screenshot_url = capture_chart_screenshot_url(
            driver,
            chart_id=(req.chart or DEFAULT_CHART_ID),
            ticker=req.ticker or "NONE",
            timeframe=req.timeframe or "D",
            adjustment=req.adjustment or 30,
            load_wait=req.load_wait or 5
        )
        return {"ok": True, "screenshot_url": screenshot_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Capture error: {e}")
    finally:
        if driver:
            quit_driver(driver)

# ================== Bootstrap ==================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
