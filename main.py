import M5
from M5 import *
import wcache
import time, json, requests
import math, ntptime, network
from machine import Pin
from hardware import I2C
from unit import ENVUnit
from esp32 import RMT
import asyncio
# ── config ──────────────────────────────────────
RGB_PIN    = 5
SCREEN_MAIN, SCREEN_DATA, SCREEN_WEATHER, SCREEN_FORECAST, SCREEN_SETTINGS = 0, 1, 2, 3, 4
SCREEN_COUNT = 5
NAV_H        = 28        

SENSOR_MS  = 5_000
GRAPH_MS   = 60_000      
WEATHER_MS = 30 * 60 * 1000
NTP_MS     = 24 * 60 * 60 * 1000
GRAPH_MAX  = 60
WEATHER_REFRESH_OPTIONS = [15, 30, 60]   

                       
C_BG     = 0x040810   
C_CARD   = 0x080E18   
C_GLASS  = 0x0E2540   
C_DARK   = 0x071320   
C_TOPBAR = 0x020508   
C_A1      = 0x0078D4   # accent blue
C_A2      = 0x00B4D8   # accent cyan

C_ICE1   = 0x62C8E8   
C_ICE2   = 0x9ADFF5   
C_FROST  = 0x3EB8DC   
C_SNOW   = 0xDCF2FF   

C_TXT    = 0xDCF2FF   
C_TXT2   = 0x3D6E8A   
C_SEP    = 0x0F2840   
NAV_GRAD = [
    0x010306, 0x010307, 0x010409, 0x01050A,
    0x02050B, 0x02060D, 0x02060F, 0x020710,
    0x030812, 0x030813, 0x030914, 0x030916,
    0x040A17, 0x040A19, 0x040B1A, 0x040C1C,
    0x050C1D, 0x050D1E, 0x050D20, 0x050E21,
    0x060E23, 0x060F24, 0x061025, 0x061027,
    0x071128, 0x07112A, 0x07122B, 0x07132C,
    0x08132E, 0x08142F, 0x081431, 0x081532,
    0x091533, 0x091635, 0x091736, 0x091738,
    0x09183A, 0x09183A, 0x09193C, 0x091A40,
]
BRIGHTNESS_LEVELS = [40, 120, 220]
SLEEP_OPTIONS     = [1, 2, 5, 0]   # 0 = off
WMO_CODES = {
    0: "Clear sky",    1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog",         48: "Icy fog",
    51: "Lt drizzle",  53: "Drizzle",     55: "Hvy drizzle",
    61: "Lt rain",     63: "Rain",        65: "Hvy rain",
    71: "Lt snow",     73: "Snow",        75: "Hvy snow",
    80: "Showers",     81: "Showers",     82: "Hvy showers",
    95: "Thunderstorm",
}

DAY_PARTS = [
    ("Morning", 8),
    ("Day",     14),
    ("Evening", 20),
    ("Night",   23),
]
NAV_ICON_PATHS = [
    "/flash/icons/ui/nav_main.png",
    "/flash/icons/ui/nav_data.png",
    "/flash/icons/ui/nav_weather.png",
    "/flash/icons/ui/nav_forecast.png",
    "/flash/icons/ui/nav_settings.png",
]
# ══════════════════════════════════════════════════════
                     #  global state
# ══════════════════════════════════════════════════════
_icons_mod      = None          # icons.py 
current_screen  = SCREEN_MAIN
is_sleeping     = False
last_touch_ms   = 0
last_sensor_ms  = 0
last_graph_ms   = 0
last_weather_ms = -(WEATHER_MS)   
last_ntp_ms     = 0

sensor_data     = {'temp': 0.0, 'humi': 0.0, 'press': 0.0, 'battery': 0}
outdoor_weather = None
archive_data    = None   # [{date, min, max, rain, wind}, ...]
wifi_screen    = 0      # 0=off, 1=list, 2=password
wifi_networks  = []     # [(ssid_str, rssi), ...]
wifi_selected  = None   # ssid 
wifi_password  = ""     
wifi_kb_shift  = False  # Shift
wifi_kb_nums   = False  # False=ABC, True=123
wifi_show_pass = False  
temp_history    = []
press_history = []
last_minute_ms = 0
cfg = {}
is_wifi_active = False   # True when connect_wifi()
is_fetching    = False   # True when fetch_weather()
_weather_saved_at = 0   
# ══════════════════════════════════════════════════════
                    #  cfg
# ══════════════════════════════════════════════════════
DEFAULT_CFG = {
    'wifi_ssid': '', 'wifi_pass': '',
    'brightness': 120, 'sleep_min': 2,
    'temp_unit': 'C', 'press_unit': 'hPa',
    'weather_lat': 0.0, 'weather_lon': 0.0,
    'weather_city': 'City', 'utc_offset': 0, 'sea_level_hpa': 1013.25, 'weather_refresh_min': 30,
}

def load_config():
    global cfg
    cfg = DEFAULT_CFG.copy()
    try:
        with open('/flash/config.json', 'r') as f:
            cfg.update(json.load(f))
    except:
        save_config()

def save_config():
    try:
        with open('/flash/config.json', 'w') as f:
            json.dump(cfg, f)
    except Exception as e:
        print("Config save error:", e)
        
# ── Init ─────────────────────────────────────
def init_hardware():
    M5.begin()
    M5.Lcd.setBrightness(0)   
    Widgets.setRotation(1)
    
    #I2C 
    i2c = I2C(0, scl=Pin(1), sda=Pin(2), freq=100000)
    sensor = ENVUnit(i2c=i2c, type=3)
    time.sleep_ms(500)
    #RMT for RGB
    rmt = RMT(0, pin=Pin(RGB_PIN), clock_div=8)
    
    return sensor, rmt

# ── RGB ───────────────────────────────────────────────
def ws2812_send_all(rmt, colors):
    buf = []
    for (r, g, b) in colors:
        for byte in (g, r, b):
          for i in range(7, -1, -1):
            if byte & (1 << i):
                buf += [8, 5]
            else:
                buf += [4, 9]
    rmt.write_pulses(buf, 1)
    time.sleep_us(60)
    
def rgb_pulse_animation(rmt):
  t = 0.0
  while t < 6.28 * 1:
    brightness = int((math.sin(t) + 1) * 127)
    r = int((math.sin(t) + 1) * 127)
    g = int((math.sin(t + 2.09) + 1) * 127)  
    b = int((math.sin(t + 4.19) + 1) * 127)  
    colors = [(r, g, b)] * 10
    ws2812_send_all(rmt, colors)
    time.sleep_ms(30)
    t += 0.1
  ws2812_send_all(rmt, [(0, 0, 0)] * 10)
  
# ══════════════════════════════════════════════════════
                         #  Time
# ══════════════════════════════════════════════════════
def get_local_time():
    return time.gmtime(time.time() + cfg.get('utc_offset', 0) * 3600)

def format_datetime():
    t = get_local_time()
    return "%02d.%02d.%04d" % (t[2], t[1], t[0]), "%02d:%02d" % (t[3], t[4])

# ══════════════════════════════════════════════════════
#  WI-FI + NTP + Weather
# ══════════════════════════════════════════════════════
async def connect_wifi(timeout_s=15):
    if not cfg.get('wifi_ssid'):
        return False
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True
    wlan.connect(cfg['wifi_ssid'], cfg['wifi_pass'])
    for _ in range(timeout_s):
        if wlan.isconnected():
            return True
        await asyncio.sleep(1)
    return False

def disconnect_wifi():
    try:
        network.WLAN(network.STA_IF).active(False)
    except:
        pass
def sync_ntp():
    try:
        ntptime.host = "pool.ntp.org"
        ntptime.settime()
        print("NTP OK")
        return True
    except Exception as e:
        print("NTP fail:", e)
        return False

def fetch_weather():
    global outdoor_weather, _weather_saved_at
    lat = cfg['weather_lat']
    lon = cfg['weather_lon']
    timezone = cfg.get('timezone', 'UTC').replace('/', '%2F')
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=%.4f&longitude=%.4f"
        "&current=temperature_2m,relative_humidity_2m,"
        "surface_pressure,weather_code"
        "&hourly=temperature_2m,weather_code,"
        "wind_speed_10m,precipitation_probability"
        "&daily=temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,wind_speed_10m_max"
        "&forecast_days=2"
        "&timezone=%s"
    ) % (lat, lon, timezone)

    try:
        r = requests.get(url, timeout=15)

        if r.status_code != 200:
            print("[weather] HTTP error:", r.status_code)
            r.close()
            return False  

        d = r.json()
        r.close()

        # ─────────────────────────
        cur = d['current']
        _, ts = format_datetime()
        
        # ── Hourly ──────────
        h = d['hourly']
        hourly = {
            'time':    h['time'][:48],
            'temp':    h['temperature_2m'][:48],
            'code':    h['weather_code'][:48],
            'wind':    h['wind_speed_10m'][:48],
            'precip':  h['precipitation_probability'][:48],
        }

        # ── Daily  ─────────────
        dd = d['daily']
        tomorrow = {
            'temp_max': dd['temperature_2m_max'][1],
            'temp_min': dd['temperature_2m_min'][1],
            'precip':   dd['precipitation_probability_max'][1],
            'wind':     dd['wind_speed_10m_max'][1],
        }

        outdoor_weather = {
            'temp':     cur['temperature_2m'],
            'humidity': cur['relative_humidity_2m'],
            'pressure': cur['surface_pressure'],
            'code':     cur['weather_code'],
            'desc':     WMO_CODES.get(cur['weather_code'], "Unknown"),
            'updated':  ts,
            'hourly':   hourly,
            'tomorrow': tomorrow,
        }

        print("Weather OK:", outdoor_weather['temp'], outdoor_weather['desc'])
        wcache.save(outdoor_weather)
        _weather_saved_at = time.time()
        return True

    except Exception as e:
        print("Weather fail:", e)
        return False
