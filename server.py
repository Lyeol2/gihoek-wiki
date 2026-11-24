#!/usr/bin/env python3
"""게임 기획 위키 로컬 서버.

설치 없이 Python 3 표준 라이브러리만 사용한다.
AI는 API 키 대신 로컬에 설치된 CLI(Claude Code, Codex 등)를 호출한다.

저장 구조 (사람이 읽고 고칠 수 있는 md 파일):

    projects/
      <프로젝트>/
        project.md            프로젝트 이름과 설명
        세계관/벨모어.md        양식별 폴더 / 문서 하나 = md 파일 하나
        images/               이미지
        .wiki/                되돌리기 기록, 휴지통 (앱 내부용)

    python3 server.py          # http://127.0.0.1:4173
    python3 server.py --open   # 브라우저까지 열기

데이터 위치
    소스로 실행하면 이 폴더(config.json, projects/)를 그대로 쓴다.
    배포용 앱(맥 .app, 윈도우 .exe)은 문서 폴더의 '기획위키'를 쓴다.
    GAMEWIKI_HOME 환경 변수로 바꿀 수 있다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

FROZEN = getattr(sys, "frozen", False)          # PyInstaller로 묶인 배포판인지
ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = getattr(sys, "_MEIPASS", ROOT)            # 코드와 화면 파일(public/)이 있는 곳
PUBLIC = os.path.join(APP_DIR, "public")


def documents_dir():
    if os.name == "nt":
        try:  # OneDrive로 옮겨진 '문서' 폴더도 찾는다
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:  # noqa: BLE001
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


HOME = os.path.abspath(os.path.expanduser(
    os.environ.get("GAMEWIKI_HOME") or (os.path.join(documents_dir(), "기획위키") if FROZEN else ROOT)))
DATA = os.path.join(ROOT, "data")                   # 예전 버전 저장소 (소스 실행 때만)
WORK = os.path.join(tempfile.gettempdir(), "gihoek-wiki-ai")
CONFIG_PATH = os.path.join(HOME, "config.json")


def read_version():
    try:
        with open(os.path.join(APP_DIR, "version.txt"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


VERSION = read_version()

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_UPLOAD = 25 * 1024 * 1024
MEMO_HEADING = "원본 메모"

os.makedirs(HOME, exist_ok=True)
os.makedirs(WORK, exist_ok=True)

DEFAULT_CONFIG = {
    "port": 4317 if FROZEN else 4173,  # 배포판과 소스 실행본이 서로의 서버를 잡지 않게
    "projectsDir": "projects",
    "ai": {
        "provider": "claude",
        "timeoutSec": 300,
        "providers": {
            "claude": {"label": "Claude Code",
                       "command": ["claude", "-p", "--tools", "", "--output-format", "text"]},
            "codex": {"label": "Codex",
                      "command": ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral",
                                  "--color", "never", "-o", "{out}", "-"]},
            "gemini": {"label": "Gemini CLI", "command": ["gemini", "-p", ""]},
        },
    },
}


# ================================================================ config

def merged(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merged(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config():
    """config.json이 없으면 기본값으로 만든다. 파일에 적힌 값이 기본값보다 우선이다."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return merged(DEFAULT_CONFIG, json.load(f))


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_templates():
    with open(os.path.join(PUBLIC, "templates.json"), encoding="utf-8") as f:
        return {t["id"]: t for t in json.load(f)}


def projects_dir():
    d = os.path.expanduser(load_config().get("projectsDir") or "projects")
    if not os.path.isabs(d):
        d = os.path.join(HOME, d)
    os.makedirs(d, exist_ok=True)
    return os.path.realpath(d)


# ================================================================ paths

BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def safe_name(s):
    s = BAD_CHARS.sub("_", (s or "").strip()).strip(". ")[:80].strip(". ")
    if s.split(".")[0].upper() in WIN_RESERVED:  # 윈도우에서 만들 수 없는 파일 이름
        s = "_" + s
    return s or "제목 없음"


def inside(base, rel):
    p = os.path.realpath(os.path.join(base, rel))
    if not (p == base or p.startswith(base + os.sep)):
        raise ValueError("잘못된 경로")
    return p


def project_path(pid):
    p = inside(projects_dir(), pid)
    if not os.path.isfile(os.path.join(p, "project.md")):
        raise FileNotFoundError(pid)
    return p


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ================================================================ frontmatter

def split_front(text):
    text = text.lstrip("﻿")
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if mm:
            k, v = mm.group(1), mm.group(2).strip()
            if v.startswith('"'):
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    v = v.strip('"')
            elif v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            meta[k] = v
    return meta, text[m.end():]


