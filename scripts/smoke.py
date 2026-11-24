#!/usr/bin/env python3
"""서버가 실제로 동작하는지 빠르게 확인한다 (빈 임시 폴더에서 프로젝트·문서·이미지를 만들어 본다).

    python3 scripts/smoke.py            # 소스(server.py)로 확인
    python3 scripts/smoke.py --built    # scripts/build.py로 만든 배포판으로 확인
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 4391
BASE = f"http://127.0.0.1:{PORT}"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082")


def server_cmd(built):
    if not built:
        return [sys.executable, os.path.join(ROOT, "server.py"), "--serve"]
    if sys.platform == "darwin":
        return [os.path.join(ROOT, "dist", "기획위키.app", "Contents", "MacOS", "wiki-server"), "--serve"]
    return [os.path.join(ROOT, "build", "pyi", "GihoekWiki", "GihoekWiki.exe"), "--serve"]


def call(method, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ctype = r.headers.get("Content-Type", "")
            payload = r.read()
            return json.loads(payload) if "json" in ctype else payload
    except urllib.error.HTTPError as e:
        raise AssertionError(f"{method} {path} → {e.code} {e.read().decode('utf-8', 'replace')}") from None


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  ok", msg, flush=True)


def main():
    built = "--built" in sys.argv
    home = tempfile.mkdtemp(prefix="wiki-smoke-")
    env = dict(os.environ, GAMEWIKI_HOME=home, PORT=str(PORT), PYTHONUTF8="1")
    proc = subprocess.Popen(server_cmd(built), env=env, cwd=home)
    try:
        for _ in range(150):
            try:
                cfg = call("GET", "/api/config")
                break
            except Exception:  # noqa: BLE001
                if proc.poll() is not None:
                    raise AssertionError(f"서버가 바로 종료됨 (코드 {proc.returncode})") from None
                time.sleep(0.2)
        else:
            raise AssertionError("서버 응답 없음")
        print(f"서버 확인 (버전 {cfg['version']}, 저장 위치 {cfg['projectsDir']})")
        check(os.path.realpath(cfg["projectsDir"]).startswith(os.path.realpath(home)), "임시 폴더에 저장")
        check(b"<html" in call("GET", "/").lower(), "화면(index.html) 열림")
        check(isinstance(call("GET", "/templates.json"), list), "양식 목록 읽힘")

        proj = call("POST", "/api/projects", {"name": "테스트 프로젝트", "description": "스모크 테스트"})
        pid = quote(proj["id"], safe="")
        check(os.path.isfile(os.path.join(home, "projects", "테스트 프로젝트", "project.md")), "프로젝트 폴더 생성")

        img = call("POST", f"/api/p/{pid}/images", raw=PNG, headers={"Content-Type": "image/png", "X-Filename": "a.png"})
        check(call("GET", quote(img["url"])) == PNG, "이미지 업로드/읽기")

        doc = call("POST", f"/api/p/{pid}/docs", {
            "template": "note", "title": "1차 회의록",
            "fields": {"summary": "[[벨모어]] 이야기", "body": "본문 첫 줄\n\n- 항목", "gallery": [
                {"caption": "그림", "idea": "", "src": img["url"]}]}})
        check(doc["id"] == "문서/1차 회의록", f"문서 id ({doc['id']})")
        md_path = os.path.join(home, "projects", "테스트 프로젝트", "문서", "1차 회의록.md")
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
        check("../images/" in md and "## " in md, "md 파일 저장 (이미지 상대 경로)")

        docs = call("GET", f"/api/p/{pid}/docs")
        check(len(docs) == 1 and docs[0]["links"] == ["벨모어"], "문서 목록과 링크")

        did = quote(doc["id"], safe="")
        doc["title"] = "2차 회의록"
        renamed = call("PUT", f"/api/p/{pid}/docs/{did}", doc)
        check(renamed["id"] == "문서/2차 회의록" and not os.path.exists(md_path), "제목 바꾸면 파일 이름도 바뀜")
        check(renamed["fields"]["gallery"][0]["src"] == img["url"], "이미지 경로 유지")

        call("DELETE", f"/api/p/{pid}/docs/{quote(renamed['id'], safe='')}")
        trash = os.path.join(home, "projects", "테스트 프로젝트", ".wiki", "trash")
        check(len(os.listdir(trash)) == 1, "삭제하면 휴지통으로")
        check(call("GET", "/api/ping")["ok"] is True, "ping")
        print("통과")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
