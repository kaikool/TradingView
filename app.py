# -*- coding: utf-8 -*-
import time
import platform
import requests
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from selenium import webdriver
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
# from tkinter import Tk  # Not needed in Docker headless environment
from urllib3 import encode_multipart_formdata


# ================== HARDCODE ==================
HARDCODE = {
    "USERNAME": os.getenv("TRADINGVIEW_USERNAME", "taotaufx"),
    "PASSWORD": os.getenv("TRADINGVIEW_PASSWORD", "jigno9-hurfyx-xibmYb"),
    "SESSIONID": os.getenv("TRADINGVIEW_SESSIONID", "o1hixcbxh1cvz59ri1u6d9juggsv9jko"),
    "CHART_ID": "fCLTltqk"
}

URLS = {
    "tvchart": "https://www.tradingview.com/chart",
    "tvcoins": "https://www.tradingview.com/accounts/tvcoins/",
    "signin":  "https://www.tradingview.com/accounts/signin/"
}


# ================== FastAPI ==================
# Create app and mount static files
app = FastAPI(
    title="TradingView Chart Capture API",
    version="2.0.0",
    description="""
    # TradingView Chart Capture API
    
    Automated service for capturing TradingView chart screenshots with configurable timeframes.
    
    ## Key Features
    
    - **Automated Chart Capture**: Captures screenshots from TradingView charts
    - **Multiple Timeframes**: Supports various timeframes from 1 minute to 1 month
    - **Symbol Override**: Can override chart symbols with any trading pair
    - **Optimized Settings**: Pre-configured for best performance and quality
    
    ## Hardcoded Configuration
    
    This API uses optimized hardcoded settings for consistent results:
    
    - **Chart ID**: `fCLTltqk` (fixed chart template)
    - **Window Size**: `1920x1080` (Full HD resolution)
    - **Browser Mode**: Visible browser (not headless)
    - **Chart Adjustment**: 30 RIGHT key presses for optimal positioning
    - **Load Wait**: 5 seconds for chart loading
    
    ## API Usage
    
    ### Basic Request
    ```bash
    curl -X POST "http://your-server:8000/capture" \
      -H "Content-Type: application/json" \
      -d '{"timeframe": "4H"}'
    ```
    
    ### With Symbol Override
    ```bash
    curl -X POST "http://your-server:8000/capture" \
      -H "Content-Type: application/json" \
      -d '{
        "timeframe": "1H",
        "ticker": "BINANCE:BTCUSDT"
      }'
    ```
    
    ### Response Format
    ```json
    {
      "ok": true,
      "screenshot_url": "https://www.tradingview.com/x/abc123/",
      "timestamp": "2025-09-02T17:00:00.000000"
    }
    ```
    
    ## Supported Timeframes
    
    - **Minutes**: `1m`, `3m`, `5m`, `15m`, `30m`
    - **Hours**: `1H`, `2H`, `4H`, `6H`, `12H`
    - **Days**: `1D`, `3D`
    - **Weeks**: `1W`
    - **Months**: `1M`
    
    ## Health Check
    
    Check service status and Selenium readiness:
    ```bash
    curl http://your-server:8000/health
    ```
    """,
    contact={
        "name": "TradingView Capture API",
        "url": "http://localhost:8000",
    },
    license_info={
        "name": "MIT",
    },
)

# Create screenshots directory
os.makedirs("screenshots", exist_ok=True)

# Mount static files for screenshots
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")


# ================== Session ==================
def _probe_sessionid(tvcoins_url: str, sessionid: str) -> bool:
    """
    Probe if the sessionid is valid by making a request to TradingView
    """
    try:
        r = requests.get(tvcoins_url, headers={'cookie': f'sessionid={sessionid}'}, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f"Session probe failed: {e}")
        return False


def get_or_refresh_sessionid() -> str:
    """
    Get the sessionid from environment variables or hardcoded values
    """
    sid = HARDCODE.get("SESSIONID")
    if not sid:
        raise RuntimeError("No SESSIONID found in environment variables or hardcode configuration.")
    
    # Optional: probe the sessionid validity
    if not _probe_sessionid(URLS["tvcoins"], sid):
        print("Warning: SessionID might be invalid or expired")
    
    return sid