def front(meta):
    lines = ["---"]
    for k, v in meta.items():
        if v in (None, ""):
            continue
        s = str(v)
        if re.search(r"[:#\"'\n\[\]{}]|^\s|\s$|^[-?!&*]", s):
            s = json.dumps(s, ensure_ascii=False)
        lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines)


# ================================================================ md <-> fields

IMG_RE = re.compile(r'^\s*!\[(.*?)\]\((<[^>]*>|[^\s)]*)(?:\s+"((?:[^"\\]|\\.)*)")?\)\s*$')
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")


def is_empty(v):
    if v is None or v == "":
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, dict):
        return all(x in (None, "") for x in v.values())
    return False


def one_line(s):
    return re.sub(r"\s*\n\s*", " ", str(s or "")).strip()


def src_to_md(src, pid, ddir):
    prefix = f"/files/{pid}/"
    if src and src.startswith(prefix):
        return os.path.relpath(src[len(prefix):], ddir or ".").replace(os.sep, "/")
    return src or ""


def src_from_md(src, pid, ddir):
    if src.startswith("<") and src.endswith(">"):
        src = src[1:-1]
    src = unquote(src.strip())
    if not src or re.match(r"^[a-zA-Z][\w+.-]*:|^/", src):
        return src
    rel = os.path.normpath(os.path.join(ddir, src)).replace(os.sep, "/")
    return src if rel.startswith("..") else f"/files/{pid}/{rel}"


def img_md(v, pid, ddir):
    v = v or {}
    src = src_to_md(v.get("src", ""), pid, ddir)
    src = f"<{src}>" if (not src or " " in src) else src
    # 캡션 속 [[링크]]는 md 이미지 문법과 겹쳐 읽기 어려워지므로 글자만 남긴다
    cap = LINK_RE.sub(r"\1", one_line(v.get("caption"))).replace("[", "(").replace("]", ")")
    idea = one_line(v.get("idea")).replace('"', '\\"')
    return f"![{cap}]({src}" + (f' "{idea}"' if idea else "") + ")"


def img_from(line, pid, ddir):
    m = IMG_RE.match(line)
    if not m:
        return None
    out = {"caption": m.group(1).replace("\\]", "]"), "idea": (m.group(3) or "").replace('\\"', '"')}
    src = src_from_md(m.group(2), pid, ddir)
    if src:
        out["src"] = src
    return out


def items(text):
    out = []
    for line in text.splitlines():
        m = ITEM_RE.match(line)
        if m:
            out.append(m.group(1).strip())
        elif line.strip() and out:
            out[-1] += " " + line.strip()
    return out


def pair(s):
    m = re.match(r"^\*\*(.+?)\*\*\s*(?:[:：—–]\s*|-\s+)?(.*)$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^\[\[(.+?)\]\]\s*(?:[:：—–]\s*|-\s+)?(.*)$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    for sep in (": ", " — ", " - ", "："):
        if sep in s:
            a, b = s.split(sep, 1)
            return a.strip(), b.strip()
    return s.strip(), ""


def cell(s):
    return one_line(s).replace("|", "\\|")


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def field_md(f, v, pid, ddir):
    t = f["type"]
    if t in ("text", "longtext"):
        return str(v).strip()
    if t in ("list", "tags"):
        return "\n".join(f"- {one_line(x)}" for x in v)
    if t == "flow":
        return "\n".join(f"{i + 1}. {one_line(x)}" for i, x in enumerate(v))
    if t == "cards":
        return "\n".join(f"- **{one_line(c.get('title'))}** — {one_line(c.get('desc'))}" for c in v)
    if t == "keyvalue":
        keys = list(f.get("keys", [])) + [k for k in v if k not in f.get("keys", [])]
        return "\n".join(f"- **{k}**: {one_line(v[k])}" for k in keys if v.get(k))
    if t == "timeline":
        return "\n".join(f"- **{one_line(e.get('when'))}**: {one_line(e.get('what'))}" for e in v)
    if t == "relations":
        return "\n".join("- [[" + LINK_RE.sub(r"\1", one_line(r.get("target"))) + "]]: " + one_line(r.get("relation"))
                         for r in v)
    if t == "table":
        cols = f.get("columns") or [f"열{i + 1}" for i in range(max(len(r) for r in v))]
        lines = ["| " + " | ".join(cell(c) for c in cols) + " |", "|" + "|".join(" --- " for _ in cols) + "|"]
        for r in v:
            lines.append("| " + " | ".join(cell(r[i] if i < len(r) else "") for i in range(len(cols))) + " |")
        return "\n".join(lines)
    if t == "image":
        return img_md(v, pid, ddir)
    if t == "gallery":
        return "\n".join(img_md(g, pid, ddir) for g in v)
    return str(v)


def field_from(f, text, pid, ddir):
    t = f["type"]
    text = text.strip("\n")
    if t in ("text", "longtext"):
        return text.strip()
    if t in ("list", "tags", "flow"):
        return items(text)
    if t == "cards":
        return [dict(zip(("title", "desc"), pair(x))) for x in items(text)]
    if t == "keyvalue":
        return {k: v for k, v in (pair(x) for x in items(text))}
    if t == "timeline":
        return [dict(zip(("when", "what"), pair(x))) for x in items(text)]
    if t == "relations":
        return [dict(zip(("target", "relation"), pair(x))) for x in items(text)]
    if t == "table":
        rows = [split_row(l) for l in text.splitlines() if l.strip().startswith("|")]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "") for c in r)]
        if rows and f.get("columns") and [c.strip() for c in rows[0]] == f["columns"]:
            rows = rows[1:]
        n = len(f.get("columns") or [])
        return [(r + [""] * n)[:n] if n else r for r in rows]
    if t == "image":
        for line in text.splitlines():
            img = img_from(line, pid, ddir)
            if img:
                return img
        return {}
    if t == "gallery":
        return [g for g in (img_from(l, pid, ddir) for l in text.splitlines()) if g]
    return text


