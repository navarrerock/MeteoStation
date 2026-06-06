# ─────────────────────────────────────────────────────────────
# wcache.py  —  MeteoStation v3.0

import json
import time
import os

CACHE_DIR  = "/flash/cache"
CACHE_FILE = "/flash/cache/weather.json"
ARCHIVE_FILE = "/flash/cache/archive.json"
STALE_HOURS = 6 


def _ensure_dir():
    try:
        os.stat(CACHE_DIR)
    except OSError:
        os.mkdir(CACHE_DIR)


def save(outdoor_weather_dict):
    
    _ensure_dir()
    try:
        payload = {
            "saved_at": time.time(),   
            "data":     outdoor_weather_dict,
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(payload, f)
        print("[cache] saved  %.1f KB" % (os.stat(CACHE_FILE)[6] / 1024))
        return True
    except Exception as e:
        print("[cache] save error:", e)
        return False


def load():
    try:
        with open(CACHE_FILE, 'r') as f:
            payload = json.load(f)
        saved_at = payload.get("saved_at", 0)
        data     = payload.get("data")
        if not data:
            return None, None
        age_min = (time.time() - saved_at) // 60
        print("[cache] loaded  age=%dh%dm" % (age_min // 60, age_min % 60))
        return data, saved_at
    except Exception as e:
        print("[cache] load error:", e)
        return None, None


def is_stale(saved_at):
    if not saved_at:
        return True
    age_hours = (time.time() - saved_at) / 3600
    return age_hours > STALE_HOURS


def age_str(saved_at):
    
    if not saved_at:
        return "no data"
    age_min = int((time.time() - saved_at) / 60)
    if age_min < 2:
        return "fresh"
    if age_min < 60:
        return "%dm ago" % age_min
    return "%dh ago" % (age_min // 60)


def clear():
    try:
        os.remove(CACHE_FILE)
        print("[cache] cleared")
        return True
    except:
        return False
def save_archive(days_list, date_str):
    
    _ensure_dir()
    try:
        payload = {
            "saved_date": date_str,
            "days": days_list,
        }
        with open(ARCHIVE_FILE, 'w') as f:
            json.dump(payload, f)
        print("[archive] saved %d days" % len(days_list))
        return True
    except Exception as e:
        print("[archive] save error:", e)
        return False


def load_archive(today_str):
    
    try:
        with open(ARCHIVE_FILE, 'r') as f:
            payload = json.load(f)
        if payload.get("saved_date") != today_str:
            print("[archive] stale, need refresh")
            return None
        days = payload.get("days") or []
        print("[archive] loaded from cache, %d days" % len(days))
        return days
    except Exception as e:
        print("[archive] load error:", e)
        return None