"""기획위키 MCP 서버 — 터미널의 Claude Code / Codex가 위키 문서를 직접 읽고 쓰게 한다.

실행: wiki-server --mcp (배포판) / python3 server.py --mcp (소스)
표준 입출력으로 JSON-RPC(줄 단위)를 주고받는다. 앱이 꺼져 있어도 같은 프로젝트 폴더를 읽고 쓴다.
"""
import json
import os
import sys

import server as W

PROTOCOL = "2025-06-18"

INSTRUCTIONS = """기획위키는 게임 기획 문서를 프로젝트별 md 파일로 저장하는 위키다. 사람은 기획위키 앱으로 보고 고친다.
- 문서를 만들거나 고치기 전에 wiki_templates로 양식의 항목(key)과 값 모양을 확인한다.
- 문서 본문에서 [[문서 제목]]은 다른 문서로 가는 위키 링크, **굵게**는 강조다. 이미 있는 문서 이름을 링크로 걸면 좋다.
- 한국어로, 짧고 훑어보기 좋게 쓴다. 메모에 없는 내용을 지어내지 않는다.
- 이미지 칸에는 그림을 넣을 수 없다. caption과 idea(들어갈 그림 설명)만 적는다. 이미 들어간 그림은 그대로 남는다.
- 맵(type map)은 사람이 앱에서 그린다. 요청받지 않으면 건드리지 않는다.
- 고칠 때는 wiki_update로 바꿀 항목만 보낸다. 앱이 고치기 전 버전을 기록해 두어서 사람이 되돌릴 수 있다."""


# ------------------------------------------------------------ 도우미

def find_project(name):
    name = (name or "").strip()
    projects = W.list_projects()
    if not name:
        if len(projects) == 1:
            return projects[0]["id"]
        raise ValueError("project를 정해주세요. 있는 프로젝트: " + ", ".join(p["id"] for p in projects))
    for p in projects:
        if name in (p["id"], p["name"]):
            return p["id"]
    for p in projects:
        if name.lower() in (p["id"].lower(), p["name"].lower()):
            return p["id"]
    raise ValueError(f"'{name}' 프로젝트가 없어요. 있는 프로젝트: " + ", ".join(p["id"] for p in projects))


def find_doc(pid, name):
    name = (name or "").strip().removesuffix(".md")
    docs = W.list_docs(pid)
    for d in docs:
        if name == d["id"]:
            return d["id"]
    hits = [d for d in docs if name in (d["title"], d["id"].split("/")[-1])]
    if len(hits) == 1:
        return hits[0]["id"]
    if len(hits) > 1:
        raise ValueError(f"'{name}' 문서가 여러 개예요. id로 정해주세요: " + ", ".join(d["id"] for d in hits))
    raise ValueError(f"'{name}' 문서가 없어요. wiki_list로 목록을 보세요.")


def template_of(tid):
    templates = W.load_templates()
    if tid not in templates:
        raise ValueError(f"'{tid}' 양식이 없어요. 있는 양식: " + ", ".join(templates))
    return templates[tid]


def lines_of(v):
    if isinstance(v, str):
        return [x.strip(" -•\t") for x in v.splitlines() if x.strip(" -•\t")]
    return v if isinstance(v, list) else [v]


def coerce(f, v):
    """AI가 보낸 값을 양식이 기대하는 모양으로 맞춘다. 웬만한 실수는 받아준다."""
    t = f["type"]
    if t in ("text", "longtext"):
        return v if isinstance(v, str) else "\n".join(map(str, lines_of(v)))
    if t in ("list", "tags", "flow"):
        return [str(x) for x in lines_of(v) if str(x).strip()]
    pairs = {"cards": ("title", "desc"), "timeline": ("when", "what"), "relations": ("target", "relation")}
    if t in pairs:
        a, b = pairs[t]
        out = []
        for x in lines_of(v):
            if isinstance(x, dict):
                out.append({a: str(x.get(a, "")), b: str(x.get(b, ""))})
            else:
                k, d = W.pair(str(x)) if "|" not in str(x) else [s.strip() for s in str(x).split("|", 1)]
                out.append({a: k, b: d})
        return out
    if t == "keyvalue":
        if isinstance(v, dict):
            return {str(k): str(x) for k, x in v.items()}
        return {k: d for k, d in (W.pair(str(x)) for x in lines_of(v))}
    if t == "table":
        cols = f.get("columns") or []
        rows = []
        for r in lines_of(v):
            if isinstance(r, dict):
                r = [r.get(c, "") for c in cols]
            elif isinstance(r, str):
                r = W.split_row(r) if "|" in r else [r]
            r = [str(c) for c in r]
            rows.append((r + [""] * len(cols))[:len(cols)] if cols else r)
        return rows
    if t == "image":
        v = v if isinstance(v, dict) else {"caption": str(v)}
        return {k: str(v[k]) for k in ("caption", "idea") if v.get(k)}
    if t == "gallery":
        return [coerce({"type": "image"}, x) for x in lines_of(v)]
    if t == "map":
        if not isinstance(v, dict):
            raise ValueError(f"'{f['key']}'는 맵이에요. {{\"rows\": [\"...\"], \"markers\": [...]}} 모양으로 보내주세요.")
        return W.map_from(f, W.map_md(f, v))
    return v