def doc_to_md(doc, t, pid, ddir):
    meta = {"template": t["id"], "status": doc.get("status") or "draft", "created": doc.get("created") or now_iso()}
    parts = [front(meta), "", f"# {one_line(doc.get('title')) or '제목 없음'}", ""]
    extras = doc.get("extra") or []
    for ex in extras:
        if not ex.get("heading") and ex.get("body", "").strip():
            parts += [ex["body"].strip(), ""]
    fields = doc.get("fields") or {}
    for f in t["fields"]:
        v = fields.get(f["key"])
        if is_empty(v):
            continue
        body = field_md(f, v, pid, ddir)
        if body.strip():
            parts += [f"## {f['label']}", "", body, ""]
    for ex in extras:
        if ex.get("heading"):
            parts += [f"## {ex['heading']}", "", (ex.get("body") or "").strip(), ""]
    memo = (doc.get("memo") or "").strip()
    if memo:
        parts += [f"## {MEMO_HEADING}", "", "````text", memo, "````", ""]
    return "\n".join(parts).rstrip() + "\n"


def md_to_doc(text, pid, doc_id, templates):
    meta, body = split_front(text)
    ddir = os.path.dirname(doc_id)
    by_folder = {t.get("folder"): t["id"] for t in templates.values()}
    tid = meta.get("template") or by_folder.get(doc_id.split("/")[0]) or "note"
    t = templates.get(tid) or templates["note"]

    title, pre, sections, cur, fence = None, [], [], None, None
    for line in body.replace("\r\n", "\n").split("\n"):
        target = cur["lines"] if cur else pre
        if fence:
            target.append(line)
            if line.strip().startswith(fence):
                fence = None
            continue
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            fence = m.group(1)
            target.append(line)
            continue
        if title is None and not sections and re.match(r"^#\s+\S", line):
            title = line[1:].strip()
            continue
        m = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if m:
            cur = {"heading": m.group(1).strip(), "lines": []}
            sections.append(cur)
            continue
        target.append(line)

    by_label = {f["label"]: f for f in t["fields"]}
    by_label.update({f["key"]: f for f in t["fields"]})
    fields, extra, memo = {}, [], ""
    for s in sections:
        txt = "\n".join(s["lines"]).strip("\n")
        if s["heading"] == MEMO_HEADING:
            memo = re.sub(r"^\s*(`{3,}|~{3,})[^\n]*\n|\n\s*(`{3,}|~{3,})\s*$", "", txt.strip())
            continue
        f = by_label.get(s["heading"])
        if f and f["key"] not in fields:
            fields[f["key"]] = field_from(f, txt, pid, ddir)
        else:
            extra.append({"heading": s["heading"], "body": txt.strip()})

    pre_txt = "\n".join(pre).strip()
    if pre_txt:
        if t["id"] == "note" and "body" not in fields:
            fields["body"] = pre_txt
        else:
            tf = next((f for f in t["fields"] if f["type"] in ("text", "longtext") and f["key"] not in fields), None)
            if tf:
                fields[tf["key"]] = pre_txt
            else:
                extra.insert(0, {"heading": "", "body": pre_txt})

    return {
        "id": doc_id,
        "template": t["id"],
        "title": title or meta.get("title") or os.path.basename(doc_id),
        "status": meta.get("status") or "draft",
        "created": meta.get("created") or "",
        "fields": fields,
        "extra": extra,
        "memo": memo,
    }


