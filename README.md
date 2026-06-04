# MeteoStation

An embedded weather station built on **M5Stack CoreS3 SE** (ESP32-S3), written in pure MicroPython. Measures indoor temperature, humidity, and atmospheric pressure via an ENV III sensor, fetches outdoor weather forecasts from the Open-Meteo API over WiFi, and displays everything across five navigable screens on a 2.0" touchscreen.

---

## Features

- **Five screens** — Main, Data, Weather, Forecast, Settings — navigated via a PNG icon nav bar
- **Local measurements** — temperature, humidity, and pressure polled every 5 seconds via I2C
- **Derived metrics** — heat index (feels-like), barometric altitude, and pressure trend (rising/stable/falling)
- **Outdoor weather** — current conditions, hourly forecast, and tomorrow's outlook via Open-Meteo (no API key required)
- **Weather cache** — last known weather is stored on flash and shown immediately at boot, before WiFi connects (stale-while-revalidate pattern)
- **Stale data indicator** — amber highlight when cached data is older than 6 hours
- **Async architecture** — `asyncio`-based event loop; WiFi refresh runs as a background task so touch and sensors stay responsive during network operations
- **Retry logic** — automatic retry after 5 minutes if a weather fetch fails, up to 3 attempts
- **Sleep mode** — screen blanks after configurable idle timeout, wakes on touch
- **NTP time sync** — at boot and every 24 hours
- **Persistent settings** — brightness, sleep timer, temperature units, and weather refresh interval saved to flash

---

## Hardware

| Component | Notes |
|---|---|
| M5Stack CoreS3 SE | ESP32-S3, 2.0" IPS 320×240 touch display |
| ENV III Unit | SHT30 (temp/humidity) + QMP6988 (pressure), Grove I2C |
| M5GO Battery Bottom 3 | 500 mAh, attaches via pogo pins |

The ENV III sensor connects to **Grove Port A** (SCL = GPIO 1, SDA = GPIO 2). Remove the orange protective film from the CoreS3 SE pogo pins before attaching the battery bottom.

---

## Prerequisites

Before installing, you need two things on your computer.

**Thonny IDE** is used to upload files to the device and interact with the MicroPython REPL. Download it from [thonny.org](https://thonny.org).

**UIFlow2 firmware** must be flashed onto the CoreS3 SE. Use [M5Burner](https://docs.m5stack.com/en/download) to flash the latest UIFlow2 image. In the boot configuration, select **"Run main.py directly"** so the station starts automatically on power-up.

---

## Installation

**Step 1 — Clone the repository:**
```bash
git clone https://github.com/YOUR_USERNAME/MeteoStation.git
cd MeteoStation
```

**Step 2 — Create your config file:**

Copy the example config and fill in your details:
```bash
cp config.example.json config.json
```

Open `config.json` and set at minimum `wifi_ssid`, `wifi_pass`, `weather_lat`, `weather_lon`, and `weather_city`. Coordinates for your location can be found on [open-meteo.com](https://open-meteo.com).

**Step 3 — Create the icon folders on the device:**

Connect the device in Thonny and run in the REPL:
```python
import os
os.mkdir('/flash/icons')
os.mkdir('/flash/icons/ui')
os.mkdir('/flash/cache')
```

**Step 4 — Upload files via Thonny:**

In Thonny's file manager, upload the following to `/flash/` on the device:

```
main.py
wcache.py
icomod.py
config.json
icons/          ← weather PNG icons (18 files)
icons/ui/       ← UI icons (nav bar, cards, status)
```

**Step 5 — Reboot the device.** After the RGB LED animation, the main screen appears with local sensor data. Weather data loads as soon as WiFi connects.

---

## Configuration

All settings live in `/flash/config.json`. The file is created from defaults on first run if it does not exist, so the device will start without WiFi if no config is present — it will display sensor data and show cached weather if available.

| Key | Type | Default | Description |
|---|---|---|---|
| `wifi_ssid` | string | `""` | WiFi network name |
| `wifi_pass` | string | `""` | WiFi password |
| `weather_lat` | float | `0.0` | Latitude of your location |
| `weather_lon` | float | `0.0` | Longitude of your location |
| `weather_city` | string | `"City"` | City name shown in the top bar |
| `utc_offset` | int | `0` | UTC offset in hours |
| `brightness` | int | `120` | Backlight level (40 / 120 / 220) |
| `sleep_min` | int | `2` | Minutes before sleep (0 = disabled) |
| `temp_unit` | string | `"C"` | Temperature unit (`C` or `F`) |
| `sea_level_hpa` | float | `1013.25` | Sea-level pressure for altitude calibration |
| `weather_refresh_min` | int | `30` | Weather update interval in minutes |

Settings can also be changed at runtime on the **Settings screen** and are written to flash immediately.

### Altitude calibration

The `sea_level_hpa` value is *not* your current atmospheric pressure — it is the pressure reduced to sea level, which is always higher than the local reading. Adjust it in Settings (± 0.5 hPa steps) until the altitude shown on the Data screen matches the known elevation of your location.

---

## File Structure

```
/flash/
├── main.py              # Core application: screens, event loop, sensors, weather
├── wcache.py            # Weather cache module (save / load / age)
├── icomod.py            # Icon module: WMO code → PNG filename mapping
├── config.json          # Your settings (not in repo — see config.example.json)
├── icons/               # Weather PNG icons, 64×64, transparent background
│   ├── clear_day.png
│   ├── rain.png
│   └── ...              # 18 icons total
└── icons/ui/            # UI icons: nav bar (24×24), cards, status (16×16)
    ├── nav_main.png
    ├── thermometer.png
    ├── wifi_16.png
    └── ...
```

The `/flash/cache/` directory is created automatically on first successful weather fetch and stores `weather.json` (~2 KB).

---

## Technical Notes

**Why `asyncio`?** The WiFi connection and HTTP fetch can block for several seconds. By running the weather refresh as a separate `asyncio` task (`wifi_loop`), the main loop continues processing touch input and updating sensors while the network operates in the background. The key insight is that `await asyncio.sleep()` yields execution to other tasks, whereas `time.sleep()` would freeze the entire device.

**Why a weather cache?** The stale-while-revalidate pattern means the device always has something useful to show. On boot, the last known weather appears instantly from flash before any network activity. WiFi then fetches fresh data and updates the display — the user never sees empty cards.

**Icon rendering** uses `canvas.drawImage(path, x, y)` on an off-screen canvas buffer. Drawing every element — including PNG icons — onto the canvas *before* `canvas.push()` ensures the display is updated in a single atomic operation, eliminating flicker.

---

## Roadmap

- [ ] Open-Meteo Archive API for 7-day outdoor temperature history
- [ ] Local sensor database (binary circular buffer, persistent across reboots)
- [ ] WiFi configuration from the device screen (no JSON editing required)
- [ ] TrueType fonts for larger, smoother numerals
- [ ] Port to Arduino / C++ for full M5GFX access

---

## License

MIT License — see `LICENSE` for details.
