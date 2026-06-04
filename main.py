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
#  Screen 0 - main
# ══════════════════════════════════════════════════════
def draw_main_screen():
    d, t = format_datetime()
    temp    = sensor_data['temp']
    humi    = sensor_data['humi']
    press   = sensor_data['press']
    battery = sensor_data['battery']

    canvas = M5.Lcd.newCanvas(320, 240, 16, True)

    grad = [0x040810, 0x050A14, 0x060C18, 0x07101C,
            0x081220, 0x091424, 0x091828, 0x0A1C2C]
    for i, c in enumerate(grad):
        canvas.fillRect(0, i * 30, 320, 30, c)

    # ── TOP BAR ──────────────────────────────────────
    canvas.fillRect(0, 0, 320, 32, C_TOPBAR)
    canvas.fillRect(0, 31, 320, 1, C_SEP)
    canvas.fillCircle(14, 16, 5, C_GLASS)
    canvas.fillCircle(14, 16, 3, C_ICE1)
    canvas.setTextColor(C_TXT2, C_TOPBAR)
    canvas.setTextSize(1)
    canvas.drawString(d, 26, 10)
    canvas.drawString(t, 258, 10)

    # ── temp ───────────────────────────
    canvas.fillRoundRect(8, 40, 192, 105, 10, C_CARD)

     # Depth tricks
    canvas.drawLine(9,  41, 198, 41,  0x1A3A5A)  # top highlight
    canvas.drawLine(9,  42, 198, 42,  0x112840)  # sub-highlight
    canvas.drawLine(9,  144, 198, 144, 0x040810) # bottom shadow
    canvas.drawLine(10, 40,  10,  144, 0x1A3A5A) # left highlight

     # Border
    canvas.drawRoundRect(8, 40, 192, 105, 10, C_ICE1)
    canvas.fillRect(8, 50, 3, 87, C_ICE1)
    canvas.fillRoundRect(8, 40, 3, 16, 3, C_ICE1)

    canvas.drawImage("/flash/icons/ui/thermometer.png", 128, 44)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Temp", 18, 47)
    canvas.setTextColor(C_TXT, C_CARD)       # ← bg=C_CARD
    canvas.setTextSize(3)
    t_val = temp if cfg['temp_unit'] == 'C' else temp * 9/5 + 32
    canvas.drawString("%.1f" % t_val, 18, 65)
    canvas.setTextSize(1)
    canvas.setTextColor(C_ICE1, C_CARD)
    canvas.drawString(cfg['temp_unit'], 138, 73)

    # ── bat ───────────────────────────────
    canvas.fillRoundRect(207, 39, 106, 107, 11, C_ICE2)
    canvas.fillRoundRect(208, 40, 104, 105, 10, C_CARD)
    canvas.fillRect(208, 50, 3, 87, C_ICE2)
    canvas.fillRoundRect(208, 40, 3, 16, 3, C_ICE2)

    canvas.drawImage("/flash/icons/ui/battery_shell.png", 211, 35)  
    fw = max(2, int(38 * battery / 100))   # max 38px
    bc = 0x4AB3D6 if battery > 50 else (0xF5C842 if battery > 20 else 0xE84040)
    canvas.fillRoundRect(222, 60, fw, 14, 2, bc)                    

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Battery", 218, 47)
    canvas.setTextColor(C_TXT, C_CARD)       # ← bg=C_CARD
    canvas.setTextSize(2)
    canvas.drawString("%d%%" % battery, 220, 88)

    # ── hum ─────────────────────────────
    canvas.fillRoundRect(7, 152, 146, 67, 11, C_FROST)
    canvas.fillRoundRect(8, 153, 144, 65, 10, C_CARD)
    canvas.fillRect(8, 163, 3, 47, C_FROST)
    canvas.fillRoundRect(8, 153, 3, 16, 3, C_FROST)
    
    canvas.drawImage("/flash/icons/ui/humidity.png", 83, 153)


    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Humidity", 18, 161)
    canvas.setTextColor(C_TXT, C_CARD)       # ← bg=C_CARD
    canvas.setTextSize(2)
    canvas.drawString("%d%%" % humi, 18, 178)

    # ── pres ─────────────────────────────────
    p_val  = press if cfg['press_unit'] == 'hPa' else int(press * 0.75006)
    p_unit = cfg['press_unit']
    canvas.fillRoundRect(159, 152, 154, 67, 11, C_FROST)
    canvas.fillRoundRect(160, 153, 152, 65, 10, C_CARD)
    canvas.fillRect(160, 163, 3, 47, C_FROST)
    canvas.fillRoundRect(160, 153, 3, 16, 3, C_FROST)

    # icon
    canvas.drawImage("/flash/icons/ui/pressure.png", 248, 153)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Pressure", 170, 161)
    canvas.setTextColor(C_TXT, C_CARD)       # ← bg=C_CARD
    canvas.setTextSize(2)
    canvas.drawString("%d" % p_val, 170, 178)
    canvas.setTextSize(1)
    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.drawString(p_unit, 232, 190)

    # ── GLACIER ACCENT ─────────────────────────
    canvas.fillRect(0, 237, 320, 3, C_ICE1)
    canvas.fillRect(0, 236, 80, 1, C_ICE2)   # highlight

    draw_nav_bar(canvas)
    canvas.push(0, 0)
    canvas.delete()
