"""Start YOUR Chrome with a debugging port so secjobs can attach to it.

    secjobs chrome

Chrome launched this way is not marked as automated (no `navigator.webdriver`,
no --enable-automation), which is what hCaptcha keys on. secjobs then attaches
over the local debugging port, fills the form, and you click Submit.

Uses a dedicated profile folder (data/chrome_profile). Chrome refuses remote
debugging on your default profile, so this is required - sign in once and it
persists.
"""
import os, shutil, subprocess, sys, time
import requests
from .config import ROOT

PORT = 9222
PROFILE = ROOT / "data" / "chrome_profile"

_WIN = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
_MAC = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
_LINUX = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def find_chrome() -> str | None:
    cands = _WIN if sys.platform.startswith("win") else _MAC if sys.platform == "darwin" else _LINUX
    for c in cands:
        if os.path.isfile(c):
            return c
        w = shutil.which(c)
        if w:
            return w
    return None


def is_running() -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{PORT}/json/version", timeout=1).ok
    except Exception:
        return False


def launch(url: str = "https://jobs.lever.co") -> None:
    if is_running():
        print(f"Chrome already listening on port {PORT}."); return
    exe = find_chrome()
    if not exe:
        raise SystemExit("Chrome not found. Install Google Chrome or set the path in secjobs/chrome.py.")
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
            "--no-first-run", "--no-default-browser-check", "--start-maximized", url]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if is_running():
            break
        time.sleep(0.5)
    print(f"Chrome started ({exe}) on port {PORT}, profile {PROFILE}.")
    print("Leave it open. Now run:  secjobs apply --id <id>   (or --clean-only, etc.)")