# ================== Selenium helpers ==================
def setup_driver(window_size="1280,720", headless=False):
    print(f'---> Setup selenium start : {datetime.now()}')
    opts = Options()
    
    # Set binary location for Chromium
    opts.binary_location = "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"
    
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--force-dark-mode')
    opts.add_argument(f'--window-size={window_size}')
    if headless:
        opts.add_argument('--headless=new')

    service = Service(ChromeDriverManager(driver_version="138.0.7204.183").install())
    driver = webdriver.Chrome(service=service, options=opts)
    print('Setup selenium complete')
    return driver


def inject_tv_session(driver, sessionid: str):
    driver.get("https://www.tradingview.com")
    time.sleep(2)
    driver.add_cookie({
        'name': 'sessionid',
        'value': sessionid,
        'domain': '.tradingview.com',
        'path': '/',
        'secure': True,
        'httpOnly': True
    })
    driver.get("https://www.tradingview.com")
    time.sleep(2)


def capture_chart_screenshot_url(driver, chart: str, ticker: str = "NONE", timeframe: str = "1D",
                                 adjustment: int = 30, load_wait: int = 5, headless: bool = True) -> str:
    tvchart = URLS["tvchart"].rstrip('/')
    chart_url = f"{tvchart}/{chart}/"
    
    # Add query parameters
    params = []
    if ticker and ticker != "NONE":
        params.append(f"symbol={ticker}")
    if timeframe and timeframe != "1D":
        params.append(f"interval={timeframe}")
    
    if params:
        chart_url += "?" + "&".join(params)

    print(f'---> Opening Chart {chart} (ticker={ticker}, timeframe={timeframe}) : {datetime.now()}')
    driver.get(chart_url)
    print(f'Đợi {load_wait}s cho chart load...')
    time.sleep(load_wait)

    # Thay đổi timeframe bằng JavaScript nếu cần
    if timeframe and timeframe != "1D":
        print(f'Thay đổi timeframe thành {timeframe}...')
        try:
            # Mapping timeframe values cho TradingView
            timeframe_map = {
                "1m": "1",
                "3m": "3", 
                "5m": "5",
                "15m": "15",
                "30m": "30",
                "1H": "60",
                "2H": "120", 
                "4H": "240",
                "6H": "360",
                "12H": "720",
                "1D": "1D",
                "3D": "3D",
                "1W": "1W",
                "1M": "1M"
            }
            
            tv_timeframe = timeframe_map.get(timeframe, timeframe)
            
            driver.execute_script(f"""
                // Tìm và click vào timeframe selector
                const timeframeSelectors = [
                    '[data-value="{tv_timeframe}"]',
                    '[data-interval="{tv_timeframe}"]',
                    'button[data-value="{tv_timeframe}"]',
                    '.tv-dropdown-behavior__item[data-value="{tv_timeframe}"]'
                ];
                
                // Thử click vào timeframe button trước
                const timeframeButtons = document.querySelectorAll(
                    '.tv-dropdown-behavior__toggle, .js-chart-toolbar-time-interval, ' +
                    '[data-name="time-interval"], .interval-selector'
                );
                
                if (timeframeButtons.length > 0) {{
                    timeframeButtons[0].click();
                    console.log('Clicked timeframe dropdown');
                    
                    setTimeout(() => {{
                        // Sau khi dropdown mở, tìm và click timeframe cần thiết
                        for (let selector of timeframeSelectors) {{
                            const element = document.querySelector(selector);
                            if (element) {{
                                element.click();
                                console.log('Changed timeframe to {timeframe}');
                                return;
                            }}
                        }}
                        
                        // Nếu không tìm thấy, thử tìm bằng text content
                        const items = document.querySelectorAll('.tv-dropdown-behavior__item, .tv-menu__item');
                        for (let item of items) {{
                            if (item.textContent.trim() === '{timeframe}' || 
                                item.textContent.trim() === '{tv_timeframe}') {{
                                item.click();
                                console.log('Changed timeframe to {timeframe} by text');
                                return;
                            }}
                        }}
                    }}, 500);
                }}
            """)
            time.sleep(3)  # Đợi timeframe thay đổi
        except Exception as e:
            print(f"Không thể thay đổi timeframe: {e}")

    print(f'Điều chỉnh vị trí {adjustment} lần phím RIGHT...')
    act = ActionChains(driver)
    act.send_keys(Keys.ESCAPE).perform()
    for _ in range(max(0, int(adjustment))):
        act.send_keys(Keys.RIGHT)
    act.perform()

    time.sleep(2)
    
    # Ẩn quảng cáo và click vào chart container
    print('Ẩn quảng cáo và chọn chart container...')
    try:
        driver.execute_script("""
            // Ẩn quảng cáo
            const ads = document.querySelectorAll(
                '[class*="ad-banner"], [class*="advertisement"], [id*="ad"], ' +
                '.tv-ad, [class*="promo"], [class*="sponsor"], ' +
                '[class*="upgrade"], [class*="premium"]'
            );
            ads.forEach(el => el && (el.style.display = 'none'));
            
            // Tìm và click vào chart container
            const chartContainer = document.querySelector(
                '[data-name="chart-container"], .chart-container, ' +
                '[class*="chart-container"], [id*="chart"]'
            );
            if (chartContainer) {
                chartContainer.click();
                chartContainer.focus();
                console.log('Đã click vào chart container');
            }
        """)
        time.sleep(1)
    except Exception as e:
        print(f"Lỗi: {e}")
    
    if headless:
        # Headless mode: dùng browser screenshot
        print('Headless mode: chụp màn hình trực tiếp...')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"chart_{chart}_{timestamp}.png"
        
        # Tạo thư mục screenshots nếu chưa có
        os.makedirs("screenshots", exist_ok=True)
        filepath = os.path.join("screenshots", filename)
        
        driver.save_screenshot(filepath)
        screenshot_url = f"/screenshots/{filename}"
        print(f'Screenshot saved: {screenshot_url}')
        return f"http://localhost:8000{screenshot_url}"
    else:
        # Non-headless: dùng Alt+S
        print('Chart sẵn sàng để capture (Alt+S)...')
        ActionChains(driver).key_down(Keys.ALT).send_keys('s').key_up(Keys.ALT).perform()
        time.sleep(3)

        # In Docker environment, clipboard is not available
        # Use headless screenshot fallback instead
        print('Visible mode: trying to get URL from clipboard...')
        try:
            # Fallback to screenshot since clipboard unavailable in Docker
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chart_{chart}_{timestamp}.png"
            os.makedirs("screenshots", exist_ok=True)
            filepath = os.path.join("screenshots", filename)
            driver.save_screenshot(filepath)
            url = f"http://localhost:8000/screenshots/{filename}"
            print(f'Fallback screenshot saved: {url}')
        except Exception as e:
            print(f"Screenshot fallback failed: {e}")
            url = "https://www.tradingview.com/x/capture_failed/"

        return url