# ══════════════════════════════════════════════════════
#  Screen 1 - G
# ══════════════════════════════════════════════════════
def draw_data_screen():
    d, t = format_datetime()
    temp    = sensor_data['temp']
    humi    = sensor_data['humi']
    press   = sensor_data['press']

    hi  = heat_index(temp, humi)
    alt = altitude_from_pressure(press)

    canvas = M5.Lcd.newCanvas(320, 240, 16, True)

    grad = [0x040810, 0x050A14, 0x060C18, 0x07101C,
            0x081220, 0x091424, 0x091828, 0x0A1C2C]
    for i, c in enumerate(grad):
        canvas.fillRect(0, i * 30, 320, 30, c)

    draw_topbar(canvas, d, t, title="Data")

    canvas.fillRoundRect(6, 36, 152, 68, 8, C_CARD)
    canvas.drawRoundRect(6, 36, 152, 68, 8, C_ICE1)
    canvas.drawLine(7, 37, 157, 37, C_GLASS)       # top highlight
    canvas.drawLine(7, 103, 157, 103, C_DARK)      # bottom shadow
    canvas.fillRect(6, 46, 3, 50, C_ICE1)          

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
    canvas.drawString("Feels like", 18, 42)

    canvas.setTextColor(C_TXT, C_CARD)
    canvas.setTextSize(2)
    canvas.drawString("%.1f" % hi, 18, 58)
    canvas.setTextSize(1)
    canvas.setTextColor(C_ICE1, C_CARD)
    canvas.drawString("C", 90, 64)

    canvas.setTextColor(C_TXT2, C_CARD)
    if temp < 27 or humi < 40:
        canvas.drawString("= actual", 18, 82)
    else:
        diff = hi - temp
        dc = 0xFF6B6B if diff > 2 else (0xFFCA28 if diff > 0 else C_ICE1)
        canvas.setTextColor(dc, C_CARD)
        canvas.drawString("%+.1f vs real" % diff, 18, 82)

    canvas.fillRoundRect(162, 36, 152, 68, 8, C_CARD)
    canvas.drawRoundRect(162, 36, 152, 68, 8, C_ICE1)
    canvas.drawLine(163, 37, 313, 37, C_GLASS)
    canvas.drawLine(163, 103, 313, 103, C_DARK)
    canvas.fillRect(162, 46, 3, 50, C_FROST)

    # PNG altitude
    canvas.drawImage("/flash/icons/ui/altitude_48.png", 256, 38)

    canvas.setTextColor(C_TXT2, C_CARD)
    canvas.setTextSize(1)
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

    # ── BAR CHART ────────────────────────────────────
    BX = 10    
    BY = 114   
    BW = 300   
    BH = 72    

    canvas.fillRoundRect(BX - 4, BY - 6, BW + 8, BH + 28, 6, C_CARD)
    canvas.drawRoundRect(BX - 4, BY - 6, BW + 8, BH + 28, 6, C_GLASS)

    if len(temp_history) >= 2:
        mn  = min(temp_history)
        mx  = max(temp_history)
        rng = mx - mn if mx != mn else 1.0
        n   = len(temp_history)

        avg = sum(temp_history) / n
        avg_y = BY + BH - int(BH * (avg - mn) / rng)
        canvas.drawLine(BX, avg_y, BX + BW, avg_y, C_SEP)

        
        bar_w = BW // GRAPH_MAX   
        for i, val in enumerate(temp_history):
            bh = max(2, int(BH * (val - mn) / rng))
            bx = BX + i * bar_w
            by = BY + BH - bh

            ratio = (val - mn) / rng
            if ratio > 0.75:
                bc = 0xFF6B6B   
            elif ratio > 0.5:
                bc = 0xFFCA28   
            elif ratio > 0.25:
                bc = C_ICE1     
            else:
                bc = C_FROST    

            canvas.fillRect(bx, by, bar_w - 1, bh, bc)
            canvas.drawLine(bx, by, bx + bar_w - 2, by, C_SNOW)

        # Min / Avg / Max
        canvas.setTextColor(C_ICE1, C_CARD)
        canvas.setTextSize(1)
        canvas.drawString("Min %.1f" % mn,  BX,        BY + BH + 8)
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.drawString("Avg %.1f" % avg, BX + 100,  BY + BH + 8)
        canvas.setTextColor(0xFF6B6B, C_CARD)
        canvas.drawString("Max %.1f" % mx,  BX + 220,  BY + BH + 8)

    else:
        canvas.setTextColor(C_TXT2, C_CARD)
        canvas.setTextSize(1)
        canvas.drawString("Collecting data...", 90, BY + BH//2 - 4)
        canvas.drawString("(%d / %d min)" % (len(temp_history), GRAPH_MAX),
                          105, BY + BH//2 + 8)

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

    # NTP Sync
    y = settings_row_y(5)
    canvas.fillRoundRect(8, y, 304, ROW_H - 4, 6, C_CARD)
    canvas.drawLine(9, y+1, 311, y+1, C_GLASS)
    canvas.setTextColor(C_TXT2, C_CARD); canvas.setTextSize(1)
    canvas.drawString("Time sync (NTP)", 18, y + 13)
    btn(220, y + 6, 84, 20, "Sync now", False)

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

    elif row == 5: # NTP Sync
        if x >= 220:
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
    canvas.drawString("v1.0   May 2026", 114, 210)

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
    if   current_screen == SCREEN_MAIN:     draw_main_screen()
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