# ================================================================ projects

def read_project(pid):
    p = project_path(pid)
    with open(os.path.join(p, "project.md"), encoding="utf-8") as f:
        meta, body = split_front(f.read())
    body = re.sub(r"^#\s+.*\n?", "", body.strip(), count=1).strip()
    return {"id": pid, "name": meta.get("name") or pid, "description": body, "created": meta.get("created", ""), "path": p}


def write_project(path, name, description, created=None):
    with open(os.path.join(path, "project.md"), "w", encoding="utf-8") as f:
        f.write(front({"name": name, "created": created or now_iso()}) + f"\n\n# {name}\n\n{(description or '').strip()}\n")


def list_projects():
    base = projects_dir()
    out = []
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if name.startswith(".") or not os.path.isfile(os.path.join(p, "project.md")):
            continue
        info = read_project(name)
        docs = doc_files(p)
        mt = max([os.path.getmtime(os.path.join(p, d)) for d in docs] + [os.path.getmtime(os.path.join(p, "project.md"))])
        info.update({"docCount": len(docs), "updatedAt": int(mt * 1000)})
        out.append(info)
    out.sort(key=lambda x: x["updatedAt"], reverse=True)
    return out


def create_project(body):
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("프로젝트 이름을 적어주세요")
    pid = safe_name(name)
    p = inside(projects_dir(), pid)
    if os.path.exists(p):
        raise ValueError(f"'{pid}' 폴더가 이미 있어요")
    os.makedirs(os.path.join(p, "images"))
    write_project(p, name, body.get("description", ""))
    return read_project(pid)


def update_project(pid, body):
    cur = read_project(pid)
    write_project(cur["path"], body.get("name") or cur["name"], body.get("description", cur["description"]), cur["created"])
    return read_project(pid)


