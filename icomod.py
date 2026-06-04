# ─────────────────────────────────────────────────────────────
# icons.py  —  MeteoStation v1.0
# ─────────────────────────────────────────────────────────────
import M5
import gc

_BG_CARD = 0x080E18   # C_CARD з main

ICON_FILES = {
    "clear_day":           "clear_day.png",
    "clear_night":         "clear_night.png",
    "overcast":            "overcast.png",
    "partly_cloudy_day":   "partly_cloudy_day.png",
    "partly_cloudy_night": "partly_cloudy_night_.png",
    "rain":                "rain.png",
    "drizzle":             "drizzle.png",
    "thunderstorm":        "thunderstorm.png",
    "thunder_only":        "thunder_only.png",
    "snow":                "snow.png",
    "fog":                 "fog.png",
    "windy":               "windy.png",
    "sleet":               "sleet.png",
    "heavy_rain":          "heavy_rain.png",
    "frost":               "frost.png",
    "heat":                "heat.png",
    "blizzard":            "blizzard_.png",
    "squall":              "squall.png",
}

# ── PSRAM  ─────────────────────────────────────────
_sprites = {}

def preload(lcd):
    import os, gc
    loaded = missing = 0

    for name, fname in ICON_FILES.items():
        path = "/flash/icons/" + fname
        try:
            os.stat(path)
            spr = lcd.newCanvas(64, 64, 16, True)   # True = PSRAM
            spr.fillRect(0, 0, 64, 64, _BG_CARD)    
            spr.drawImage(path, 0, 0)               
            _sprites[name] = spr                    
        except Exception as e:
            print("[icon] missing:", fname, e)
            missing += 1
            continue
        loaded += 1

    gc.collect()
    print("[icon] Loaded %d/%d  Free RAM: %d" % (
        loaded, loaded + missing, gc.mem_free()))
    return loaded, missing

def draw(lcd, name, x, y):
    spr = _sprites.get(name)
    if spr:
        spr.push(x, y)   
    else:
        lcd.drawRect(x, y, 64, 64, 0x4AB3)

def wmo_to_icon(code, is_day=True):
    
    s = "day" if is_day else "night"
    m = {
        0:  "clear_" + s,           1:  "clear_" + s,
        2:  "partly_cloudy_" + s,   3:  "overcast",
        45: "fog",    48: "fog",
        51: "drizzle",53: "drizzle",55: "drizzle",
        61: "rain",   63: "rain",   65: "heavy_rain",
        66: "sleet",  67: "sleet",
        71: "snow",   73: "snow",   75: "snow",   77: "snow",
        80: "rain",   81: "heavy_rain", 82: "heavy_rain",
        85: "snow",   86: "blizzard",
        95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm",
    }
    return m.get(code, "clear_" + s)