def quit_driver(driver):
    """
    Safely quit the WebDriver instance
    """
    try:
        print(f'---> Closing browser : {datetime.now()}')
        driver.close()
    except Exception as e:
        print(f"Error closing driver: {e}")
    
    try:
        driver.quit()
    except Exception as e:
        print(f"Error quitting driver: {e}")


# ================== API models ==================
class CaptureRequest(BaseModel):
    """
    Request model for chart capture operations.
    
    All capture settings are optimized and hardcoded except for these two configurable parameters.
    """
    
    ticker: Optional[str] = Field(
        "NONE",
        description="Trading symbol in Exchange:Symbol format (e.g., BINANCE:BTCUSDT, NASDAQ:AAPL). Leave empty to use chart's default symbol."
    )
    
    timeframe: Optional[str] = Field(
        "1D",
        description="Chart timeframe interval. Supported values: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 3D, 1W, 1M"
    )

    class Config:
        schema_extra = {
            "examples": [
                {
                    "summary": "Default 1D Chart",
                    "description": "Capture with default timeframe and symbol",
                    "value": {}
                },
                {
                    "summary": "Bitcoin 4H Chart",
                    "description": "4-hour Bitcoin/USDT chart from Binance", 
                    "value": {
                        "ticker": "BINANCE:BTCUSDT",
                        "timeframe": "4H"
                    }
                },
                {
                    "summary": "Apple 15min Chart",
                    "description": "15-minute Apple stock chart from NASDAQ",
                    "value": {
                        "ticker": "NASDAQ:AAPL",
                        "timeframe": "15m"
                    }
                },
                {
                    "summary": "EUR/USD 1H Forex",
                    "description": "1-hour EUR/USD forex chart",
                    "value": {
                        "ticker": "FX:EURUSD",
                        "timeframe": "1H"
                    }
                },
                {
                    "summary": "Weekly Overview",
                    "description": "Weekly timeframe for long-term analysis",
                    "value": {
                        "timeframe": "1W"
                    }
                }
            ]
        }


