"""윈도우 배포판 실행기.

서버를 띄우고 Edge(없으면 Chrome)의 '앱 모드' 창으로 연다. 주소창이 없는 일반 프로그램 창처럼 보인다.
창을 닫으면 서버도 꺼진다. 이미 켜져 있으면 창만 하나 더 연다.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

import server

TITLE = "기획위키"


def message(text, error=False):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
    except Exception:  # noqa: BLE001
        pass


def ping(url):
    try:
        with urllib.request.urlopen(url + "/api/ping", timeout=1) as r:
            return json.loads(r.read().decode("utf-8")).get("ok") is True
    except Exception:  # noqa: BLE001
        return False


def find_browser():
    """Edge는 윈도우 10/11에 기본으로 들어 있다."""
    candidates = []
    try:
        import winreg
        for exe in ("msedge.exe", "chrome.exe"):
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        candidates.append(winreg.QueryValue(k, None))
                except OSError:
                    pass
    except ImportError:
        pass
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [os.path.join(base, r"Microsoft\Edge\Application\msedge.exe"),
                           os.path.join(base, r"Google\Chrome\Application\chrome.exe")]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def open_window(url):
    """앱 창을 연다. 창이 닫힐 때까지 기다릴 수 있으면 그 프로세스를 돌려준다."""
    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return None
    profile = os.path.join(os.environ.get("LOCALAPPDATA") or server.HOME, "GihoekWiki", "window")
    os.makedirs(profile, exist_ok=True)
    return subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                             "--no-default-browser-check", "--disable-sync", "--window-size=1360,880"])


def wait_until_idle(limit=150):
    """창 프로세스를 못 잡았을 때: 화면이 보내는 신호(ping)가 끊기면 끈다."""
    while time.time() - server.LAST_PING[0] < limit:
        time.sleep(5)


def run():
    try:
        cfg = server.load_config()
        url = f"http://127.0.0.1:{cfg.get('port', 4173)}"
        if ping(url):  # 이미 켜져 있다 → 창만 하나 더
            open_window(url)
            return
        httpd, url = server.start()
        for _ in range(50):
            if ping(url):
                break
            time.sleep(0.1)
        started = time.time()
        proc = open_window(url)
        if proc:
            proc.wait()
            if time.time() - started < 5:
                # 이미 떠 있던 Edge에 창을 넘기고 바로 끝난 경우
                server.LAST_PING[0] = time.time()
                wait_until_idle()
        else:
            server.LAST_PING[0] = time.time()
            wait_until_idle()
        httpd.shutdown()
    except Exception as e:  # noqa: BLE001
        log = os.path.join(server.HOME, ".logs", "server.log")
        message(f"기획위키를 시작하지 못했어요.\n\n{e}\n\n로그: {log}", error=True)
        sys.exit(1)