def merge_field(f, old, new):
    """이미지 칸은 사람이 넣은 그림(src)을 지키고 글만 바꾼다."""
    if f["type"] == "image":
        return {**(old or {}), **new} if (old or {}).get("src") else new
    if f["type"] == "gallery":
        old = old or []
        return [{**(old[i] if i < len(old) else {}), **n} for i, n in enumerate(new)] + \
               [o for o in old[len(new):] if o.get("src")]
    return new


def apply_fields(t, doc, fields):
    if not isinstance(fields, dict):
        raise ValueError("fields는 {항목 key: 값} 모양이어야 해요.")
    by = {f["key"]: f for f in t["fields"]}
    by.update({f["label"]: f for f in t["fields"]})
    unknown = [k for k in fields if k not in by]
    if unknown:
        raise ValueError(f"'{t['name']}' 양식에 없는 항목: {', '.join(unknown)}. 있는 항목: " +
                         ", ".join(f["key"] for f in t["fields"]))
    out = dict(doc.get("fields") or {})
    for k, v in fields.items():
        f = by[k]
        if v is None or v == "" or v == []:
            out.pop(f["key"], None)
        else:
            out[f["key"]] = merge_field(f, out.get(f["key"]), coerce(f, v))
    return out


def md_text(pid, doc_id):
    with open(W.doc_path(W.project_path(pid), doc_id), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------ 도구

def t_projects(a):
    return [{"id": p["id"], "name": p["name"], "docs": p["docCount"], "description": p["description"][:300]}
            for p in W.list_projects()]


def t_templates(a):
    out = []
    for t in W.load_templates().values():
        if a.get("template") and a["template"] != t["id"]:
            continue
        item = {"id": t["id"], "name": t["name"], "folder": t["folder"], "description": t["description"],
                "single": bool(t.get("single"))}
        if a.get("template") or a.get("detail"):
            item["fields"] = [W.field_spec(f) if f["type"] != "map" else
                              f'- "{f["key"]}" ({f["label"]}): 맵 ({"옆에서 본 플랫포밍" if f.get("mode") == "side" else "위에서 본 지도"}). 사람이 앱에서 그린다.'
                              for f in t["fields"]]
        out.append(item)
    return out


def t_list(a):
    pid = find_project(a.get("project"))
    templates = W.load_templates()
    docs = W.list_docs(pid)
    if a.get("template"):
        docs = [d for d in docs if d["template"] == a["template"]]
    return {"project": pid, "docs": [{"id": d["id"], "title": d["title"], "template": d["template"],
                                      "status": d["status"], "summary": d["summary"],
                                      "kind": templates.get(d["template"], {}).get("name", "")} for d in docs]}


def t_read(a):
    pid = find_project(a.get("project"))
    did = find_doc(pid, a.get("doc"))
    return f"[project: {pid} / doc id: {did}]\n\n" + md_text(pid, did)


def t_search(a):
    pid = find_project(a.get("project"))
    words = [w.lower() for w in str(a.get("query", "")).split() if w]
    if not words:
        raise ValueError("query를 적어주세요")
    proj = W.project_path(pid)
    hits = []
    for rel in W.doc_files(proj):
        text = open(os.path.join(proj, rel), encoding="utf-8").read()
        low = text.lower()
        if not all(w in low for w in words):
            continue
        lines = [l.strip() for l in text.splitlines() if any(w in l.lower() for w in words)]
        hits.append({"id": rel[:-3], "lines": lines[:5]})
    return {"project": pid, "query": a.get("query"), "hits": hits[:30]}


def t_create(a):
    pid = find_project(a.get("project"))
    t = template_of(a.get("template"))
    title = str(a.get("title") or "").strip()
    if not title:
        raise ValueError("title을 적어주세요")
    if t.get("single"):
        same = [d["id"] for d in W.list_docs(pid) if d["template"] == t["id"]]
        if same:
            raise ValueError(f"'{t['name']}'은 프로젝트에 하나만 두는 핵심 문서예요. 이미 있는 문서를 wiki_update로 고쳐주세요: {same[0]}")
    doc = {"template": t["id"], "title": title, "status": a.get("status") or "draft", "memo": a.get("memo") or "", "fields": {}}
    doc["fields"] = apply_fields(t, doc, a.get("fields") or {})
    saved = W.save_doc(pid, doc)
    return f"만들었어요: {saved['id']}\n\n" + md_text(pid, saved["id"])


def t_update(a):
    pid = find_project(a.get("project"))
    did = find_doc(pid, a.get("doc"))
    doc = W.read_doc(pid, did)
    doc.pop("previous", None)
    t = template_of(doc["template"])
    if a.get("fields"):
        doc["fields"] = apply_fields(t, doc, a["fields"])
    if a.get("title"):
        doc["title"] = str(a["title"]).strip()
    if a.get("status"):
        doc["status"] = a["status"]
    saved = W.save_doc(pid, doc, old_id=did)
    return f"고쳤어요: {saved['id']} (고치기 전 버전은 앱의 '기록'에서 되돌릴 수 있어요)\n\n" + md_text(pid, saved["id"])


def t_new_project(a):
    out = W.create_project({"name": a.get("name"), "description": a.get("description", "")})
    return {"id": out["id"], "name": out["name"], "path": out["path"]}


STATUS = {"type": "string", "enum": ["draft", "review", "final"], "description": "draft 초안 / review 검토 중 / final 확정"}
PROJECT = {"type": "string", "description": "프로젝트 id나 이름. 프로젝트가 하나뿐이면 비워도 된다."}
TOOLS = [
    ("wiki_projects", "기획위키 프로젝트 목록.", {}, [], t_projects),
    ("wiki_templates", "문서 양식 목록. template을 주면 그 양식의 항목(key)과 값 모양까지 보여준다. 문서를 만들기 전에 꼭 본다.",
     {"template": {"type": "string", "description": "양식 id (예: world, character, level)"},
      "detail": {"type": "boolean", "description": "true면 모든 양식의 항목까지"}}, [], t_templates),
    ("wiki_list", "프로젝트의 문서 목록 (id, 제목, 양식, 상태, 요약).",
     {"project": PROJECT, "template": {"type": "string", "description": "이 양식의 문서만"}}, [], t_list),
    ("wiki_read", "문서 하나를 md 원문으로 읽는다.",
     {"project": PROJECT, "doc": {"type": "string", "description": "문서 id(예: 세계관/벨모어) 또는 제목"}}, ["doc"], t_read),
    ("wiki_search", "프로젝트의 모든 문서에서 낱말을 찾는다 (띄어쓴 낱말이 모두 들어간 문서).",
     {"project": PROJECT, "query": {"type": "string"}}, ["query"], t_search),
    ("wiki_create", "새 문서를 만든다. fields는 wiki_templates에서 본 항목 key와 값 모양을 따른다.",
     {"project": PROJECT, "template": {"type": "string", "description": "양식 id"}, "title": {"type": "string"},
      "fields": {"type": "object", "description": "{항목 key: 값}"}, "status": STATUS,
      "memo": {"type": "string", "description": "근거가 된 원본 메모 (문서 맨 아래 '원본 메모'에 남는다)"}},
     ["template", "title", "fields"], t_create),
    ("wiki_update", "문서를 고친다. 보낸 항목만 바뀌고 나머지는 그대로. 빈 값을 보내면 그 항목을 지운다. 제목을 바꾸면 파일 이름도 바뀐다.",
     {"project": PROJECT, "doc": {"type": "string", "description": "문서 id 또는 제목"},
      "fields": {"type": "object", "description": "{항목 key: 새 값}"}, "title": {"type": "string"}, "status": STATUS},
     ["doc"], t_update),
    ("wiki_new_project", "새 프로젝트를 만든다 (GitHub 연결은 앱에서).",
     {"name": {"type": "string"}, "description": {"type": "string"}}, ["name"], t_new_project),
]
BY_NAME = {t[0]: t for t in TOOLS}


def tool_list():
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": props, "required": req},
             **({"annotations": {"readOnlyHint": True}} if n in ("wiki_projects", "wiki_templates", "wiki_list", "wiki_read", "wiki_search") else {})}
            for n, d, props, req, _ in TOOLS]


