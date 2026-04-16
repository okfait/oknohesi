"""
okNoHesi Dashboard Server
Tiny Flask API -- runs silently in background (no window).
Provides file-system access the browser can't do on its own:
  - Reads car preview images from AC install
  - Reads ui_car.json specs
  - Scans screenshot folder
  - Launches Content Manager / AC with a specific car+track
"""
import os, json, glob, subprocess, sys, base64, threading, webbrowser, time
from pathlib import Path
from flask import Flask, jsonify, send_file, request, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config (persisted so the user only sets paths once) ──────────────────────
CONFIG_FILE = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {
    "ac_path": r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa",
    "screens_path": r"C:\Users\lucac\OneDrive\Documents\Assetto Corsa\screens",
    "cm_path": r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa",
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text("utf-8"))
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

cfg = load_config()

# ── Helpers ──────────────────────────────────────────────────────────────────
def ac_cars_path():
    return Path(cfg["ac_path"]) / "content" / "cars"

def ac_tracks_path():
    return Path(cfg["ac_path"]) / "content" / "tracks"

def screens_path():
    return Path(cfg["screens_path"])

def img_to_b64(path: Path) -> str | None:
    """Return base64-encoded image or None if not found."""
    if path and path.exists():
        data = base64.b64encode(path.read_bytes()).decode()
        ext = path.suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext, "jpeg")
        return f"data:image/{mime};base64,{data}"
    return None

def find_car_preview(car_id: str) -> Path | None:
    """Find the best preview image for a car."""
    car_dir = ac_cars_path() / car_id
    if not car_dir.exists():
        return None
    # Priority order: generated preview → any skin preview → ui badge → logo
    gen_preview = car_dir / "skins" / "generated" / "preview.jpg"
    if gen_preview.exists():
        return gen_preview
    for ext in ("preview.jpg", "preview.png"):
        for skin_preview in (car_dir / "skins").rglob(ext) if (car_dir / "skins").exists() else []:
            return skin_preview
    for badge in [car_dir / "ui" / "badge.png", car_dir / "logo.png", car_dir / "ui" / "logo.png"]:
        if badge.exists():
            return badge
    return None

def find_track_preview(track_id: str) -> Path | None:
    """Find track preview image."""
    track_dir = ac_tracks_path() / track_id
    if not track_dir.exists():
        return None
    for p in ["ui/preview.png", "ui/preview.jpg", "preview.png", "preview.jpg"]:
        img = track_dir / p
        if img.exists():
            return img
    # Layouts
    for img in track_dir.rglob("preview.png"):
        return img
    for img in track_dir.rglob("preview.jpg"):
        return img
    return None

def read_ui_car_json(car_id: str) -> dict:
    """Read ui_car.json for a car."""
    path = ac_cars_path() / car_id / "ui" / "ui_car.json"
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8", errors="ignore"))
        except:
            pass
    return {}

def read_ui_track_json(track_id: str) -> dict:
    """Read ui_track.json for a track."""
    track_dir = ac_tracks_path() / track_id
    # Try direct ui_track.json
    for candidate in track_dir.rglob("ui_track.json"):
        try:
            return json.loads(candidate.read_text("utf-8", errors="ignore"))
        except:
            pass
    return {}

# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/config")
def api_get_config():
    return jsonify(cfg)

@app.post("/api/config")
def api_set_config():
    global cfg
    data = request.json or {}
    cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    save_config(cfg)
    return jsonify({"ok": True})

# Prefixes that identify No Hesi / okNoHesi mod cars
NH_PREFIXES = (
    "nohesi_", "nohesituned_", "nohesi-",
    "nh_", "ok_nohesi", "oknohesi",
)
NH_EXCLUDE = ("_traffic", "traffic_", "ai_car", "pace_car")


def is_nh_car(name: str) -> bool:
    nl = name.lower()
    if any(e in nl for e in NH_EXCLUDE):
        return False
    return any(nl.startswith(p) for p in NH_PREFIXES)


@app.get("/api/cars")
def api_cars():
    """List all No Hesi cars installed."""
    cars_dir = ac_cars_path()
    if not cars_dir.exists():
        return jsonify([])

    car_ids = sorted([d.name for d in cars_dir.iterdir() if d.is_dir() and is_nh_car(d.name)])

    result = []
    for car_id in car_ids:
        ui = read_ui_car_json(car_id)
        preview_path = find_car_preview(car_id)
        result.append({
            "id": car_id,
            "name": ui.get("name", car_id.replace("_", " ").title()),
            "brand": ui.get("brand", ""),
            "country": ui.get("country", ""),
            "year": ui.get("year", ""),
            "tags": ui.get("tags", []),
            "class": ui.get("class", ""),
            "specs": ui.get("specs", {}),
            "description": ui.get("description", ""),
            "author": ui.get("author", ""),
            "torqueCurve": ui.get("torqueCurve", []),
            "powerCurve": ui.get("powerCurve", []),
            "hasPreview": preview_path is not None,
        })
    return jsonify(result)