def fetch_archive():
    global archive_data
    t_now    = get_local_time()
    today_str = "%04d-%02d-%02d" % (t_now[0], t_now[1], t_now[2])

    # ── cache chekup ──
    cached = wcache.load_archive(today_str)
    if cached:
        archive_data = cached
        print("[archive] using cache")
        return True

    # ── date  ───────────────────
    now_ts     = time.time()
    t_yesterday  = time.gmtime(now_ts - 86400)
    t_3days_ago  = time.gmtime(now_ts - 3 * 86400)
    end_date   = "%04d-%02d-%02d" % (t_yesterday[0],  t_yesterday[1],  t_yesterday[2])
    start_date = "%04d-%02d-%02d" % (t_3days_ago[0],  t_3days_ago[1],  t_3days_ago[2])

    lat = cfg['weather_lat']
    lon = cfg['weather_lon']
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        "?latitude=%.4f&longitude=%.4f"
        "&start_date=%s&end_date=%s"
        "&daily=temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,wind_speed_10m_max"
    ) % (lat, lon, start_date, end_date)

    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print("[archive] HTTP error:", r.status_code)
            r.close()
            return False
        d = r.json()
        r.close()

        dd = d['daily']
        days = []
        for i in range(len(dd['time'])):
            days.append({
                'date':  dd['time'][i],              # 'YYYY-MM-DD'
                'max':   dd['temperature_2m_max'][i],
                'min':   dd['temperature_2m_min'][i],
                'rain':  dd['precipitation_sum'][i],
                'wind':  dd['wind_speed_10m_max'][i],
            })

        archive_data = days
        wcache.save_archive(days, today_str)
        print("[archive] OK, %d days fetched" % len(days))
        return True

    except Exception as e:
        print("[archive] fetch fail:", e)
        return False
                                      # WiFi
async def do_wifi_tasks(force_ntp=False):
    global last_ntp_ms, last_weather_ms
    global is_wifi_active, is_fetching
    is_wifi_active = True
    render()                      
    success = False
    
    if await connect_wifi():
        if force_ntp or time.ticks_diff(time.ticks_ms(), last_ntp_ms) >= NTP_MS:
            wlan = network.WLAN(network.STA_IF)
            print("[wifi] IP:", wlan.ifconfig()[0])
            sync_ntp()
            last_ntp_ms = time.ticks_ms()
        is_wifi_active = False
        is_fetching    = True
        render()                  
        if fetch_weather():       
            success = True
            fetch_archive() 
        last_weather_ms = time.ticks_ms()
        disconnect_wifi()
       
    is_wifi_active = False
    is_fetching    = False
    render()                      
    return success
def get_forecast_slots():
    
    t = get_local_time()
    current_hour = t[3]
    slots = []

    for name, target_h in DAY_PARTS:
        if target_h > current_hour:
            slots.append((name, target_h))

    for name, target_h in DAY_PARTS:
        if len(slots) >= 3:
            break
        slots.append((name + "+1", target_h + 24))

    return slots[:3]  
                        
def heat_index(temp_c, humidity):
    if temp_c < 27 or humidity < 40:
        return temp_c   
    t, h = temp_c, humidity
    hi = (-8.78469475556
          + 1.61139411    * t
          + 2.33854883889 * h
          - 0.14611605    * t * h
          - 0.012308094   * t ** 2
          - 0.016424828   * h ** 2
          + 0.002211732   * t ** 2 * h
          + 0.00072546    * t * h ** 2
          - 0.000003582   * t ** 2 * h ** 2)
    return hi
def get_pressure_trend():
    
    WINDOW = 15   
    if len(press_history) < WINDOW:
        return 'stable'          
    delta = press_history[-1] - press_history[-WINDOW]
    if   delta >  0.5: return 'rising'
    elif delta < -0.5: return 'falling'
    else:              return 'stable'
    
def altitude_from_pressure(pressure_hpa):
    """Висота над рівнем моря з тиску. sea_level з config."""
    sea = cfg.get('sea_level_hpa', 1013.25)
    return 44330.0 * (1.0 - (pressure_hpa / sea) ** (1.0 / 5.255))

                #  components
# ══════════════════════════════════════════════════════
def draw_topbar(canvas, date_str, time_str, title=None):
    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)
     # ───────────────────────
    if is_wifi_active:
        # WiFi topbar
        canvas.drawImage("/flash/icons/ui/wifi_16.png", 6, 8)

    elif is_fetching:
        # Refresh
        canvas.drawImage("/flash/icons/ui/refresh_16.png", 6, 8)

    else:
        age_ms = time.ticks_diff(time.ticks_ms(), last_sensor_ms)
        if age_ms < 200:
            dot_color = 0xA855F7
        elif age_ms < 500:
            dot_color = 0x6D28D9
        else:
            dot_color = C_GLASS
        canvas.fillCircle(14, 16, 4, dot_color)

    # ── Time Header ──────────────────────────
    canvas.setTextColor(C_TXT2)
    canvas.setTextSize(1)
    canvas.drawString(date_str, 26, 10)
    canvas.drawString(time_str, 258, 10)
    if title:
        canvas.setTextColor(C_A1)
        canvas.drawString(title, 160 - len(title) * 3, 10)

def draw_nav_bar(canvas):
    y = 240 - NAV_H
    step_w = 160 // len(NAV_GRAD)
    for i, c in enumerate(NAV_GRAD):
        canvas.fillRect(i * step_w, y, step_w + 1, NAV_H, c)
    for i, c in enumerate(reversed(NAV_GRAD)):
        canvas.fillRect(160 + i * step_w, y, step_w + 1, NAV_H, c)

    canvas.drawLine(0, y,     320, y,     C_SEP)
    canvas.drawLine(0, y + 1, 320, y + 1, C_GLASS)

    zone_w = 320 // SCREEN_COUNT

    for i in range(SCREEN_COUNT):
        x  = i * zone_w
        cx = x + zone_w // 2
        cy = y + NAV_H // 2

        if i == current_screen:
            canvas.fillRect(x + 1, y + 2, zone_w - 2, NAV_H - 4, C_GLASS)
            canvas.drawRoundRect(x + 1, y + 2, zone_w - 2, NAV_H - 4, 3, C_ICE1)

        # 24×24 PNG
        canvas.drawImage(NAV_ICON_PATHS[i], cx - 12, cy - 12)

        if i > 0:
            canvas.drawLine(x, y + 4, x, y + NAV_H - 4, C_SEP)
# ══════════════════════════════════════════════════════
#  Helper stripe
# ══════════════════════════════════════════════════════
def fill_glass_rect(canvas, x, y, w, h, r, base_color, border=6):
    
    for sy in range(y, y + border, 2):
        canvas.drawLine(x + r, sy, x + w - r, sy, base_color)
    
    for sy in range(y + h - border, y + h, 2):
        canvas.drawLine(x + r, sy, x + w - r, sy, base_color)
    
    for sx in range(x, x + border, 2):
        canvas.drawLine(sx, y + r, sx, y + h - r, base_color)
    
    for sx in range(x + w - border, x + w, 2):
        canvas.drawLine(sx, y + r, sx, y + h - r, base_color)
# ══════════════════════════════════════════════════════
#  Screen 0 - main
# ══════════════════════════════════════════════════════
def draw_main_screen():
    d, t = format_datetime()
    temp    = sensor_data['temp']
    humi    = sensor_data['humi']
    press   = sensor_data['press']
    battery = sensor_data['battery']

    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    # ── bg ─────────────
    canvas.drawImage("/flash/bg/bg_stars.bmp", 0, 0)

    # ── TOP BAR ──────────────────────────────────────
    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)

    canvas.fillCircle(14, 16, 5, C_GLASS)
    canvas.fillCircle(14, 16, 3, C_ICE1)
    canvas.setTextColor(C_TXT2, C_TOPBAR)
    canvas.setTextSize(1)
    canvas.drawString(d, 26, 10)
    canvas.drawString(t, 258, 10)

    # ── temp ─────────
    canvas.drawRoundRect(8, 38, 138, 90, 10, C_ICE1)
    canvas.fillRoundRect(8, 38, 138, 90, 12, C_CARD)
    canvas.fillRect(8, 48, 3, 72, C_ICE1)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Temperature", 18, 45)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(3)
    t_val = temp if cfg['temp_unit'] == 'C' else temp * 9/5 + 32
    canvas.drawString("%.1f" % t_val, 18, 62)
    canvas.setTextSize(1)
    canvas.setTextColor(C_ICE1, C_DARK)
    canvas.drawString(cfg['temp_unit'], 110, 70)
     

    # ── temp: png ───
    canvas.drawImage("/flash/icons/ui/thermometer.png", 102, 52)

    # ── power ───────────────────────────────────────
    canvas.drawRoundRect(210, 38, 102, 90, 10, C_ICE2)
    canvas.fillRoundRect(210, 38, 102, 90, 12, C_CARD)

    canvas.drawImage("/flash/icons/ui/battery_shell.png", 213, 33)
    fw = max(2, int(38 * battery / 100))
    bc = 0x4AB3D6 if battery > 50 else (0xF5C842 if battery > 20 else 0xE84040)
    canvas.fillRoundRect(224, 58, fw, 14, 2, bc)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Battery", 220, 45)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(2)
    canvas.drawString("%d%%" % battery, 220, 86)

    # ── hum ─────────────────────────────────────
    canvas.drawRoundRect(8, 136, 152, 64, 10, C_FROST)
    canvas.fillRect(8, 146, 3, 48, C_FROST)
    canvas.fillRoundRect(8, 136, 152, 64, 12, C_CARD)
    canvas.drawImage("/flash/icons/ui/humidity.png", 100, 138)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Humidity", 18, 143)
    canvas.fillRoundRect(14, 156, 52, 23, 5, C_CARD)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(2)
    canvas.drawString("%d%%" % humi, 18, 162)

    # ── press ──────────────────────────────────────────
    p_val  = press if cfg['press_unit'] == 'hPa' else int(press * 0.75006)
    p_unit = cfg['press_unit']
    canvas.drawRoundRect(168, 136, 144, 64, 10, C_FROST)
    canvas.fillRoundRect(168, 136, 144, 64, 12, C_CARD)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Pressure", 178, 143)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(2)
    canvas.drawString("%d" % p_val, 178, 162)
    canvas.setTextSize(1)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString(p_unit, 178, 182)

    #  PNG
    canvas.drawImage("/flash/icons/ui/pressure.png", 250, 130)

    # ──  GLACIER  ─────────────────────────
    canvas.fillRect(0, 237, 320, 3, C_ICE1)
    canvas.fillRect(0, 236, 80, 1, C_ICE2)  

    draw_nav_bar(canvas)
    canvas.push(0, 0)
    canvas.delete()
