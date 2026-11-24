"""자동 업데이트: GitHub 릴리즈에서 새 버전을 확인하고, 받아서 설치한 뒤 앱을 다시 연다.

배포판(맥 .app, 윈도우 설치형)에서만 동작한다. 소스 실행이나 윈도우 무설치판은 릴리즈 페이지를 안내한다.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

REPO = "Lyeol2/gihoek-wiki"
RELEASES = f"https://github.com/{REPO}/releases"
CHECK_EVERY = 3600
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

_lock = threading.Lock()
_cache = {"at": 0, "latest": None}
status = {"state": "idle", "error": ""}   # idle → downloading → installing → restarting / error


def parse(v):
    nums = re.findall(r"\d+", (v or "").split("-")[0])
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def curl():
    return shutil.which("curl")


def latest_version(force=False):
    """releases/latest 가 최신 태그 주소로 넘겨주는 것을 이용한다 (API 횟수 제한이 없다)."""
    if not force and _cache["latest"] and time.time() - _cache["at"] < CHECK_EVERY:
        return _cache["latest"]
    url = ""
    try:
        if curl():  # 시스템 인증서를 쓰는 curl이 묶음 파이썬의 SSL보다 믿을 만하다
            url = subprocess.run([curl(), "-fsSL", "-o", os.devnull, "-w", "%{url_effective}", "--max-time", "10",
                                  RELEASES + "/latest"], capture_output=True, text=True, timeout=15, **NO_WINDOW).stdout
        else:
            with urllib.request.urlopen(RELEASES + "/latest", timeout=10) as r:
                url = r.geturl()
    except Exception:  # noqa: BLE001  오프라인이면 조용히 넘어간다
        return _cache["latest"]
    m = re.search(r"/releases/tag/v?([\w.\-]+)$", url.strip())
    if m:
        _cache.update(at=time.time(), latest=m.group(1))
    return _cache["latest"]


def download(url, dest):
    if not url.startswith(f"https://github.com/{REPO}/"):
        raise RuntimeError("알 수 없는 다운로드 주소")
    if curl():
        r = subprocess.run([curl(), "-fL", "--retry", "2", "-o", dest, url], capture_output=True, text=True,
                           timeout=900, **NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("새 버전을 내려받지 못했어요.\n" + (r.stderr or "").strip()[-300:])
    else:
        urllib.request.urlretrieve(url, dest)  # noqa: S310


# ------------------------------------------------------------------ 설치 방식 판단

def mac_app_path():
    """…/기획위키.app/Contents/MacOS/wiki-server → …/기획위키.app"""
    p = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(sys.executable))))
    return p if p.endswith(".app") else None


def install_kind():
    """(종류, 설치할 수 없는 이유)"""
    if not getattr(sys, "frozen", False):
        return None, "소스로 실행 중이라 자동 설치는 하지 않아요. git pull로 받아 주세요."
    if sys.platform == "darwin":
        app = mac_app_path()
        if not app:
            return None, "앱 위치를 찾지 못했어요."
        if "/AppTranslocation/" in app or app.startswith("/Volumes/"):
            return None, "기획위키를 Applications(응용 프로그램) 폴더로 옮긴 뒤 다시 실행하면 자동으로 업데이트할 수 있어요."
        if not os.access(os.path.dirname(app), os.W_OK):
            return None, "앱이 있는 폴더에 쓸 권한이 없어요. 릴리즈 페이지에서 새 버전을 받아 주세요."
        return "mac", ""
    if os.name == "nt":
        if glob.glob(os.path.join(os.path.dirname(sys.executable), "unins*.exe")):
            return "windows", ""
        return None, "무설치(portable) 버전은 릴리즈 페이지에서 새 zip을 받아 주세요."
    return None, "지원하지 않는 환경이에요."


def info(current, force=False):
    latest = latest_version(force)
    kind, why = install_kind()
    return {
        "current": current,
        "latest": latest,
        "available": bool(latest) and parse(latest) > parse(current) and current != "dev",
        "canInstall": bool(kind),
        "reason": why,
        "url": f"{RELEASES}/tag/v{latest}" if latest else RELEASES,
        "state": status["state"],
        "error": status["error"],
    }


# ------------------------------------------------------------------ 설치

MAC_SWAP = """#!/bin/bash
# 앱이 꺼지길 기다렸다가 새 앱으로 바꾸고 다시 연다
APP="$1"; NEW="$2"; APP_PID="$3"; SRV_PID="$4"
kill "$APP_PID" 2>/dev/null
for i in $(seq 1 50); do kill -0 "$APP_PID" 2>/dev/null || break; sleep 0.2; done
kill "$SRV_PID" 2>/dev/null
sleep 0.5
OLD="$APP.old"
rm -rf "$OLD"
if mv "$APP" "$OLD" && mv "$NEW" "$APP"; then rm -rf "$OLD"; else [ -d "$APP" ] || mv "$OLD" "$APP"; fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
open "$APP"
rm -f "$0"
"""


def install_mac(version, work):
    app = mac_app_path()
    dmg = os.path.join(work, "update.dmg")
    download(f"{RELEASES}/download/v{version}/gihoek-wiki-{version}-mac.dmg", dmg)
    status["state"] = "installing"
    mnt = os.path.join(work, "mnt")
    os.makedirs(mnt, exist_ok=True)
    subprocess.run(["hdiutil", "attach", dmg, "-nobrowse", "-readonly", "-mountpoint", mnt, "-quiet"], check=True)
    new = app + ".new"
    try:
        found = glob.glob(os.path.join(mnt, "*.app"))
        if not found:
            raise RuntimeError("내려받은 파일에 앱이 없어요.")
        shutil.rmtree(new, ignore_errors=True)
        subprocess.run(["ditto", found[0], new], check=True)
    finally:
        subprocess.run(["hdiutil", "detach", mnt, "-quiet"], check=False)
    script = os.path.join(work, "swap.sh")
    with open(script, "w", encoding="utf-8") as f:
        f.write(MAC_SWAP)
    os.chmod(script, 0o755)
    status["state"] = "restarting"
    time.sleep(1.5)  # 화면이 '다시 여는 중' 상태를 읽어갈 시간
    subprocess.Popen(["/bin/bash", script, app, new, str(os.getppid()), str(os.getpid())],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


WIN_SWAP = """@echo off
chcp 65001 >nul
ping -n 3 127.0.0.1 >nul
taskkill /F /PID {pid} >nul 2>&1
ping -n 2 127.0.0.1 >nul
"{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
start "" "{exe}" --no-window
del "{setup}" >nul 2>&1
del "%~f0"
"""


def install_windows(version, work):
    setup = os.path.join(work, "setup.exe")
    download(f"{RELEASES}/download/v{version}/gihoek-wiki-{version}-windows-setup.exe", setup)
    status["state"] = "installing"
    bat = os.path.join(work, "update.cmd")
    with open(bat, "w", encoding="utf-8") as f:
        f.write(WIN_SWAP.format(pid=os.getpid(), setup=setup, exe=sys.executable))
    status["state"] = "restarting"
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW: 우리 프로세스가 죽어도 계속 돈다
    subprocess.Popen(["cmd", "/c", bat], creationflags=0x00000008 | 0x00000200 | 0x08000000,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def _run(current):
    try:
        latest = latest_version(force=True)
        if not latest or parse(latest) <= parse(current):
            raise RuntimeError("이미 최신 버전이에요.")
        kind, why = install_kind()
        if not kind:
            raise RuntimeError(why)
        work = tempfile.mkdtemp(prefix="gihoek-wiki-update-")
        print(f"  update: {current} → {latest}", flush=True)
        (install_mac if kind == "mac" else install_windows)(latest, work)
    except Exception as e:  # noqa: BLE001
        print(f"  update 실패: {e}", flush=True)
        status.update(state="error", error=str(e))


def start_install(current):
    with _lock:
        if status["state"] in ("downloading", "installing", "restarting"):
            return
        status.update(state="downloading", error="")
    threading.Thread(target=_run, args=(current,), daemon=True).start()