def reveal(path, select=False):
    """Finder / 탐색기에서 폴더를 열거나(select=True면) 파일을 선택해 보여준다."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if select else ["open", path])
    elif os.name == "nt":
        path = os.path.normpath(path)
        subprocess.Popen(f'explorer /select,"{path}"' if select else ["explorer", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if select else path])


# ================================================================ docs

def doc_files(proj):
    out = []
    for dirpath, dirnames, filenames in os.walk(proj):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "images"]
        for fn in filenames:
            if fn.endswith(".md") and not fn.startswith("."):
                rel = os.path.relpath(os.path.join(dirpath, fn), proj).replace(os.sep, "/")
                if rel != "project.md":
                    out.append(rel)
    return out


def doc_path(proj, doc_id):
    return inside(proj, doc_id + ".md")


def history_path(proj, doc_id):
    return os.path.join(proj, ".wiki", "history", doc_id.replace("/", "__") + ".json")


def read_doc(pid, doc_id, templates=None):
    proj = project_path(pid)
    templates = templates or load_templates()
    path = doc_path(proj, doc_id)
    with open(path, encoding="utf-8") as f:
        doc = md_to_doc(f.read(), pid, doc_id, templates)
    doc["updatedAt"] = int(os.path.getmtime(path) * 1000)
    hp = history_path(proj, doc_id)
    if os.path.exists(hp):
        with open(hp, encoding="utf-8") as f:
            doc["previous"] = json.load(f)
    return doc


def save_doc(pid, doc, old_id=None):
    proj = project_path(pid)
    templates = load_templates()
    t = templates.get(doc.get("template")) or templates["note"]
    folder = os.path.dirname(old_id) if old_id else t["folder"]
    name = safe_name(doc.get("title"))
    new_id = f"{folder}/{name}" if folder else name
    path = doc_path(proj, new_id)
    if new_id != old_id and os.path.exists(path):
        if old_id:
            raise ValueError(f"'{doc.get('title')}' 제목의 문서가 이미 있어요")
        n = 2
        while os.path.exists(doc_path(proj, f"{new_id} ({n})")):
            n += 1
        new_id = f"{new_id} ({n})"
        path = doc_path(proj, new_id)
    if old_id:
        try:
            doc.setdefault("created", read_doc(pid, old_id, templates).get("created"))
        except FileNotFoundError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(doc_to_md(doc, t, pid, os.path.dirname(new_id)))
    os.replace(tmp, path)

    hp = history_path(proj, new_id)
    if old_id and old_id != new_id:
        os.remove(doc_path(proj, old_id))
        old_hp = history_path(proj, old_id)
        if os.path.exists(old_hp):
            os.replace(old_hp, hp) if not os.path.exists(hp) else os.remove(old_hp)
    if "previous" in doc:
        if doc["previous"]:
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            with open(hp, "w", encoding="utf-8") as f:
                json.dump(doc["previous"], f, ensure_ascii=False)
        elif os.path.exists(hp):
            os.remove(hp)
    return read_doc(pid, new_id, templates)


def delete_doc(pid, doc_id):
    """완전히 지우지 않고 .wiki/trash로 옮긴다."""
    proj = project_path(pid)
    src = doc_path(proj, doc_id)
    trash = os.path.join(proj, ".wiki", "trash")
    os.makedirs(trash, exist_ok=True)
    dst = os.path.join(trash, time.strftime("%y%m%d-%H%M%S-") + doc_id.replace("/", "__") + ".md")
    shutil.move(src, dst)


def doc_summary(doc, templates):
    t = templates.get(doc.get("template"), {})
    fields = doc.get("fields", {})
    summary, cover = "", ""
    for f in t.get("fields", []):
        v = fields.get(f["key"])
        if not summary and f["type"] == "text" and isinstance(v, str):
            summary = v
        if not cover and f["type"] == "image" and isinstance(v, dict) and v.get("src"):
            cover = v["src"]
    if not cover:
        for f in t.get("fields", []):
            v = fields.get(f["key"])
            if f["type"] == "gallery" and v and isinstance(v[0], dict) and v[0].get("src"):
                cover = v[0]["src"]
                break
    raw = json.dumps([fields, doc.get("extra")], ensure_ascii=False)
    links = set(LINK_RE.findall(raw))
    for f in t.get("fields", []):
        if f["type"] == "relations":
            for r in fields.get(f["key"]) or []:
                if isinstance(r, dict) and r.get("target"):
                    links.add(LINK_RE.sub(r"\1", r["target"]))
    return {
        "id": doc["id"],
        "title": doc.get("title", ""),
        "template": doc.get("template"),
        "status": doc.get("status", "draft"),
        "updatedAt": doc.get("updatedAt"),
        "summary": LINK_RE.sub(r"\1", summary)[:200],
        "cover": cover,
        "links": sorted(links),
    }


def list_docs(pid):
    proj = project_path(pid)
    templates = load_templates()
    out = []
    for rel in doc_files(proj):
        try:
            out.append(doc_summary(read_doc(pid, rel[:-3], templates), templates))
        except Exception as e:  # noqa: BLE001  깨진 파일 하나 때문에 목록 전체가 안 뜨면 안 된다
            print(f"  skip {rel}: {e}", flush=True)
    out.sort(key=lambda d: d.get("updatedAt") or 0, reverse=True)
    return out


# ================================================================ 예전 JSON 저장소 → 프로젝트로 옮기기

def migrate_legacy():
    old_docs = os.path.join(DATA, "docs")
    if not os.path.isdir(old_docs):
        return
    files = [f for f in os.listdir(old_docs) if f.endswith(".json")]
    if not files:
        return
    pid = "샘플 프로젝트"
    p = os.path.join(projects_dir(), pid)
    if not os.path.exists(p):
        os.makedirs(os.path.join(p, "images"))
        write_project(p, pid, "예전 버전에서 옮겨온 문서들.")
    templates = load_templates()

    def fix(v):
        if isinstance(v, dict):
            v = {k: fix(x) for k, x in v.items()}
            src = v.get("src")
            if isinstance(src, str) and src.startswith("/images/"):
                name = src[len("/images/"):]
                old = os.path.join(DATA, "images", name)
                if os.path.exists(old):
                    shutil.copy2(old, os.path.join(p, "images", name))
                v["src"] = f"/files/{pid}/images/{name}"
            return v
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v

    for fn in files:
        with open(os.path.join(old_docs, fn), encoding="utf-8") as f:
            old = json.load(f)
        t = templates.get(old.get("template")) or templates["note"]
        doc = {"template": t["id"], "title": old.get("title"), "status": old.get("status"),
               "fields": fix(old.get("fields") or {}), "memo": old.get("memo", ""),
               "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((old.get("createdAt") or 0) / 1000 or time.time()))}
        save_doc(pid, doc)
    os.rename(old_docs, os.path.join(DATA, "docs-json-backup"))
    print(f"  예전 문서 {len(files)}개를 '{pid}' 프로젝트로 옮겼습니다.", flush=True)


# ================================================================ AI via CLI

SHAPES = {
    "text": '문자열',
    "longtext": '문자열 (문단은 "\\n\\n"으로 구분)',
    "list": '["문자열", ...]',
    "tags": '["키워드", ...] (각 1~3단어)',
    "flow": '["단계", ...] (순서대로)',
    "cards": '[{"title": "...", "desc": "..."}, ...]',
    "timeline": '[{"when": "시기", "what": "사건 1문장"}, ...]',
    "relations": '[{"target": "대상 이름", "relation": "관계 1구절"}, ...]',
    "image": '{"caption": "캡션", "idea": "들어갈 그림 설명 1문장"}',
    "gallery": '[{"caption": "캡션", "idea": "들어갈 그림 설명 1문장"}, ...]',
}


def field_spec(f):
    t = f["type"]
    if t == "keyvalue":
        shape = "{" + ", ".join(f'"{k}": "값"' for k in f.get("keys", [])) + "} (값은 짧게)"
    elif t == "table":
        shape = "[[" + ", ".join(f'"{c}"' for c in f.get("columns", [])) + "], ...] (헤더 없이 행만, 각 칸 짧게)"
    else:
        shape = SHAPES.get(t, "문자열")
    line = f'- "{f["key"]}" ({f["label"]}): {shape}'
    if f.get("max"):
        line += f" / 최대 {f['max']}개"
    if f.get("hint"):
        line += f" / {f['hint']}"
    return line


def strip_images(fields, template):
    """AI에 보낼 때 이미지 경로는 빼서 토큰 낭비를 막는다."""
    out = dict(fields or {})
    for f in template["fields"]:
        v = out.get(f["key"])
        if f["type"] == "image" and isinstance(v, dict):
            out[f["key"]] = {k: v.get(k, "") for k in ("caption", "idea")}
        elif f["type"] == "gallery" and isinstance(v, list):
            out[f["key"]] = [{k: (i or {}).get(k, "") for k in ("caption", "idea")} for i in v]
    return out


def build_prompt(template, memo, title, known_names, project, current=None, instruction=""):
    specs = "\n".join(field_spec(f) for f in template["fields"])
    known = ", ".join(known_names[:250]) or "(아직 없음)"
    parts = [
        f'너는 게임 기획 문서를 쓰는 시니어 게임 기획자다. "{template["name"]}" 양식을 채운다.',
        "",
        "작성 규칙",
        "- JSON 객체 하나만 출력한다. 코드블록, 설명, 인사말을 붙이지 않는다.",
        "- 짧고 읽기 쉽게 쓴다. 필드별 분량 제한을 지킨다. 같은 말을 반복하지 않는다.",
        '- "다양한", "풍부한", "독특한", "몰입감 있는" 같은 빈 수식어 대신 구체적인 명사, 행동, 숫자를 쓴다.',
        "- 메모에 적힌 내용이 최우선이다. 메모에 없는 부분은 메모의 방향과 어긋나지 않게 기획자로서 구체적으로 채운다.",
        "- 다른 위키 문서가 될 만한 고유명사(인물, 지역, 세력, 아이템, 퀘스트)는 [[이름]]으로 감싼다. 표, 목록, 본문 어디서든 같다.",
        f"- 이 세계에 이미 있는 이름(문서 제목, 다른 문서에서 언급된 이름): {known}",
        "- 같은 대상을 가리킬 때는 위 이름을 철자 그대로 다시 쓴다. 메모와 충돌하지 않으면 새 이름을 지어내기보다 위 이름을 우선 활용한다.",
        "- 강조는 꼭 필요한 단어에만 **굵게**를 쓴다.",
        "- 이미지는 만들 수 없으므로 이미지 필드에는 caption과 idea만 쓴다.",
        "- 한국어로 쓴다.",
    ]
    if project and project.get("description"):
        parts += ["", f"[프로젝트: {project['name']}]", project["description"][:2000]]
    parts += [
        "",
        "출력 형식",
        '{"title": "문서 제목", "fields": { ...아래 항목... }}',
        "",
        "fields 항목",
        specs,
    ]
    if current is not None:
        parts += [
            "",
            "[현재 문서]",
            json.dumps({"title": current.get("title", ""), "fields": strip_images(current.get("fields"), template)},
                       ensure_ascii=False),
            "",
            "[수정 요청]",
            instruction or "전체를 더 읽기 쉽고 구체적으로 다듬어라.",
            "",
            "현재 문서를 기준으로 수정 요청을 반영한 전체 JSON을 다시 출력한다. 요청과 관계없는 내용은 그대로 둔다.",
        ]
    if memo:
        parts += ["", "[메모]", memo]
    if title:
        parts += ["", f"문서 제목은 \"{title}\"로 한다."]
    return "\n".join(parts)


NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}  # 윈도우: 검은 콘솔 창이 뜨지 않게


def fix_path():
    """앱으로 실행하면 터미널의 PATH를 못 받아서 claude / codex를 못 찾는다. 흔한 설치 위치를 더해준다."""
    home = os.path.expanduser("~")
    parts = os.environ.get("PATH", "").split(os.pathsep)
    extra = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        extra = [os.path.join(home, ".local", "bin"), os.path.join(appdata, "npm") if appdata else ""]
    else:
        if sys.platform == "darwin" and FROZEN:
            try:
                out = subprocess.run([os.environ.get("SHELL") or "/bin/zsh", "-ilc", "printf '\\n__PATH__%s' \"$PATH\""],
                                     capture_output=True, text=True, timeout=8, stdin=subprocess.DEVNULL).stdout
                if "__PATH__" in out:
                    extra += out.rsplit("__PATH__", 1)[1].strip().split(":")
            except Exception:  # noqa: BLE001
                pass
        extra += [os.path.join(home, ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin",
                  os.path.join(home, ".npm-global", "bin"), os.path.join(home, ".bun", "bin")]
    for d in extra:
        if d and d not in parts and os.path.isdir(d):
            parts.append(d)
    os.environ["PATH"] = os.pathsep.join(p for p in parts if p)


def run_cli(prompt):
    cfg = load_config()
    ai = cfg["ai"]
    name = ai["provider"]
    prov = ai["providers"].get(name)
    if not prov:
        raise RuntimeError(f"config.json에 '{name}' 설정이 없습니다.")
    out_file = os.path.join(WORK, f"out-{uuid.uuid4().hex}.txt")
    cmd = [a.replace("{out}", out_file) for a in prov["command"]]
    exe = shutil.which(cmd[0])
    if not exe:
        raise RuntimeError(f"'{cmd[0]}' 명령을 찾을 수 없습니다. 설치되어 있고 PATH에 있는지 확인하세요.")
    cmd[0] = exe
    started = time.time()
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=ai.get("timeoutSec", 300), cwd=WORK, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{name} 응답이 {ai.get('timeoutSec', 300)}초 안에 오지 않았습니다.")
    text = ""
    if os.path.exists(out_file):
        with open(out_file, encoding="utf-8") as f:
            text = f.read()
        os.remove(out_file)
    if not text.strip():
        text = r.stdout
    if r.returncode != 0 and not text.strip():
        tail = (r.stderr or "").strip()[-800:]
        raise RuntimeError(f"{name} 실행 실패 (코드 {r.returncode})\n{tail}")
    print(f"  ai: {name} {time.time() - started:.1f}s", flush=True)
    return text


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s >= 0 and e > s:
            return json.loads(t[s:e + 1])
        raise


def generate(body):
    templates = load_templates()
    template = templates.get(body.get("template"))
    if not template:
        raise ValueError("알 수 없는 양식")
    pid = body.get("project")
    project, names = None, []
    if pid:
        project = read_project(pid)
        docs = list_docs(pid)
        titles = [d["title"] for d in docs if d["title"]]
        # 이미 다른 문서에서 언급된 이름도 같이 알려줘야 문서끼리 고유명사가 맞춰진다
        names = titles + sorted({l for d in docs for l in d["links"]} - set(titles))
    prompt = build_prompt(template, body.get("memo", "").strip(), body.get("title", "").strip(), names, project,
                          body.get("current"), body.get("instruction", "").strip())
    text = run_cli(prompt)
    try:
        data = parse_json(text)
    except Exception:
        raise RuntimeError("AI 응답을 JSON으로 읽지 못했습니다.\n\n" + text[:1500])
    if "fields" not in data:
        data = {"title": data.get("title", ""), "fields": data}
    return data


# ================================================================ HTTP

LAST_PING = [time.time()]


class Handler(BaseHTTPRequestHandler):
    server_version = "GihoekWiki/" + VERSION

    def log_message(self, fmt, *args):
        line = fmt % args
        if "/api/" in line or "code " in line:
            sys.stdout.write("  " + line + "\n")

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path):
        if not path or not os.path.isfile(path):
            return self.send_error(404)
        ctype = {
            ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("파일이 너무 큽니다 (25MB 제한)")
        return self.rfile.read(n) if n else b""

    def json_body(self):
        raw = self.body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def route(self, method):
        raw = urlparse(self.path).path
        # 먼저 '/'로 나눈 뒤 조각마다 디코딩한다 → 문서 id 안의 '/'(%2F)가 경로로 쪼개지지 않는다
        seg = [unquote(s) for s in raw.split("/") if s]
        try:
            if seg[:1] == ["api"]:
                return self.api(method, seg[1:])
            if method != "GET":
                return self.send_error(405)
            if seg[:1] == ["files"] and len(seg) >= 3:
                proj = project_path(seg[1])
                p = inside(proj, "/".join(seg[2:]))
                if os.path.splitext(p)[1].lower() not in IMAGE_EXT:
                    return self.send_error(404)
                return self.send_file(p)
            rel = "/".join(seg) or "index.html"
            return self.send_file(inside(os.path.realpath(PUBLIC), rel))
        except FileNotFoundError:
            self.send_json({"error": "찾을 수 없습니다"}, 404)
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            self.send_json({"error": str(e)}, 500)

    def api(self, method, s):
        head = s[0] if s else ""

        if head == "projects":
            if len(s) == 1 and method == "GET":
                return self.send_json(list_projects())
            if len(s) == 1 and method == "POST":
                return self.send_json(create_project(self.json_body()), 201)
            if len(s) == 2 and method == "GET":
                return self.send_json(read_project(s[1]))
            if len(s) == 2 and method == "PUT":
                return self.send_json(update_project(s[1], self.json_body()))

        if head == "p" and len(s) >= 3:
            pid, what = s[1], s[2]
            if what == "docs":
                if len(s) == 3 and method == "GET":
                    return self.send_json(list_docs(pid))
                if len(s) == 3 and method == "POST":
                    body = self.json_body()
                    body.setdefault("created", now_iso())
                    return self.send_json(save_doc(pid, body), 201)
                doc_id = s[3]
                if method == "GET":
                    return self.send_json(read_doc(pid, doc_id))
                if method == "PUT":
                    return self.send_json(save_doc(pid, self.json_body(), old_id=doc_id))
                if method == "DELETE":
                    delete_doc(pid, doc_id)
                    return self.send_json({"ok": True})
            if what == "images" and method == "POST":
                proj = project_path(pid)
                name = unquote(self.headers.get("X-Filename") or "image.png")
                ext = os.path.splitext(name)[1].lower() or ".png"
                if ext not in IMAGE_EXT:
                    raise ValueError("png, jpg, gif, webp만 올릴 수 있습니다")
                fname = time.strftime("%y%m%d") + "-" + uuid.uuid4().hex[:10] + ext
                os.makedirs(os.path.join(proj, "images"), exist_ok=True)
                with open(os.path.join(proj, "images", fname), "wb") as f:
                    f.write(self.body())
                return self.send_json({"url": f"/files/{pid}/images/{fname}"})
            if what == "reveal" and method == "POST":
                proj = project_path(pid)
                target = proj
                rel = self.json_body().get("doc")
                if rel:
                    reveal(doc_path(proj, rel), select=True)
                    return self.send_json({"ok": True})
                reveal(target)
                return self.send_json({"ok": True})

        if head == "ping":
            LAST_PING[0] = time.time()
            return self.send_json({"ok": True, "version": VERSION})

        if head == "generate" and method == "POST":
            return self.send_json(generate(self.json_body()))

        if head == "config":
            cfg = load_config()
            if method == "PUT":
                want = self.json_body().get("provider")
                if want not in cfg["ai"]["providers"]:
                    raise ValueError("알 수 없는 AI")
                cfg["ai"]["provider"] = want
                save_config(cfg)
            ai = cfg["ai"]
            return self.send_json({
                "provider": ai["provider"],
                "version": VERSION,
                "projectsDir": projects_dir(),
                "configPath": CONFIG_PATH,
                "providers": [{"id": k, "label": v.get("label", k), "installed": bool(shutil.which(v["command"][0]))}
                              for k, v in ai["providers"].items()],
            })
        self.send_json({"error": "없는 API"}, 404)

    def do_GET(self):
        self.route("GET")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")


def setup_logging():
    """창 없는 배포판(윈도우)은 stdout이 없으므로 로그 파일로 보낸다."""
    if sys.stdout is None or sys.stderr is None:
        log_dir = os.path.join(HOME, ".logs")
        os.makedirs(log_dir, exist_ok=True)
        f = open(os.path.join(log_dir, "server.log"), "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def make_server(port):
    """정한 포트가 다른 프로그램에 쓰이고 있으면 빈 포트를 쓴다."""
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def start(port=None):
    """서버를 백그라운드 스레드로 띄우고 (httpd, url)을 돌려준다."""
    setup_logging()
    fix_path()
    cfg = load_config()
    if not FROZEN:
        migrate_legacy()
    port = int(port or os.environ.get("PORT") or cfg.get("port", 4173))
    httpd = make_server(port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"기획위키 {VERSION} 실행 중: {url}  (AI: {cfg['ai']['provider']} CLI, 프로젝트: {projects_dir()})", flush=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, url


def main():
    if FROZEN and os.name == "nt" and "--serve" not in sys.argv:
        import launcher_win  # 윈도우 배포판: 서버 + 앱 창
        return launcher_win.run()
    httpd, url = start()
    print("종료: Ctrl+C", flush=True)
    if "--open" in sys.argv:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