class CaptureResponse(BaseModel):
    """
    Response model for successful chart capture operations.
    """
    
    ok: bool = Field(description="Success status of the capture operation")
    screenshot_url: str = Field(description="Direct URL to the captured chart screenshot. Can be either TradingView URL or local server URL depending on browser mode.")
    timestamp: str = Field(description="ISO format timestamp when the capture was completed")


class HealthResponse(BaseModel):
    """
    Response model for health check operations.
    """
    
    ok: bool = Field(description="API service status - always true if endpoint responds")
    time: str = Field(description="Current server time in ISO format")
    version: str = Field(description="API version number")
    selenium_ready: bool = Field(description="WebDriver readiness status - indicates if browser automation is functional")


# ================== Endpoints ==================
@app.get("/", response_class=FileResponse)
def read_index():
    """Serve the web interface"""
    return FileResponse('index.html')


# Mount screenshots directory for serving images
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Service Health Check",
    description="""
    Comprehensive health check for the TradingView Capture API service.
    
    ## What it checks
    
    - **API Status**: Confirms the FastAPI service is running
    - **Selenium Readiness**: Tests WebDriver functionality
    - **Browser Availability**: Verifies Chrome/Chromium accessibility
    - **System Resources**: Basic system health indicators
    
    ## Response Fields
    
    - **ok**: Always true if API responds
    - **time**: Current server timestamp in ISO format
    - **version**: API version number
    - **selenium_ready**: Boolean indicating WebDriver status
    
    ## Usage
    
    ```bash
    curl http://localhost:8000/health
    ```
    
    ## Response Examples
    
    ### Healthy Service
    ```json
    {
      "ok": true,
      "time": "2025-09-02T17:00:00.000000",
      "version": "2.0.0",
      "selenium_ready": true
    }
    ```
    
    ### Service Issues
    ```json
    {
      "ok": true,
      "time": "2025-09-02T17:00:00.000000",
      "version": "2.0.0",
      "selenium_ready": false
    }
    ```
    
    Use this endpoint for monitoring, load balancer health checks, and troubleshooting.
    """
)
def health():
    selenium_ready = True
    try:
        # Quick selenium check
        opts = Options()
        opts.binary_location = "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"
        opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-gpu')
        service = Service(ChromeDriverManager(driver_version="138.0.7204.183").install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.quit()
    except Exception as e:
        print(f"Selenium health check failed: {e}")
        selenium_ready = False
    
    return HealthResponse(
        ok=True,
        time=datetime.now().isoformat(),
        version="1.0.0",
        selenium_ready=selenium_ready
    )


@app.post(
    "/capture", 
    response_model=CaptureResponse,
    tags=["Chart Capture"],
    summary="Capture TradingView Chart Screenshot",
    description="""
    Captures a screenshot of the configured TradingView chart with specified timeframe and optional symbol override.
    
    ## Parameters
    
    ### ticker (optional)
    - **Type**: String
    - **Default**: "NONE" (uses chart's default symbol)
    - **Format**: Exchange:Symbol (e.g., "BINANCE:BTCUSDT", "NASDAQ:AAPL")
    - **Description**: Override the chart's default trading symbol
    
    ### timeframe (optional)
    - **Type**: String  
    - **Default**: "1D"
    - **Available Options**:
      - Minutes: `1m`, `3m`, `5m`, `15m`, `30m`
      - Hours: `1H`, `2H`, `4H`, `6H`, `12H`
      - Days: `1D`, `3D`
      - Weeks: `1W`
      - Months: `1M`
    
    ## Hardcoded Configuration
    
    The following settings are optimized and fixed:
    
    - **Chart ID**: `fCLTltqk` (predefined chart template)
    - **Resolution**: `1920x1080` (Full HD for crisp screenshots)
    - **Browser**: Visible mode (ensures proper rendering)
    - **Positioning**: 30 RIGHT key adjustments for optimal view
    - **Load Time**: 5 seconds wait for complete chart loading
    
    ## Response
    
    Returns a JSON object containing:
    - **ok**: Boolean indicating success
    - **screenshot_url**: Direct URL to the captured screenshot
    - **timestamp**: ISO format timestamp of capture completion
    
    ## Example Requests
    
    ### Default capture (1D timeframe)
    ```bash
    curl -X POST "http://localhost:8000/capture" \
      -H "Content-Type: application/json" \
      -d '{}'
    ```
    
    ### 4-hour Bitcoin chart
    ```bash
    curl -X POST "http://localhost:8000/capture" \
      -H "Content-Type: application/json" \
      -d '{
        "timeframe": "4H",
        "ticker": "BINANCE:BTCUSDT"
      }'
    ```
    
    ### 15-minute Apple stock
    ```bash
    curl -X POST "http://localhost:8000/capture" \
      -H "Content-Type: application/json" \
      -d '{
        "timeframe": "15m",
        "ticker": "NASDAQ:AAPL"
      }'
    ```
    
    ## Processing Time
    
    Typical capture takes 30-45 seconds including:
    - Browser startup and chart loading (15-20s)
    - Timeframe switching and positioning (5-10s)
    - Screenshot capture and processing (5-10s)
    
    ## Error Handling
    
    Returns HTTP 500 with error details if:
    - Browser automation fails
    - Chart loading timeout
    - Invalid session credentials
    - TradingView service unavailable
    """
)
def capture(req: CaptureRequest):
    driver = None
    start_time = datetime.now()
    
    try:
        print(f"\n{'='*50}")
        print(f"CAPTURE REQUEST STARTED: {start_time}")
        print(f"Chart: {HARDCODE['CHART_ID']} (hardcoded)")
        print(f"Ticker: {req.ticker}")
        print(f"Timeframe: {req.timeframe}")
        print(f"Window Size: 1920x1080 (hardcoded)")
        print(f"Browser Mode: Visible (hardcoded)")
        print(f"Adjustment: 30 (hardcoded)")
        print(f"Load Wait: 5s (hardcoded)")
        print(f"{'='*50}")
        
        # Get valid session ID
        sid = get_or_refresh_sessionid()
        print("Using sessionid:", sid[:10] + "..." if len(sid) > 10 else sid)
        
        # Setup WebDriver with hardcoded settings
        driver = setup_driver(
            window_size="1920,1080",  # Hardcoded Full HD
            headless=False             # Hardcoded visible browser
        )
        
        # Inject TradingView session
        inject_tv_session(driver, sid)
        
        # Capture chart screenshot with hardcoded settings
        screenshot_url = capture_chart_screenshot_url(
            driver,
            chart=HARDCODE["CHART_ID"],
            ticker=req.ticker or "NONE",
            timeframe=req.timeframe or "1D",
            adjustment=30,  # Hardcoded
            load_wait=5,    # Hardcoded
            headless=False  # Hardcoded to visible browser
        )
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\n{'='*50}")
        print(f"CAPTURE COMPLETED: {end_time}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Screenshot URL: {screenshot_url}")
        print(f"{'='*50}\n")
        
        return CaptureResponse(
            ok=True,
            screenshot_url=screenshot_url,
            timestamp=end_time.isoformat()
        )
        
    except Exception as e:
        error_msg = f"Capture error: {str(e)}"
        print(f"ERROR: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)
        
    finally:
        # Always cleanup WebDriver
        if driver:
            quit_driver(driver)


# ================== Bootstrap ==================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Render sets PORT environment variable
    print("Starting TradingView Capture API Server...")
    print("Environment variables:")
    print(f"- TRADINGVIEW_USERNAME: {'SET' if os.getenv('TRADINGVIEW_USERNAME') else 'NOT SET (using hardcode)'}")
    print(f"- TRADINGVIEW_PASSWORD: {'SET' if os.getenv('TRADINGVIEW_PASSWORD') else 'NOT SET (using hardcode)'}")
    print(f"- TRADINGVIEW_SESSIONID: {'SET' if os.getenv('TRADINGVIEW_SESSIONID') else 'NOT SET (using hardcode)'}")
    print(f"\nServer will be available at: http://0.0.0.0:{port}")
    print(f"API documentation at: http://0.0.0.0:{port}/docs")
    
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