# ------------------------------------------------------------ JSON-RPC

def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:   # 알림에는 답하지 않는다
        return None
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": want, "capabilities": {"tools": {}},
            "serverInfo": {"name": "gihoek-wiki", "title": "기획위키", "version": W.VERSION},
            "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        p = msg.get("params") or {}
        tool = BY_NAME.get(p.get("name"))
        if not tool:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"없는 도구: {p.get('name')}"}}
        try:
            out = tool[4](p.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        except Exception as e:  # noqa: BLE001  도구 오류는 AI가 읽고 고칠 수 있게 글로 돌려준다
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"오류: {e}"}], "isError": True}}
    if method in ("resources/list", "prompts/list"):
        return {"jsonrpc": "2.0", "id": mid, "result": {method.split("/")[0]: []}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"지원하지 않는 요청: {method}"}}


def std_streams():
    """윈도우 배포판은 창 프로그램이라 sys.stdin/stdout이 비어 있다. 부모가 넘겨준 파이프를 직접 연다."""
    if sys.stdin is not None and sys.stdout is not None:
        return sys.stdin.buffer, sys.stdout.buffer
    import ctypes
    import msvcrt
    k32 = ctypes.windll.kernel32
    k32.GetStdHandle.restype = ctypes.c_void_p
    fin = os.fdopen(msvcrt.open_osfhandle(k32.GetStdHandle(-10), os.O_RDONLY | os.O_BINARY), "rb", buffering=0)
    fout = os.fdopen(msvcrt.open_osfhandle(k32.GetStdHandle(-11), os.O_BINARY), "wb", buffering=0)
    return fin, fout