@app.get("/api/cars/<car_id>/preview")
def api_car_preview(car_id):
    """Serve car preview image."""
    path = find_car_preview(car_id)
    if path:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return send_file(path, mimetype=mime)
    abort(404)

@app.get("/api/cars/<car_id>/badge")
def api_car_badge(car_id):
    """Serve car brand badge/logo."""
    badge = ac_cars_path() / car_id / "ui" / "badge.png"
    logo  = ac_cars_path() / car_id / "logo.png"
    if badge.exists():
        return send_file(badge, mimetype="image/png")
    if logo.exists():
        return send_file(logo, mimetype="image/png")
    abort(404)

# No Hesi priority tracks shown first
NH_PRIORITY_TRACKS = [
    "shuto_revival_project_beta", "lac", "la_canyons",
    "ks_black_cat_county", "highlands", "ks_nordschleife",
    "mulholland_drive", "csp_mulholland drive", "ks_laguna_seca",
]


@app.get("/api/tracks")
def api_tracks():
    """List all installed tracks that have UI data or a preview image."""
    tracks_dir = ac_tracks_path()
    if not tracks_dir.exists():
        return jsonify([])

    all_tracks = []
    for d in tracks_dir.iterdir():
        if not d.is_dir():
            continue
        ui = read_ui_track_json(d.name)
        preview_path = find_track_preview(d.name)
        if ui or preview_path:
            all_tracks.append({
                "id": d.name,
                "name": ui.get("name", d.name.replace("_", " ").title()),
                "city": ui.get("city", ""),
                "country": ui.get("country", ""),
                "tags": ui.get("tags", []),
                "description": ui.get("description", ""),
                "hasPreview": preview_path is not None,
            })

    # Sort: NH priority tracks first, then alphabetical
    def sort_key(t):
        try:
            return (0, NH_PRIORITY_TRACKS.index(t["id"]))
        except ValueError:
            return (1, t["name"].lower())

    all_tracks.sort(key=sort_key)
    return jsonify(all_tracks)


@app.get("/api/tracks/<track_id>/preview")
def api_track_preview(track_id):
    path = find_track_preview(track_id)
    if path:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return send_file(path, mimetype=mime)
    abort(404)

@app.get("/api/screenshots")
def api_screenshots():
    """
    List all screenshots.
    Filename pattern: Screenshot_{car_id}_{track_id}_{date}.png
    Returns grouped by car_id.
    """
    sp = screens_path()
    if not sp.exists():
        return jsonify([])
    
    shots = []
    for f in sorted(sp.glob("Screenshot_*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
        name = f.stem  # e.g. Screenshot_nohesi_audi_rs5_f5_lac_...
        parts = name.split("_", 1)  # ['Screenshot', 'nohesi_audi_rs5_f5_lac_...']
        rest = parts[1] if len(parts) > 1 else ""
        
        # Try to figure out car_id by matching against known car IDs
        car_id = _guess_car_from_filename(rest)
        
        shots.append({
            "filename": f.name,
            "path": str(f),
            "car_id": car_id,
            "mtime": f.stat().st_mtime,
        })
    return jsonify(shots)

def _guess_car_from_filename(rest: str) -> str | None:
    """Try to match screenshot filename to a car ID."""
    cars_dir = ac_cars_path()
    if not cars_dir.exists():
        return None
    
    rest_lower = rest.lower().replace("-", "_")
    # Try longest match first
    candidates = [
        d.name for d in cars_dir.iterdir()
        if d.is_dir() and rest_lower.startswith(d.name.lower())
    ]
    if candidates:
        return sorted(candidates, key=len, reverse=True)[0]
    return None

@app.get("/api/screenshots/<path:filename>")
def api_screenshot_file(filename):
    sp = screens_path() / filename
    if sp.exists():
        return send_file(sp, mimetype="image/png")
    abort(404)

@app.post("/api/launch")
def api_launch():
    """
    Launch AC with specific car+track via Content Manager protocol.
    Body: { "car_id": "...", "track_id": "..." }
    """
    data = request.json or {}
    car_id   = data.get("car_id", "")
    track_id = data.get("track_id", "")
    
    if not car_id or not track_id:
        return jsonify({"ok": False, "error": "Missing car_id or track_id"}), 400
    
    # Content Manager URI scheme
    uri = f"acmanager://race?car={car_id}&track={track_id}&mode=practice"
    
    try:
        os.startfile(uri)
        return jsonify({"ok": True, "uri": uri})
    except Exception as e:
        # Fallback: try launching AC directly via steam
        try:
            subprocess.Popen(
                ["steam", "steam://run/244210"],
                shell=True
            )
            return jsonify({"ok": True, "method": "steam_fallback"})
        except Exception as e2:
            return jsonify({"ok": False, "error": str(e2)}), 500

@app.get("/")
def root():
    return send_file(Path(__file__).parent / "index.html")

@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "version": "1.0.0"})

# ── Boot ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Open browser after short delay
    def open_browser():
        time.sleep(1.2)
        webbrowser.open("http://localhost:5827")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run silently — no debug output, no window
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    
    app.run(host="127.0.0.1", port=5827, debug=False, use_reloader=False)