# ══════════════════════════════════════════════════════
#  Screen 1 - G
# ══════════════════════════════════════════════════════
def draw_data_screen():
    d, t = format_datetime()
    temp  = sensor_data['temp']
    humi  = sensor_data['humi']
    press = sensor_data['press']

    hi  = heat_index(temp, humi)
    alt = altitude_from_pressure(press)

    canvas = M5.Lcd.newCanvas(320, 240, 16, True)

    # ── bg + stripe  ────────────────────────────
    canvas.fillRect(0, 0, 320, 240, C_BG)
    for y in range(32, 212, 3):
        canvas.drawLine(0, y, 320, y, 0x050C14)   

    # vignette
    canvas.fillRect(0,   0, 10, 240, 0x020508)
    canvas.fillRect(310, 0, 10, 240, 0x020508)

    draw_topbar(canvas, d, t, title="Data")

    # ── Feels like — glass ───────────────────
    canvas.fillRoundRect(8, 36, 148, 70, 12, C_CARD)
    # inner highlight top (glass)
    canvas.drawLine(12, 38, 152, 38, 0x1A3A5C)     
    canvas.drawLine(12, 39, 152, 39, 0x0F2840)     
    # inner shadow 
    canvas.drawLine(12, 104, 152, 104, 0x050C14)
    # top border cyan
    canvas.fillRect(82, 36, 74, 2, C_DARK)
    
    canvas.setTextSize(1)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("Feels like", 18, 42)

    canvas.setTextColor(C_TXT, C_CARD)
    canvas.setTextSize(2)
    canvas.drawString("%.1f" % hi, 18, 58)
    canvas.setTextSize(1)
    canvas.setTextColor(C_ICE1, C_CARD)
    canvas.drawString("C", 18 + len("%.1f" % hi) * 12 + 2, 64)

    canvas.setTextColor(C_TXT2, C_CARD)
    if temp < 27 or humi < 40:
        canvas.drawString("= actual", 18, 82)
    else:
        diff = hi - temp
        dc = 0xFF6B6B if diff > 2 else (0xFFCA28 if diff > 0 else C_ICE1)
        canvas.setTextColor(dc, C_CARD)
        canvas.drawString("%+.1f vs real" % diff, 18, 82)

    # ── Altitude — glass ─────────────────────
    canvas.fillRoundRect(164, 36, 148, 70, 12, C_CARD)
    # inner highlight
    canvas.drawLine(168, 38, 308, 38, 0x1A3A5C)
    canvas.drawLine(168, 39, 308, 39, 0x0F2840)
    # inner shadow 
    canvas.drawLine(168, 104, 308, 104, 0x050C14)
    canvas.fillRect(164, 36, 74, 2, C_DARK)

    canvas.drawImage("/flash/icons/ui/altitude_48.png", 256, 38)

    canvas.setTextSize(1)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("Altitude", 174, 42)

    canvas.setTextColor(C_TXT, C_CARD)
    canvas.setTextSize(2)
    canvas.drawString("%.0f" % alt, 174, 58)
    canvas.setTextSize(1)
    canvas.setTextColor(C_FROST, C_CARD)
    canvas.drawString("m", 174 + len("%.0f" % alt) * 12 + 2, 64)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("P: %.0f hPa" % press, 174, 82)
    trend = get_pressure_trend()
    canvas.drawImage("/flash/icons/ui/pressure_%s_24.png" % trend, 228, 77)

    # ── ARCHIVE CARD ──────────────────────────────────
    AX = 8
    AY = 114
    AW = 304
    AH = 96

    # ── ARCHIVE CARD — glass ─────────────────────────
    canvas.fillRoundRect(AX, AY, AW, AH, 12, C_CARD)
    # inner highlight
    canvas.drawLine(AX+4, AY+2, AX+AW-4, AY+2, 0x1A3A5C)
    canvas.drawLine(AX+4, AY+3, AX+AW-4, AY+3, 0x0F2840)
    # inner shadow 
    canvas.drawLine(AX+4, AY+AH-2, AX+AW-4, AY+AH-2, 0x050C14)
    # top border cyan
    canvas.fillRect(AX,           AY, AW // 2, 2, C_DARK)
    canvas.fillRect(AX + AW // 2, AY, AW // 2, 2, C_DARK)

    # ── header ─────────────────────────────────────
    canvas.setTextSize(1)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("3-day history", AX + 10, AY + 9)
    canvas.setTextColor(0x60A8D0, C_CARD)
    canvas.drawString("precip",      AX + 102, AY + 9)
    canvas.setTextColor(0x8080C0, C_CARD)
    canvas.drawString("wind(km/h)",  AX + 146, AY + 9)
    canvas.setTextColor(C_ICE2, C_CARD)
    canvas.drawString("min",         AX + 212, AY + 9)
    canvas.setTextColor(0xFF6B6B, C_CARD)
    canvas.drawString("max",         AX + 262, AY + 9)

    canvas.drawLine(AX + 10, AY + 18, AX + AW - 10, AY + 18, C_SEP)

    # ── helper ────────────────────────────────────────
    def rain_label(mm):
        if mm is None or mm == 0.0: return "dry"
        if mm < 1.0:                return "trace"
        if mm < 5.0:                return "light"
        if mm < 15.0:               return "mod."
        return                             "heavy"

    DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

    if archive_data and len(archive_data) >= 3:
        days = archive_data[-3:]

        for idx, day in enumerate(days):
            row_y = AY + 21 + idx * 19

            ds = day['date']
            yr, mo, dy = int(ds[0:4]), int(ds[5:7]), int(ds[8:10])
            ts = time.mktime((yr, mo, dy, 12, 0, 0, 0, 0))
            wd = time.gmtime(ts)[6]
            day_label = "%s %02d" % (DAY_NAMES[wd], dy)

            canvas.setTextSize(1)
            canvas.setTextColor(C_TXT2, C_CARD)
            canvas.drawString(day_label, AX + 10, row_y + 8)

            rl = rain_label(day.get('rain'))
            rc = C_TXT2 if rl == "dry" else 0x60A8D0
            canvas.setTextColor(rc, C_CARD)
            canvas.drawString(rl, AX + 102, row_y + 8)

            canvas.setTextColor(0x8080C0, C_CARD)
            canvas.drawString("%d" % int(day.get('wind') or 0), AX + 163, row_y + 8)

            canvas.setTextColor(C_ICE2, C_CARD)
            canvas.drawString("%.1f" % day['min'], AX + 207, row_y + 8)
            canvas.setTextColor(0xFF6B6B, C_CARD)
            canvas.drawString("%.1f" % day['max'], AX + 259, row_y + 8)

    else:
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.setTextSize(1)
        canvas.drawString("History: waiting for WiFi...", AX + 20, AY + 50)

    draw_nav_bar(canvas)
    canvas.push(0, 0)
    canvas.delete()


# ══════════════════════════════════════════════════════
#  Sceen 2 - W
# ══════════════════════════════════════════════════════
def draw_weather_icon(canvas, code, cx, cy):
    if code == 0:                              # ☀ sun
        canvas.fillCircle(cx, cy, 14, 0xFFB300)
        for a in range(0, 360, 45):
            rad = math.radians(a)
            x1  = cx + int(18 * math.cos(rad))
            y1  = cy + int(18 * math.sin(rad))
            x2  = cx + int(25 * math.cos(rad))
            y2  = cy + int(25 * math.sin(rad))
            canvas.drawLine(x1, y1, x2, y2, 0xFFB300)
    elif code in (1, 2, 3):                    # ⛅ cloud
        if code == 1:
            canvas.fillCircle(cx + 12, cy - 12, 10, 0xFFB300)
        canvas.fillCircle(cx - 8, cy + 4, 12, 0x4A6080)
        canvas.fillCircle(cx + 5, cy + 4, 14, 0x5A7090)
        canvas.fillCircle(cx,     cy - 4, 11, 0x6A8090)
    elif code in (61, 63, 65, 80, 81, 82):    # 🌧 rain
        canvas.fillCircle(cx,     cy - 4, 11, 0x4A6080)
        canvas.fillCircle(cx - 9, cy + 2, 9,  0x4A6080)
        canvas.fillCircle(cx + 9, cy + 2, 9,  0x4A6080)
        for dx in (-10, 0, 10):
            canvas.drawLine(cx+dx, cy+14, cx+dx-3, cy+24, C_A2)
    elif code in (71, 73, 75):                 # ❄ snow
        canvas.fillCircle(cx, cy - 4, 11, 0x8090A0)
        for dx in (-10, 0, 10):
            canvas.fillCircle(cx + dx, cy + 18, 3, 0xDCE6F5)
    elif code >= 95:                           # ⛈ tr
        canvas.fillCircle(cx, cy - 4, 13, 0x303050)
        canvas.fillTriangle(cx-6, cy+10, cx+10, cy+10, cx, cy+24, 0xFFD700)
    else:                                      # 🌫 fog
        for dy in (0, 7, 14):
            canvas.drawLine(cx-20, cy+dy, cx+20, cy+dy, 0x5A7090)
                            # stripple
def draw_stipple_rect(canvas, x, y, w, h, color):
    for i in range(w):
        if i % 2 == 0:
            canvas.fillRect(x + i, y,         1, 1, color)
            canvas.fillRect(x + i, y + h - 1, 1, 1, color)
    for i in range(h):
        if i % 2 == 0:
            canvas.fillRect(x,         y + i, 1, 1, color)
            canvas.fillRect(x + w - 1, y + i, 1, 1, color)
def draw_weather_screen():
    d, t = format_datetime()
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240 - NAV_H, C_BG)

    # gradient
    for i, c in enumerate([0x040810, 0x060C18, 0x081220, 0x091828]):
        canvas.fillRect(0, i * 55, 320, 55, c)

    city = cfg.get('weather_city', 'City')
    draw_topbar(canvas, d, t, title=city)

    if outdoor_weather:
       ow = outdoor_weather

       canvas.fillRoundRect(8, 36, 304, 80, 8, C_CARD)
       canvas.drawRoundRect(8, 36, 304, 80, 8, C_SEP)
       draw_stipple_rect(canvas, 9, 37, 302, 78, C_GLASS)
       # Top highlight
       canvas.drawLine(10, 37, 310, 37, C_GLASS)
       _wmo_code = ow['code']
       _is_day   = (6 <= get_local_time()[3] < 21)

       canvas.setTextColor(C_TXT2, C_CARD)
       canvas.setTextSize(1)
       canvas.drawString("Outdoor", 18, 42)

       canvas.setTextColor(C_TXT, C_CARD)
       canvas.setTextSize(3)
       canvas.drawString("%.1f" % ow['temp'], 18, 56)
       canvas.setTextSize(1)
       canvas.setTextColor(C_ICE1, C_CARD)
       canvas.drawString("C", 100, 64)

       canvas.setTextColor(C_TXT2, C_CARD)
       canvas.setTextSize(1)
       canvas.drawString(ow['desc'], 18, 96)

       # ── HUMIDITY + PRESSURE ───────────────────────
       canvas.fillRoundRect(8, 122, 140, 38, 8, C_CARD)
       canvas.drawRoundRect(8, 122, 140, 38, 8, C_SEP)
       draw_stipple_rect(canvas, 9, 123, 138, 36, C_GLASS)

       canvas.fillRoundRect(154, 122, 158, 38, 8, C_CARD)
       canvas.drawRoundRect(154, 122, 158, 38, 8, C_SEP)
       draw_stipple_rect(canvas, 155, 123, 156, 36, C_GLASS)

       canvas.setTextColor(C_TXT2, C_CARD)
       canvas.setTextSize(1)
       canvas.drawString("Humidity", 18, 128)
       canvas.drawString("Pressure", 164, 128)
       canvas.setTextColor(C_TXT, C_CARD)
       canvas.setTextSize(2)
       canvas.drawString("%d%%" % ow['humidity'], 18, 140)
       canvas.drawString("%d hPa" % ow['pressure'], 164, 140)

       # ── INDOOR vs OUTDOOR ─────────────────────────
       canvas.fillRect(8, 166, 304, 1, C_SEP)
       canvas.setTextColor(C_TXT2, C_BG)
       canvas.setTextSize(1)
       canvas.drawString("Indoor vs Outdoor", 100, 170)

       diff = sensor_data['temp'] - ow['temp']
       dc   = 0x00E676 if diff > 0 else 0xFF5252
       canvas.setTextColor(C_TXT2, C_BG)
       canvas.drawString("In: %.1f C" % sensor_data['temp'], 18, 183)
       canvas.drawString("Out: %.1f C" % ow['temp'], 130, 183)
       canvas.setTextColor(dc, C_BG)
       canvas.drawString("Diff: %+.1f C" % diff, 232, 183)

       if wcache.is_stale(_weather_saved_at):
           # Amber 
           canvas.setTextColor(0xFF8C42, C_BG)
           canvas.drawString("Data: " + wcache.age_str(_weather_saved_at) + " old", 140, 200)
       else:
           canvas.setTextColor(C_TXT2, C_BG)
           canvas.drawString("Updated: " + wcache.age_str(_weather_saved_at), 185, 200)
    if outdoor_weather and _icons_mod is not None:
        _is_day   = (6 <= get_local_time()[3] < 21)
        icon_name = _icons_mod.wmo_to_icon(_wmo_code, _is_day)
        icon_path = "/flash/icons/" + _icons_mod.ICON_FILES.get(icon_name, "")
        canvas.drawImage(icon_path, 240, 42)  

    draw_nav_bar(canvas)
    canvas.push(0, 0)   
    canvas.delete()
    
# ══════════════════════════════════════════════════════
#  Sreen - 3 - F
# ══════════════════════════════════════════════════════
def draw_forecast_screen():
    d, t = format_datetime()
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)

    grad = [0x040810, 0x050A14, 0x060C18, 0x07101C,
            0x081220, 0x091424, 0x091828, 0x0A1C2C]
    for i, c in enumerate(grad):
        canvas.fillRect(0, i * 30, 320, 30, c)

    draw_topbar(canvas, d, t, title="Forecast")

    if not outdoor_weather or 'hourly' not in outdoor_weather:
        canvas.setTextColor(C_TXT2, C_BG)
        canvas.setTextSize(1)
        canvas.drawString("No forecast data yet.", 88, 100)
        canvas.drawString("Check WiFi in Settings.", 83, 116)
        draw_nav_bar(canvas)
        canvas.push(0, 0)
        canvas.delete()
        return

    slots   = get_forecast_slots()
    hourly  = outdoor_weather['hourly']
    tomorrow = outdoor_weather['tomorrow']

    CARD_W = 100
    CARD_H = 140
    CARD_Y = 36
    CARD_X = [6, 110, 214]

    for col, (name, target_h) in enumerate(slots):
        idx = min(target_h, 47)
        temp   = hourly['temp'][idx]   if idx < len(hourly['temp'])   else 0
        code   = hourly['code'][idx]   if idx < len(hourly['code'])   else 0
        wind   = hourly['wind'][idx]   if idx < len(hourly['wind'])   else 0
        precip = hourly['precip'][idx] if idx < len(hourly['precip']) else 0

        x = CARD_X[col]

        canvas.fillRoundRect(x, CARD_Y, CARD_W, CARD_H, 8, C_CARD)
        canvas.drawRoundRect(x, CARD_Y, CARD_W, CARD_H, 8, C_ICE1)
        # Depth tricks
        canvas.drawLine(x+1, CARD_Y+1, x+CARD_W-1, CARD_Y+1, C_GLASS)
        canvas.drawLine(x+1, CARD_Y+CARD_H-1, x+CARD_W-1, CARD_Y+CARD_H-1, C_DARK)

        cx = x + CARD_W // 2

        canvas.setTextColor(C_ICE1, C_CARD)
        canvas.setTextSize(1)
        lbl = name.replace("+1", "†")   # † 
        canvas.drawString(lbl, x + (CARD_W - len(lbl)*6)//2, CARD_Y + 6)

        hour_str = "%02d:00" % (target_h % 24)
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString(hour_str, x + (CARD_W - len(hour_str)*6)//2, CARD_Y + 17)

        canvas.drawLine(x+8, CARD_Y+28, x+CARD_W-8, CARD_Y+28, C_SEP)

        draw_weather_icon_small(canvas, code, cx, CARD_Y + 52)

        canvas.setTextColor(C_TXT, C_CARD)
        canvas.setTextSize(2)
        t_str = "%.0f" % temp
        canvas.drawString(t_str, x + (CARD_W - len(t_str)*12)//2, CARD_Y + 80)
        canvas.setTextSize(1)
        canvas.setTextColor(C_ICE1, C_CARD)
        canvas.drawString("C", x + (CARD_W + len(t_str)*12)//2 + 2, CARD_Y + 86)
        canvas.drawLine(x+8, CARD_Y+100, x+CARD_W-8, CARD_Y+100, C_SEP)

        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.setTextSize(1)
        wind_str = "%.0f km/h" % wind
        canvas.drawString(wind_str, x + (CARD_W - len(wind_str)*6)//2, CARD_Y + 106)

        if precip >= 70:
            pc = 0x4FC3F7   
        elif precip >= 30:
            pc = 0x81D4FA   
        else:
            pc = C_TXT2     

        canvas.setTextColor(pc, C_CARD)
        precip_str = "%d%%" % precip
        canvas.drawString(precip_str + " rain", x + (CARD_W - (len(precip_str)+5)*6)//2, CARD_Y + 120)

    # ── Tw ────────────────────────────────
    TY = CARD_Y + CARD_H + 4   # y = 184

    canvas.fillRoundRect(6, TY, 308, 24, 6, C_CARD)
    canvas.drawRoundRect(6, TY, 308, 24, 6, C_GLASS)
    canvas.drawLine(7, TY+1, 313, TY+1, C_GLASS)   # top highlight

    canvas.setTextColor(C_ICE1, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Tomorrow:", 14, TY + 8)

    canvas.setTextColor(C_TXT, C_CARD)
    t_range = "%.0f-%.0f C" % (tomorrow['temp_min'], tomorrow['temp_max'])
    canvas.drawString(t_range, 80, TY + 8)

    tp = tomorrow['precip']
    if tp >= 70:
        tc = 0x4FC3F7
    elif tp >= 30:
        tc = 0x81D4FA
    else:
        tc = C_TXT2
    canvas.setTextColor(tc, C_CARD)
    canvas.drawString("%d%% rain" % tp, 175, TY + 8)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("%.0f km/h" % tomorrow['wind'], 252, TY + 8)

    draw_nav_bar(canvas)
    canvas.push(0, 0)
    canvas.delete()
# ══════════════════════════════════════════════════════
#  Screen 4 - Setup
# ══════════════════════════════════════════════════════
ROW_H     = 28
ROW_START = 36

def settings_row_y(row):
    return ROW_START + row * ROW_H

def draw_settings_screen():
    _, t = format_datetime()
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240 - NAV_H, C_BG)

    draw_topbar(canvas, "", t, title="Settings")

    def btn(cx, cy, w, h, label, active):
        col = C_ICE1 if active else C_DARK
        tc  = C_TXT  if active else C_TXT2
        canvas.fillRoundRect(cx, cy, w, h, 5, col)
        canvas.setTextColor(tc, col)
        canvas.setTextSize(1)
        canvas.drawString(label, cx + (w - len(label)*6)//2, cy + (h - 8)//2)

    y = settings_row_y(0)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Brightness", 18, y + 13)
    for i, (lvl, lbl) in enumerate(zip(BRIGHTNESS_LEVELS, ["Low","Mid","Hi"])):
        btn(170 + i * 48, y + 6, 42, 20, lbl, lvl == cfg['brightness'])

    y = settings_row_y(1)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Sleep timer", 18, y + 13)
    for i, (opt, lbl) in enumerate(zip(SLEEP_OPTIONS, ["1m","2m","5m","Off"])):
        btn(142 + i * 44, y + 6, 38, 20, lbl, opt == cfg['sleep_min'])

    y = settings_row_y(2)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Temperature unit", 18, y + 13)
    for i, u in enumerate(['C', 'F']):
        btn(220 + i * 52, y + 6, 44, 20, u, cfg['temp_unit'] == u)

    y = settings_row_y(3)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Weather refresh", 18, y + 13)
    for i, opt in enumerate(WEATHER_REFRESH_OPTIONS):
        lbl = "%dm" % opt
        btn(170 + i * 52, y + 6, 44, 20, lbl,
            opt == cfg.get('weather_refresh_min', 30))

    y = settings_row_y(4)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Sea level hPa", 18, y + 13)
    sea = cfg.get('sea_level_hpa', 1013.25)
    btn(190, y + 4, 28, 20, " -", False)
    canvas.fillRoundRect(222, y + 4, 62, 20, 4, C_GLASS)
    canvas.setTextColor(C_TXT, C_GLASS)
    canvas.drawString("%.1f" % sea, 228, y + 10)
    btn(288, y + 4, 24, 20, "+", False)  # ← +/-  0.5 hPa

    # Connectivity: WiFi + NTP 
    y = settings_row_y(5)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Connectivity", 18, y + 13)
    # SSID or "not set"
    ssid_short = cfg.get('wifi_ssid', '')[:14] or 'not set'
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString(ssid_short, 110, y + 13)
    btn(222, y + 4, 36, 20, "WiFi", False)
    btn(262, y + 4, 44, 20, "NTP", False)

    draw_nav_bar(canvas)
    canvas.push(0, 0)
    canvas.delete()


async def handle_settings_touch(x, y):
    row = (y - ROW_START) // ROW_H
    changed = False

    if row == 0:   # Brightness
        for i, lvl in enumerate(BRIGHTNESS_LEVELS):
            bx = 170 + i * 48
            if bx <= x <= bx + 42:
                cfg['brightness'] = lvl
                M5.Lcd.setBrightness(lvl)
                changed = True

    elif row == 1: # Sleep timer
        for i, opt in enumerate(SLEEP_OPTIONS):
            bx = 142 + i * 44
            if bx <= x <= bx + 38:
                cfg['sleep_min'] = opt
                changed = True

    elif row == 2: # Temp unit
        if 220 <= x <= 264:
            cfg['temp_unit'] = 'C'; changed = True
        elif 272 <= x <= 316:
            cfg['temp_unit'] = 'F'; changed = True

    elif row == 3: # Weather refresh
        for i, opt in enumerate(WEATHER_REFRESH_OPTIONS):
            bx = 170 + i * 52
            if bx <= x <= bx + 44:
                cfg['weather_refresh_min'] = opt
                changed = True

    elif row == 4: # Sea level pressure
        if 190 <= x <= 218:              
            cfg['sea_level_hpa'] = round(cfg.get('sea_level_hpa', 1013.25) - 0.5, 1)
            changed = True
        elif 288 <= x <= 312:            
            cfg['sea_level_hpa'] = round(cfg.get('sea_level_hpa', 1013.25) + 0.5, 1)
            changed = True

    elif row == 5: # NTP Sync + WiFi settings
        if 222 <= x <= 258:          # WiFi Setup
            global wifi_screen, wifi_networks
            wifi_networks = []       
            wifi_screen = 1
            render()
        elif x >= 262:               # NTP Sync
            if await connect_wifi():
                sync_ntp()
                fetch_weather()
                disconnect_wifi()

    return changed

def draw_weather_icon_small(canvas, code, cx, cy):
    if code == 0:                              # ☀ 
        canvas.fillCircle(cx, cy, 8, 0xFFB300)
        canvas.fillCircle(cx-2, cy-2, 2, 0xFFD54F)  
        for a in range(0, 360, 60):
            rad = math.radians(a)
            x1 = cx + int(10 * math.cos(rad))
            y1 = cy + int(10 * math.sin(rad))
            x2 = cx + int(14 * math.cos(rad))
            y2 = cy + int(14 * math.sin(rad))
            canvas.drawLine(x1, y1, x2, y2, 0xFFB300)

    elif code in (1, 2, 3):                    # ⛅ 
        if code == 1:
            canvas.fillCircle(cx+8, cy-6, 6, 0xFFB300)
        canvas.fillCircle(cx-4, cy+2, 7, 0x4A6080)
        canvas.fillCircle(cx+4, cy+2, 8, 0x5A7090)
        canvas.fillCircle(cx,   cy-3, 6, 0x6A8090)

    elif code in (61, 63, 65, 80, 81, 82):    # 🌧 
        canvas.fillCircle(cx,   cy-3, 6, 0x4A6080)
        canvas.fillCircle(cx-6, cy+1, 5, 0x4A6080)
        canvas.fillCircle(cx+6, cy+1, 5, 0x4A6080)
        for dx in (-6, 0, 6):
            canvas.drawLine(cx+dx, cy+8, cx+dx-2, cy+14, C_A2)

    elif code in (71, 73, 75):                 # ❄ 
        canvas.fillCircle(cx, cy-3, 7, 0x8090A0)
        for dx in (-6, 0, 6):
            canvas.fillCircle(cx+dx, cy+10, 2, 0xDCE6F5)

    elif code >= 95:                           # ⛈ 
        canvas.fillCircle(cx, cy-3, 8, 0x303050)
        canvas.fillTriangle(cx-4, cy+6, cx+6, cy+6, cx, cy+16, 0xFFD700)

    else:                                      # 🌫 
        for dy in (0, 5, 10):
            canvas.drawLine(cx-12, cy+dy, cx+12, cy+dy, 0x5A7090)
# ══════════════════════════════════════════════════════
#  SPLASH
# ══════════════════════════════════════════════════════
def show_splash():
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240, C_BG)

    cx, cy = 160, 90

    canvas.fillCircle(cx, cy, 38, C_GLASS)
    canvas.fillCircle(cx, cy, 34, C_BG)
    canvas.drawCircle(cx, cy, 38, C_ICE1)
    canvas.drawCircle(cx, cy, 37, C_FROST)
    canvas.fillCircle(cx - 10, cy - 14, 5, C_ICE2)
    canvas.fillCircle(cx - 10, cy - 14, 3, C_SNOW)

    canvas.setTextColor(C_TXT, C_BG)
    canvas.setTextSize(2)
    canvas.drawString("MeteoStation", 72, 148)

    canvas.setTextColor(C_TXT2, C_BG)
    canvas.setTextSize(1)
    canvas.drawString("CoreS3 SE  *  ENV III", 90, 174)

    # V
    canvas.setTextColor(C_GLASS, C_BG)
    canvas.drawString("v1.5   Jun 2026", 114, 210)

    canvas.push(0, 0)
    canvas.delete()
    time.sleep(2)
     # Fade in 
def fade_in(target_brightness, steps=10):
    for i in range(steps + 1):
        M5.Lcd.setBrightness(target_brightness * i // steps)
        time.sleep_ms(30)    
# ── sensor ────────────────────────────────────────────
def read_sensors(sensor):
  try:
    temp  = sensor.read_temperature()
    press = sensor.read_pressure()
    humi  = sensor.read_humidity()
    if math.isnan(temp):  temp  = 0.0
    if math.isnan(press): press = 0.0
    if math.isnan(humi):  humi  = 0.0
    return temp, humi, press
  except Exception:
    return 0.0, 0.0, 0.0
# ══════════════════════════════════════════════════════
                    #  Render
# ══════════════════════════════════════════════════════
def render():
    if   wifi_screen == 1:            draw_wifi_list()
    elif wifi_screen == 2:            draw_wifi_password()
    elif current_screen == SCREEN_MAIN:     draw_main_screen()
    elif current_screen == SCREEN_DATA:     draw_data_screen()
    elif current_screen == SCREEN_WEATHER:  draw_weather_screen()
    elif current_screen == SCREEN_FORECAST: draw_forecast_screen()
    elif current_screen == SCREEN_SETTINGS: draw_settings_screen()
    
async def wifi_loop():
    RETRY_DELAY  = 5 * 60    
    MAX_RETRIES  = 3         

    while True:
        weather_ms = cfg.get('weather_refresh_min', 30) * 60
        await asyncio.sleep(weather_ms)
        # take 1
        success = await do_wifi_tasks()

        # Retry 
        retries = 0
        while not success and retries < MAX_RETRIES:
            retries += 1
            print("[wifi] retry %d/%d in %d min" % (retries, MAX_RETRIES, RETRY_DELAY//60))
            await asyncio.sleep(RETRY_DELAY)
            success = await do_wifi_tasks()

        if not success:
            print("[wifi] all retries failed, next attempt in %d min" % (weather_ms//60))
        
async def main_loop(sensor, rmt):
    global current_screen, is_sleeping, needs_redraw
    global last_touch_ms, last_sensor_ms, last_graph_ms
    global last_minute_ms

    while True:
        M5.update()
        now          = time.ticks_ms()
        needs_redraw = False

        # ── TOUCH ──────────────────────────────────
        if M5.Touch.getCount() > 0:
            tx = M5.Touch.getX()
            ty = M5.Touch.getY()
            if is_sleeping:
                M5.Lcd.setBrightness(cfg['brightness'])
                is_sleeping   = False
                last_touch_ms = now
                time.sleep_ms(200)
                render()
                continue
            last_touch_ms = now
            if ty >= (240 - NAV_H):
                new_scr = min(tx // (320 // SCREEN_COUNT), SCREEN_COUNT - 1)
                if new_scr != current_screen:
                    current_screen = new_scr
                    render()
                time.sleep_ms(200)
                continue
            if current_screen == SCREEN_SETTINGS:
                if handle_settings_touch(tx, ty):
                    save_config()
                render()
                time.sleep_ms(150)
                continue

        # ── SLEEP ──────────────────────────────────
        sleep_ms = cfg['sleep_min'] * 60_000 if cfg['sleep_min'] > 0 else 0
        if not is_sleeping and sleep_ms > 0:
            if time.ticks_diff(now, last_touch_ms) > sleep_ms:
                M5.Lcd.setBrightness(0)
                is_sleeping = True

        # ── SENSOR UPDATE ──────────────────────────
        if not is_sleeping:
            if time.ticks_diff(now, last_sensor_ms) >= SENSOR_MS:
                last_sensor_ms = now
                t, h, p = read_sensors(sensor)
                sensor_data.update(temp=t, humi=h, press=p,
                                   battery=M5.Power.getBatteryLevel())
                needs_redraw = True

        # ── GRAPH HISTORY ──────────────────────────
        if time.ticks_diff(now, last_graph_ms) >= GRAPH_MS:
            last_graph_ms = now
            if sensor_data['temp'] > 0:
                temp_history.append(sensor_data['temp'])
                if len(temp_history) > GRAPH_MAX:
                    temp_history.pop(0)
            if sensor_data['press'] > 0:
                press_history.append(sensor_data['press'])
                if len(press_history) > GRAPH_MAX:
                    press_history.pop(0)

        # ── TOPBAR TICK ────────────────────────────
        if time.ticks_diff(now, last_minute_ms) >= 60_000:
            last_minute_ms = now
            needs_redraw   = True

        if needs_redraw and not is_sleeping:
            render()

        await asyncio.sleep_ms(50) # reserved for future refactoring
# ── WiFi Config constants ─────────────────────────────
WL_ROW_H    = 28    
WL_ROW_START = 92   
WL_MAX_ROWS  = 5    # limit on a screen (Wlans)
# ── Keyboard layout constants ─────────────────────────
KB_KEY_W  = 29      
KB_KEY_H  = 24      
KB_GAP    = 2       
KB_ROW_Y  = [104, 130, 156, 190]  

KB_ROWS_ABC = [
    list("QWERTYUIOP"),
    list("ASDFGHJKL"),
    list("ZXCVBNM"),
    ["SHIFT", "SPACE", "DEL", "123"],
]
KB_ROWS_123 = [
    list("1234567890"),
    list("-/:;()@.,?"),
    list("!\"#$%^&*_+"),
    ["SHIFT", "SPACE", "DEL", "ABC"],
]
wifi_kb_caps  = 1   # 0=lowercase, 1=one-shot upper, 2=CAPS LOCK
# ══════════════════════════════════════════════════════
#  WiFi Config — List Screen
# ══════════════════════════════════════════════════════
def draw_wifi_list():
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240, C_BG)
    canvas.fillRect(0,   0, 10, 240, 0x020508)
    canvas.fillRect(310, 0, 10, 240, 0x020508)
    canvas.drawRoundRect(2, 2, 316, 236, 8, C_ICE1)
    canvas.drawRoundRect(3, 3, 314, 234, 8, 0x0F2840)   # inner shadow
    # ── topbar ───────────────────────────────────────
    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)
    # btn Back
    canvas.fillRoundRect(4, 5, 56, 22, 6, C_GLASS)
    canvas.drawRoundRect(4, 5, 56, 22, 6, C_ICE1)
    canvas.setTextColor(C_ICE1, C_GLASS)
    canvas.setTextSize(1)
    canvas.drawString("< Back", 10, 14)
    # Header WiFi
    canvas.setTextColor(C_A1, C_TOPBAR)
    canvas.drawString("WiFi Setup", 122, 16)

    # ── status ───────────────────
    canvas.fillRoundRect(8, 36, 304, 22, 6, C_CARD)
    canvas.fillRect(8, 36, 152, 2, C_A1)
    canvas.fillRect(160, 36, 152, 2, C_DARK)
    canvas.setTextSize(1)

    wlan = network.WLAN(network.STA_IF)
    if wlan.isconnected():
        current_ssid = wlan.config('essid')
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("Connected:", 18, 51)
        canvas.setTextColor(C_ICE1, C_CARD)
        canvas.drawString(current_ssid[:20], 80, 51)
    else:
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("Not connected", 18, 51)

    # ── Header + btn Scan ───────────────
    canvas.setTextColor(C_TXT2, C_BG)
    canvas.drawString("Available networks", 18, 70)
    canvas.fillRoundRect(238, 62, 52, 16, 4, C_GLASS)
    # stripe
    for sy in range(63, 78, 3):
        canvas.drawLine(239, sy, 289, sy, 0x0A1828)
    canvas.drawRoundRect(238, 62, 52, 16, 4, C_ICE1)
    canvas.setTextColor(C_ICE1, C_GLASS)
    canvas.drawString("Scan", 252, 67)
    canvas.fillRect(8, 82, 304, 1, C_SEP)
    # ── list  ─────────────────────────────────
    if not wifi_networks:
        canvas.setTextColor(C_TXT2, C_BG)
        canvas.drawString("Tap Scan to search...", 18, 110)
    else:
        wlan_ssid = wlan.config('essid') if wlan.isconnected() else ""
        for i, (ssid, rssi) in enumerate(wifi_networks[:WL_MAX_ROWS]):
            ry = WL_ROW_START + i * WL_ROW_H
            is_active = (ssid == wlan_ssid)

            bg = 0x0D1E30 if is_active else C_CARD
            canvas.fillRoundRect(8, ry, 304, WL_ROW_H - 2, 4, bg)
            if is_active:
                canvas.fillRect(8, ry, 3, WL_ROW_H - 2, C_A1)

            # SSID cut
            label = ssid[:26] if len(ssid) > 26 else ssid
            tc = C_TXT if is_active else C_TXT2
            canvas.setTextColor(tc, bg)
            canvas.drawString(label, 18, ry + 14)

            # rssi → 3 lvl
            if rssi >= -60:   sig = "***"
            elif rssi >= -75: sig = "** "
            else:             sig = "*  "
            sc = C_ICE1 if is_active else C_TXT2
            canvas.setTextColor(sc, bg)
            canvas.drawString(sig, 286, ry + 14)

    canvas.push(0, 0)
    canvas.delete()
# ══════════════════════════════════════════════════════
#  WiFi Config — Password Entry Screen
# ══════════════════════════════════════════════════════
def draw_wifi_password():
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240, C_BG)
    canvas.fillRect(0,   0, 10, 240, 0x020508)
    canvas.fillRect(310, 0, 10, 240, 0x020508)

    # ── topbar ───────────────────────────────────────
    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)
    canvas.fillRoundRect(6, 6, 46, 20, 5, C_GLASS)
    canvas.setTextColor(C_ICE1, C_GLASS)
    canvas.setTextSize(1)
    canvas.drawString("< Back", 12, 16)
    canvas.setTextColor(C_A1, C_TOPBAR)
    canvas.drawString("Enter Password", 106, 16)

    # ── info card: SSID + password field ─────────────
    canvas.fillRoundRect(8, 36, 304, 52, 8, C_CARD)
    canvas.fillRect(8, 36, 152, 2, C_A1)
    canvas.fillRect(160, 36, 152, 2, C_DARK)

    canvas.setTextSize(1)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("Network:", 18, 50)
    canvas.setTextColor(C_ICE1, C_CARD)
    ssid_label = wifi_selected[:24] if wifi_selected else "?"
    canvas.drawString(ssid_label, 72, 50)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("Password:", 18, 68)

    # password field
    canvas.fillRoundRect(74, 58, 164, 18, 3, 0x0D1E30)
    if wifi_show_pass:
        display_pass = wifi_password[:18]
    else:
        if len(wifi_password) > 0:
            display_pass = "•" * (len(wifi_password) - 1) + wifi_password[-1]
        else:
            display_pass = ""
    canvas.setTextColor(C_ICE1, 0x0D1E30)
    canvas.drawString(display_pass[:18], 78, 69)
    # cursor
    cur_x = 78 + min(len(display_pass), 18) * 6
    canvas.fillRect(cur_x, 59, 1, 14, C_ICE1)

    # btn 👁 show/hide
    eye_bg = C_A1 if wifi_show_pass else C_GLASS
    canvas.fillRoundRect(242, 58, 28, 18, 3, eye_bg)
    canvas.setTextColor(C_TXT, eye_bg)
    canvas.drawString("show", 244, 69)

    # btn ⌫ in a field 
    canvas.fillRoundRect(274, 58, 28, 18, 3, 0x1A1030)
    canvas.setTextColor(0xFF6B6B, 0x1A1030)
    canvas.drawString("del", 280, 69)
    # pass bar
    bar_filled = min(len(wifi_password), 8) * 36
    bar_color  = 0x4CAF50 if len(wifi_password) >= 8 else C_A1
    canvas.fillRoundRect(74, 86, 236, 4, 2, C_DARK)
    if bar_filled > 0:
        canvas.fillRoundRect(74, 80, bar_filled, 4, 2, bar_color)
    # ── keyboard ────────────────────────────────────
    rows = KB_ROWS_123 if wifi_kb_nums else KB_ROWS_ABC

    for row_idx, keys in enumerate(rows[:3]):   
        n    = len(keys)
        total_w = n * KB_KEY_W + (n - 1) * KB_GAP
        start_x = (320 - total_w) // 2
        ry = KB_ROW_Y[row_idx]

        for col_idx, ch in enumerate(keys):
            kx = start_x + col_idx * (KB_KEY_W + KB_GAP)
            # Shift 
            label = ch if wifi_kb_caps > 0 else ch.lower()
            canvas.fillRoundRect(kx, ry, KB_KEY_W, KB_KEY_H, 4, C_GLASS)
            canvas.setTextColor(C_TXT, C_GLASS)
            canvas.drawString(label, kx + 9, ry + 15)

    # ── totals ────────────────────────────────
    ry = KB_ROW_Y[3]
    # CAPS 
    if wifi_kb_caps == 0:
        caps_bg, caps_lbl = C_GLASS,   "abc"
    elif wifi_kb_caps == 1:
        caps_bg, caps_lbl = C_A1,      "ABC"
    else:
        caps_bg, caps_lbl = 0xFF6B6B,  "CAP"   # червоний = locked

    canvas.fillRoundRect(6, ry, 40, KB_KEY_H, 4, caps_bg)
    canvas.setTextColor(C_TXT, caps_bg)
    canvas.drawString(caps_lbl, 10, ry + 15)

    # SPACE
    canvas.fillRoundRect(48, ry, 150, KB_KEY_H, 4, C_GLASS)
    canvas.setTextColor(C_TXT2, C_GLASS)
    canvas.drawString("space", 103, ry + 15)

    # ⌫ Backspace
    canvas.fillRoundRect(200, ry, 40, KB_KEY_H, 4, 0x1A1030)
    canvas.setTextColor(0xFF6B6B, 0x1A1030)
    canvas.drawString("<-", 210, ry + 15)

    # 123 / ABC toggle
    nums_bg = C_A1 if wifi_kb_nums else C_GLASS
    nums_label = "ABC" if wifi_kb_nums else "123"
    canvas.fillRoundRect(242, ry, 34, KB_KEY_H, 4, nums_bg)
    canvas.setTextColor(C_TXT, nums_bg)
    canvas.drawString(nums_label, 249, ry + 15)

    # Connect
    canvas.fillRoundRect(278, ry, 38, KB_KEY_H, 4, 0x005A9E)
    canvas.setTextColor(C_TXT, 0x005A9E)
    canvas.drawString("OK", 287, ry + 15)

    canvas.push(0, 0)
    canvas.delete()
def kb_key_at(tx, ty):
    
    rows = KB_ROWS_123 if wifi_kb_nums else KB_ROWS_ABC

    for row_idx, keys in enumerate(rows[:3]):
        ry = KB_ROW_Y[row_idx]
        if not (ry <= ty <= ry + KB_KEY_H):
            continue
        n       = len(keys)
        total_w = n * KB_KEY_W + (n - 1) * KB_GAP
        start_x = (320 - total_w) // 2
        col_idx = (tx - start_x) // (KB_KEY_W + KB_GAP)
        if 0 <= col_idx < n:
            ch = keys[col_idx]
            # tap check
            kx = start_x + col_idx * (KB_KEY_W + KB_GAP)
            if kx <= tx <= kx + KB_KEY_W:
                return ch if wifi_kb_caps > 0 else ch.lower()
    return None
# ____________________
# Connect with spinner
async def do_wifi_connect():

    global wifi_screen

    # ── draw overlay spin ──────────────────────
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240, C_BG)
    canvas.fillRect(0,   0, 10, 240, 0x020508)
    canvas.fillRect(310, 0, 10, 240, 0x020508)

    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)
    canvas.setTextColor(C_A1, C_TOPBAR)
    canvas.setTextSize(1)
    canvas.drawString("Connecting...", 114, 16)

    canvas.fillRoundRect(8, 60, 304, 80, 12, C_CARD)
    canvas.fillRect(8, 60, 152, 2, C_A1)
    canvas.fillRect(160, 60, 152, 2, C_DARK)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString("Connecting to:", 80, 80)
    canvas.setTextColor(C_ICE1, C_CARD)
    canvas.drawString(wifi_selected[:24], 80, 96)

    # spin
    for frame in range(16):
        dots = "." * ((frame % 4) + 1) + "   "
        canvas.fillRect(80, 108, 160, 14, C_CARD)
        canvas.setTextColor(C_A1, C_CARD)
        canvas.drawString("Please wait" + dots[:4], 80, 118)
        canvas.push(0, 0)
        await asyncio.sleep_ms(300)

    canvas.delete()

    # ── connect ──────────────────────────
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(wifi_selected, wifi_password)

    connected = False
    for _ in range(15):
        if wlan.isconnected():
            connected = True
            break
        # updating spin
        canvas = M5.Lcd.newCanvas(320, 240, 16, True)
        canvas.fillRect(0, 0, 320, 240, C_BG)
        canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
        canvas.fillRect(0, 31, 320, 1, C_SEP)
        canvas.setTextColor(C_A1, C_TOPBAR)
        canvas.setTextSize(1)
        canvas.drawString("Connecting...", 114, 16)
        canvas.fillRoundRect(8, 60, 304, 80, 12, C_CARD)
        canvas.fillRect(8, 60, 152, 2, C_A1)
        canvas.fillRect(160, 60, 152, 2, C_DARK)
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("Connecting to:", 80, 80)
        canvas.setTextColor(C_ICE1, C_CARD)
        canvas.drawString(wifi_selected[:24], 80, 96)
        canvas.setTextColor(C_A1, C_CARD)
        canvas.drawString("Please wait...", 80, 118)
        canvas.push(0, 0)
        canvas.delete()
        await asyncio.sleep(1)

    # ── results ────────────────────────────────────
    if connected:
        cfg['wifi_ssid'] = wifi_selected
        cfg['wifi_pass'] = wifi_password
        save_config()
        print("[wifi_cfg] connected and saved:", wifi_selected)
        # show success retutn
        _show_wifi_result(True, wlan.ifconfig()[0])
        await asyncio.sleep(2)
        wifi_screen = 0
        render()
    else:
        wlan.active(False)
        print("[wifi_cfg] connection failed")
        _show_wifi_result(False, "")
        await asyncio.sleep(2)
        render()
def _show_wifi_result(success, ip_str):
    canvas = M5.Lcd.newCanvas(320, 240, 16, True)
    canvas.fillRect(0, 0, 320, 240, C_BG)
    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)
    canvas.setTextSize(1)

    if success:
        canvas.setTextColor(C_A1, C_TOPBAR)
        canvas.drawString("Connected!", 126, 16)
        canvas.fillRoundRect(8, 60, 304, 80, 12, C_CARD)
        canvas.fillRect(8, 60, 152, 2, 0x4CAF50)
        canvas.fillRect(160, 60, 152, 2, C_DARK)
        canvas.setTextColor(0x4CAF50, C_CARD)
        canvas.drawString("Successfully connected", 60, 85)
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("IP:", 80, 103)
        canvas.setTextColor(C_ICE1, C_CARD)
        canvas.drawString(ip_str, 102, 103)
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("Config saved.", 100, 121)
    else:
        canvas.setTextColor(0xFF6B6B, C_TOPBAR)
        canvas.drawString("Failed!", 134, 16)
        canvas.fillRoundRect(8, 60, 304, 80, 12, C_CARD)
        canvas.fillRect(8, 60, 152, 2, 0xFF6B6B)
        canvas.fillRect(160, 60, 152, 2, C_DARK)
        canvas.setTextColor(0xFF6B6B, C_CARD)
        canvas.drawString("Connection failed", 80, 85)
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("Check password and retry.", 55, 103)

    canvas.push(0, 0)
    canvas.delete()
#---touch handler for WiFi List:
async def handle_wifi_list_touch(tx, ty):
    global wifi_screen, wifi_networks, wifi_selected
    global wifi_password, wifi_kb_shift, wifi_kb_nums

    # ── Back button (topbar) ──────────────────────────
    if ty <= 32 and tx <= 52:
        wifi_screen = 0
        render()
        return

    # ── Scan button ───────────────────────────────────
    if 63 <= ty <= 79 and tx >= 236:
        # show "Scanning..."
        canvas = M5.Lcd.newCanvas(320, 240, 16, True)
        canvas.fillRect(0, 0, 320, 240, C_BG)
        canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
        canvas.fillRect(0, 31, 320, 1, C_SEP)
        canvas.setTextColor(C_A1, C_TOPBAR)
        canvas.setTextSize(1)
        canvas.drawString("WiFi Setup", 122, 16)
        canvas.setTextColor(C_TXT2, C_BG)
        canvas.drawString("Scanning...", 120, 120)
        canvas.push(0, 0)
        canvas.delete()

        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        raw = wlan.scan()  
        # (ssid_bytes, bssid, ch, rssi, auth, hidden)
        nets = []
        seen = set()
        for item in raw:
            try:
                ssid = item[0].decode('utf-8', 'ignore').strip()
            except:
                ssid = str(item[0])
            if ssid and ssid not in seen:
                seen.add(ssid)
                nets.append((ssid, item[3]))   # (ssid, rssi)
        # sorting rssi 
        nets.sort(key=lambda x: x[1], reverse=True)
        wifi_networks = nets
        render()
        return

    # ── tap wlan field ───────────────────────────
    if ty >= WL_ROW_START:
        idx = (ty - WL_ROW_START) // WL_ROW_H
        if 0 <= idx < len(wifi_networks[:WL_MAX_ROWS]):
            wifi_selected  = wifi_networks[idx][0]
            wifi_password  = ""
            wifi_kb_shift  = False
            wifi_kb_nums   = False
            wifi_screen    = 2
            render()
        return
    
async def handle_wifi_password_touch(tx, ty):
    global wifi_screen, wifi_password
    global wifi_kb_caps, wifi_kb_nums, wifi_show_pass

    # ── Back button ───────────────────────────────────
    if ty <= 32 and tx <= 52:
        wifi_screen = 1
        render()
        return

    # ── show/hide password ────────────────────────────
    if 58 <= ty <= 76 and 242 <= tx <= 270:
        wifi_show_pass = not wifi_show_pass
        render()
        return

    # ── del pass field ─────────────────────────────
    if 58 <= ty <= 76 and 274 <= tx <= 302:
        wifi_password = wifi_password[:-1]
        render()
        return

    # ── totals ─────────────
    ry = KB_ROW_Y[3]
    if ry <= ty <= ry + KB_KEY_H:
        if tx <= 46:                          # SHIFT / регістр
            wifi_kb_caps = (wifi_kb_caps + 1) % 3
        elif 48 <= tx <= 198:                 # SPACE
            wifi_password += " "
            if wifi_kb_caps == 1:
                wifi_kb_caps = 0
        elif 200 <= tx <= 240:                # Backspace ⌫
            wifi_password = wifi_password[:-1]
        elif 242 <= tx <= 276:                # 123 / ABC toggle
            wifi_kb_nums  = not wifi_kb_nums
            wifi_kb_shift = False
            wifi_kb_caps  = 1 
        elif tx >= 278:                       # Connect / OK
            if len(wifi_password) >= 8:
                await do_wifi_connect()
                return
            else:
                pass
        render()
        return

    # ── symbols 0-2 ───────────────────────────
    ch = kb_key_at(tx, ty)
    if ch:
        wifi_password += ch
        # shift (one-shot)
        if wifi_kb_caps == 1:
            wifi_kb_caps = 0   # one-shot → lowercase
        render()
# ══════════════════════════════════════════════════════
# main loop
# ══════════════════════════════════════════════════════
async def main():
    global current_screen, is_sleeping
    global last_touch_ms, last_sensor_ms, last_graph_ms, last_weather_ms
    global last_minute_ms
    global sensor_data
    global outdoor_weather
    global is_wifi_active, is_fetching
    global _weather_saved_at

    load_config()
    sensor, rmt = init_hardware()
    show_splash()
    fade_in(cfg['brightness'])   

    rgb_pulse_animation(rmt)
    t, h, p = read_sensors(sensor)
    sensor_data.update(temp=t, humi=h, press=p,
                       battery=M5.Power.getBatteryLevel())
    _cached, _saved_at = wcache.load()
    if _cached is not None:
      outdoor_weather = _cached      
      _weather_saved_at = _saved_at
      print("[boot] using cached weather, age:", wcache.age_str(_saved_at))
    render()
    await do_wifi_tasks(force_ntp=True)

    global _icons_mod
    import icomod as _icons_mod
    asyncio.create_task(wifi_loop())   
    render()  
    last_touch_ms = time.ticks_ms()
    last_sensor_ms = 0
    last_ntp_ms     = time.ticks_ms()     
    last_weather_ms = time.ticks_ms()
    last_minute_ms = time.ticks_ms()
    while True:
        M5.update()
        now = time.ticks_ms()
        needs_redraw = False
        # ── TOUCH ──────────────────────────────────
        if M5.Touch.getCount() > 0:
            tx = M5.Touch.getX()          
            ty = M5.Touch.getY()          
            if is_sleeping:               
                M5.Lcd.setBrightness(cfg['brightness'])
                is_sleeping   = False
                last_touch_ms = now
                time.sleep_ms(200)
                render()
                continue

            last_touch_ms = now

            # Nav bar
            if ty >= (240 - NAV_H):
                new_scr = min(tx // (320 // SCREEN_COUNT), SCREEN_COUNT - 1)
                if new_scr != current_screen:
                    current_screen = new_scr
                    render()
                time.sleep_ms(200)
                continue

            # Settings touch
            if wifi_screen == 1:
                await handle_wifi_list_touch(tx, ty)
                while M5.Touch.getCount() > 0:
                    M5.update()
                    await asyncio.sleep_ms(20)
                time.sleep_ms(80)
                continue
            if wifi_screen == 2:
                await handle_wifi_password_touch(tx, ty)
                # чекаємо поки палець підніметься
                while M5.Touch.getCount() > 0:
                    M5.update()
                    await asyncio.sleep_ms(20)
                time.sleep_ms(80)
                continue
            if current_screen == SCREEN_SETTINGS:
                if await handle_settings_touch(tx, ty):
                    save_config()
                render()
                time.sleep_ms(150)
                continue

        # ── SLEEP ──────────────────────────────────
        sleep_ms = cfg['sleep_min'] * 60_000 if cfg['sleep_min'] > 0 else 0
        if not is_sleeping and sleep_ms > 0:
            if time.ticks_diff(now, last_touch_ms) > sleep_ms:
                M5.Lcd.setBrightness(0)
                is_sleeping = True

        # ── SENSOR UPDATE ──────────────────────────
        if not is_sleeping:
            if time.ticks_diff(now, last_sensor_ms) >= SENSOR_MS:
                last_sensor_ms = now
                t, h, p = read_sensors(sensor)
                sensor_data.update(temp=t, humi=h, press=p,
                                   battery=M5.Power.getBatteryLevel())
                needs_redraw = True

        # ── GRAPH HISTORY ──────────────────────────
        if time.ticks_diff(now, last_graph_ms) >= GRAPH_MS:
            last_graph_ms = now
            if sensor_data['temp'] > 0:
                temp_history.append(sensor_data['temp'])
                if len(temp_history) > GRAPH_MAX:
                    temp_history.pop(0)
            # trend pres ───────────────────
            if sensor_data['press'] > 0:
                press_history.append(sensor_data['press'])
                if len(press_history) > GRAPH_MAX:
                    press_history.pop(0)
        # Topbar
        if time.ticks_diff(now, last_minute_ms) >= 60_000:
           last_minute_ms = now
           needs_redraw = True

        if needs_redraw and not is_sleeping:
           render()
        await asyncio.sleep_ms(50)
        
if __name__ == '__main__':
    asyncio.run(main())