def run():
    fin, fout = std_streams()
    sys.stdout = sys.stderr if sys.stderr is not None else open(os.devnull, "w")   # print가 프로토콜을 깨지 않게
    W.load_config()
    for raw in iter(fin.readline, b""):
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON이 아니에요"}}
        else:
            reply = [r for r in map(handle, msg) if r] if isinstance(msg, list) else handle(msg)
        if reply:
            fout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            fout.flush()


# ------------------------------------------------------------ Claude Code / Codex에 등록

NAME = "gihoek-wiki"


def launch_cmd():
    if W.FROZEN:
        return [sys.executable, "--mcp"]
    return [sys.executable, os.path.abspath(os.path.join(W.ROOT, "server.py")), "--mcp"]


def _run(cmd):
    import subprocess
    W.fix_path()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **W.NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).strip()


def registered():
    import shutil
    out = {}
    W.fix_path()
    try:
        cfg = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
        claude_on = NAME in (cfg.get("mcpServers") or {})
    except (OSError, ValueError):
        claude_on = False
    try:
        codex_on = f"[mcp_servers.{NAME}]" in open(os.path.join(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"), "config.toml"),
                                                   encoding="utf-8").read().replace('"', "")
    except OSError:
        codex_on = False
    out["claude"] = {"label": "Claude Code", "installed": bool(shutil.which("claude")), "connected": claude_on}
    out["codex"] = {"label": "Codex", "installed": bool(shutil.which("codex")), "connected": codex_on}
    out["command"] = launch_cmd()
    return out


def connect(target, on=True):
    if target == "claude":
        _run(["claude", "mcp", "remove", "-s", "user", NAME])
        if not on:
            return registered()
        code, out = _run(["claude", "mcp", "add", "-s", "user", NAME, "--"] + launch_cmd())
    elif target == "codex":
        _run(["codex", "mcp", "remove", NAME])
        if not on:
            return registered()
        code, out = _run(["codex", "mcp", "add", NAME, "--"] + launch_cmd())
    else:
        raise ValueError("claude 또는 codex")
    if code != 0:
        raise RuntimeError(f"연결하지 못했어요.\n{out[-600:]}")
    return registered()


if __name__ == "__main__":
    run()
