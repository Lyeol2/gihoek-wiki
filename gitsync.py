"""Git 협업: 프로젝트 폴더를 GitHub 비공개 레포로 올리고, 팀원을 초대하고, 버튼 하나로 동기화한다.

API 키 없이 로컬에 설치된 git 과 GitHub CLI(gh)의 로그인 상태를 그대로 쓴다.
사용자의 전역 git 설정은 건드리지 않는다 (인증과 작성자 정보는 명령마다 넘긴다).
"""
import os
import re
import shutil
import subprocess
import time

NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}
GITIGNORE = "# 기획위키: 내 컴퓨터에만 두는 것 (되돌리기 기록, 휴지통)\n.wiki/\n.DS_Store\nThumbs.db\n"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_login = {"at": 0, "value": None}


class GitError(RuntimeError):
    pass


def _env():
    return dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", LC_ALL="C")


def _run(args, cwd=None, timeout=120, check=True, binary=False):
    exe = shutil.which(args[0])
    if not exe:
        raise GitError(f"'{args[0]}' 명령을 찾을 수 없어요.")
    kw = {} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}
    try:
        r = subprocess.run([exe, *args[1:]], cwd=cwd, capture_output=True, timeout=timeout, env=_env(),
                           stdin=subprocess.DEVNULL, **kw, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise GitError("GitHub 응답이 너무 늦어요. 인터넷 연결을 확인해 주세요.") from None
    if check and r.returncode != 0:
        err = r.stderr if not binary else r.stderr.decode("utf-8", "replace")
        raise GitError((err or "").strip()[-600:] or f"{args[0]} 실행 실패")
    return r


def git(cwd, *args, net=False, **kw):
    base = ["git", "-c", "core.quotepath=false"]
    if net:  # gh 로그인으로 인증한다 (전역 설정을 바꾸지 않고 이번 명령에만)
        base += ["-c", "credential.https://github.com.helper=",
                 "-c", "credential.https://github.com.helper=!gh auth git-credential"]
    return _run(base + list(args), cwd=cwd, **kw)


def gh(*args, **kw):
    return _run(["gh", *args], **kw)


# ------------------------------------------------------------------ 상태

def login(force=False):
    if not shutil.which("gh"):
        return None
    if force or time.time() - _login["at"] > 60:
        r = gh("api", "user", "--jq", ".login", check=False, timeout=20)
        _login.update(at=time.time(), value=r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None)
    return _login["value"]


def tools():
    has_git, has_gh = bool(shutil.which("git")), bool(shutil.which("gh"))
    user = login() if has_gh else None
    if not has_git:
        hint = "Git이 설치되어 있지 않아요. https://git-scm.com 에서 설치해 주세요."
    elif not has_gh:
        hint = "GitHub CLI(gh)가 필요해요. https://cli.github.com 에서 설치한 뒤 터미널에서 gh auth login 을 실행해 주세요."
    elif not user:
        hint = "GitHub에 로그인되어 있지 않아요. 터미널에서 gh auth login 을 실행해 주세요."
    else:
        hint = ""
    return {"git": has_git, "gh": has_gh, "login": user, "ready": bool(has_git and user), "hint": hint}


def need_ready():
    t = tools()
    if not t["ready"]:
        raise GitError(t["hint"])
    return t


def is_repo(proj):
    return os.path.isdir(os.path.join(proj, ".git"))


def remote_url(proj):
    if not is_repo(proj):
        return ""
    return git(proj, "remote", "get-url", "origin", check=False).stdout.strip()


def slug_of(url):
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def branch(proj):
    return git(proj, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip() or "main"


def _count(proj, rng):
    r = git(proj, "rev-list", "--count", rng, check=False)
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 0


def _changes(proj):
    out = git(proj, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    return [x[3:] for x in out.split("\0") if len(x) > 3]


def status(proj, fetch=False):
    out = {"repo": is_repo(proj), "remote": "", "slug": "", "url": "", "changes": 0, "ahead": 0, "behind": 0, "last": None}
    if not out["repo"]:
        return out
    out["remote"] = remote_url(proj)
    out["slug"] = slug_of(out["remote"])
    out["url"] = f"https://github.com/{out['slug']}" if out["slug"] else ""
    out["changes"] = len(_changes(proj))
    b = branch(proj)
    if out["remote"]:
        if fetch:
            git(proj, "fetch", "--quiet", "origin", net=True, check=False, timeout=40)
        if git(proj, "rev-parse", "--verify", "--quiet", f"origin/{b}", check=False).returncode == 0:
            out["ahead"] = _count(proj, f"origin/{b}..HEAD")
            out["behind"] = _count(proj, f"HEAD..origin/{b}")
        else:
            out["ahead"] = _count(proj, "HEAD")
    last = git(proj, "log", "-1", "--format=%ct%x09%an%x09%s", check=False).stdout.strip().split("\t")
    if len(last) == 3:
        out["last"] = {"at": int(last[0]) * 1000, "by": last[1], "message": last[2]}
    return out


# ------------------------------------------------------------------ 커밋

def _identity(proj):
    """git 사용자 정보가 없는 PC에서도 커밋되도록 GitHub 아이디로 채운다."""
    if git(proj, "config", "user.name", check=False).stdout.strip():
        return []
    user = login() or "wiki"
    return ["-c", f"user.name={user}", "-c", f"user.email={user}@users.noreply.github.com"]


def _commit(proj, message=None):
    gi = os.path.join(proj, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8") as f:
            f.write(GITIGNORE)
    files = _changes(proj)
    if not files:
        return 0
    if not message:
        docs = [os.path.splitext(os.path.basename(f.rstrip("/")))[0] for f in files if f.endswith(".md")]
        head = ", ".join(docs[:3]) or "파일"
        message = f"문서 수정: {head}" + (f" 외 {len(files) - min(len(docs), 3)}개" if len(files) > 3 else "")
    git(proj, "add", "-A")
    git(proj, *_identity(proj), "commit", "-q", "-m", message)
    return len(files)


# ------------------------------------------------------------------ 올리기 / 받기

def suggest_name(text):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text or "").strip("-.").lower()
    return s[:60] or "wiki-" + time.strftime("%y%m%d")


def publish(proj, repo_name, description="", private=True):
    """프로젝트 폴더를 새 GitHub 레포로 올린다."""
    t = need_ready()
    repo_name = (repo_name or "").strip()
    if not NAME_RE.match(repo_name):
        raise GitError("레포 이름은 영문, 숫자, -, _ 만 쓸 수 있어요.")
    if remote_url(proj):
        raise GitError("이미 GitHub에 연결된 프로젝트예요.")
    if not is_repo(proj):
        git(proj, "init", "-q", "-b", "main")
    _commit(proj, "기획위키 프로젝트 시작")
    args = ["repo", "create", repo_name, "--private" if private else "--public"]
    if description:
        args += ["--description", description[:300]]
    r = gh(*args, check=False, timeout=60)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "already exists" in err:
            raise GitError(f"'{repo_name}' 레포가 이미 있어요. 다른 이름을 써 주세요.")
        raise GitError(err[-400:] or "레포를 만들지 못했어요.")
    slug = f"{t['login']}/{repo_name}"
    git(proj, "remote", "add", "origin", f"https://github.com/{slug}.git")
    git(proj, "push", "-q", "-u", "origin", branch(proj), net=True, timeout=180)
    return status(proj)


def _resolve_conflicts(proj):
    """같은 문서를 둘이 고쳤을 때: 팀원 버전을 받고, 내 버전은 옆에 따로 저장해 둔다 (아무것도 잃지 않는다)."""
    kept = []
    paths = [p for p in git(proj, "diff", "--name-only", "--diff-filter=U", "-z").stdout.split("\0") if p]
    stamp = time.strftime("%m%d-%H%M")
    for path in paths:
        mine = git(proj, "show", f":2:{path}", check=False, binary=True)
        theirs = git(proj, "show", f":3:{path}", check=False, binary=True)
        if mine.returncode == 0:
            base, ext = os.path.splitext(path)
            copy = f"{base} (내 버전 {stamp}){ext}"
            data = mine.stdout
            if ext.lower() == ".md":  # 문서 제목도 같이 바꿔야 위키에서 두 문서가 구분된다
                data = re.sub(rb"(?m)^(# [^\r\n]*)", lambda m: m.group(1) + f" (내 버전 {stamp})".encode(), data, count=1)
            with open(os.path.join(proj, copy), "wb") as f:
                f.write(data)
            kept.append({"file": path, "copy": copy})
        if theirs.returncode == 0:
            with open(os.path.join(proj, path), "wb") as f:
                f.write(theirs.stdout)
        elif os.path.exists(os.path.join(proj, path)):
            os.remove(os.path.join(proj, path))
    git(proj, "add", "-A")
    git(proj, *_identity(proj), "commit", "-q", "--no-edit")
    return kept


def sync(proj):
    """내 변경을 저장(commit)하고, 팀원 변경을 받고(merge), 올린다(push)."""
    need_ready()
    if not is_repo(proj):
        raise GitError("아직 GitHub에 올리지 않은 프로젝트예요.")
    result = {"committed": _commit(proj), "pulled": 0, "pushed": 0, "conflicts": []}
    if not remote_url(proj):
        return result
    b = branch(proj)
    for attempt in range(2):
        git(proj, "fetch", "--quiet", "origin", net=True, timeout=60)
        has_remote = git(proj, "rev-parse", "--verify", "--quiet", f"origin/{b}", check=False).returncode == 0
        if has_remote:
            behind = _count(proj, f"HEAD..origin/{b}")
            if behind:
                result["pulled"] += behind
                m = git(proj, *_identity(proj), "merge", "--no-edit", "-q", f"origin/{b}", check=False)
                if m.returncode != 0:
                    if git(proj, "diff", "--name-only", "--diff-filter=U").stdout.strip():
                        result["conflicts"] += _resolve_conflicts(proj)
                    else:
                        git(proj, "merge", "--abort", check=False)
                        raise GitError("팀원 변경을 합치지 못했어요.\n" + (m.stderr or m.stdout or "").strip()[-400:])
        ahead = _count(proj, f"origin/{b}..HEAD") if has_remote else _count(proj, "HEAD")
        if not ahead:
            break
        p = git(proj, "push", "-q", "-u", "origin", b, net=True, check=False, timeout=180)
        if p.returncode == 0:
            result["pushed"] = ahead
            break
        if attempt == 1:  # 그 사이 팀원이 또 올렸다면 한 번 더 받아서 시도한 것
            raise GitError("올리지 못했어요.\n" + (p.stderr or "").strip()[-400:])
    return result


# ------------------------------------------------------------------ 팀원

def members(proj):
    slug = slug_of(remote_url(proj))
    if not slug:
        return {"members": [], "pending": []}
    need_ready()
    m = gh("api", f"repos/{slug}/collaborators", "--jq", ".[].login", check=False, timeout=30)
    p = gh("api", f"repos/{slug}/invitations", "--jq", ".[].invitee.login", check=False, timeout=30)
    return {"members": m.stdout.split() if m.returncode == 0 else [],
            "pending": p.stdout.split() if p.returncode == 0 else []}


def invite(proj, user):
    need_ready()
    slug = slug_of(remote_url(proj))
    if not slug:
        raise GitError("먼저 프로젝트를 GitHub에 올려 주세요.")
    user = (user or "").strip().lstrip("@")
    if not USER_RE.match(user):
        raise GitError("GitHub 아이디를 정확히 적어 주세요. (이메일이 아니라 아이디)")
    r = gh("api", "-X", "PUT", f"repos/{slug}/collaborators/{user}", "-f", "permission=push", check=False, timeout=30)
    if r.returncode != 0:
        err = (r.stderr or "") + (r.stdout or "")
        if "404" in err or "Not Found" in err:
            raise GitError(f"'{user}' 아이디를 찾을 수 없거나, 이 레포에 초대할 권한이 없어요.")
        raise GitError(err.strip()[-300:])
    return members(proj)


def invitations():
    """내가 받은 초대 목록."""
    if not tools()["ready"]:
        return []
    r = gh("api", "user/repository_invitations",
           "--jq", '.[] | [(.id|tostring), .repository.full_name, .inviter.login] | @tsv', check=False, timeout=30)
    out = []
    for line in (r.stdout if r.returncode == 0 else "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            out.append({"id": parts[0], "repo": parts[1], "from": parts[2]})
    return out


def join(projects_dir, repo, invitation=None):
    """초대를 수락하고(있으면) 레포를 프로젝트 폴더로 받아 온다. 받은 폴더 경로를 돌려준다."""
    need_ready()
    slug = slug_of(repo) or (repo or "").strip().strip("/")
    if not re.match(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", slug):
        raise GitError("레포 주소를 '아이디/레포이름' 또는 GitHub 주소로 적어 주세요.")
    if invitation:
        if not str(invitation).isdigit():
            raise GitError("잘못된 초대")
        gh("api", "-X", "PATCH", f"user/repository_invitations/{invitation}", timeout=30)
    dest = os.path.join(projects_dir, slug.split("/")[1])
    if os.path.exists(dest):
        raise GitError(f"'{os.path.basename(dest)}' 폴더가 이미 있어요. 이미 받은 프로젝트인지 확인해 주세요.")
    try:
        git(projects_dir, "clone", "-q", f"https://github.com/{slug}.git", dest, net=True, timeout=600)
    except GitError as e:
        shutil.rmtree(dest, ignore_errors=True)
        msg = str(e)
        if "not found" in msg.lower() or "403" in msg:
            raise GitError("레포를 찾을 수 없어요. 주소가 맞는지, 초대를 받았는지 확인해 주세요.") from None
        raise
    return dest


DESC_PREFIX = "기획위키 프로젝트"


def my_projects(local_dirs):
    """내 GitHub 계정(내가 만들었거나 초대받은 레포) 중 기획위키 프로젝트. 이미 받은 것은 local=True."""
    if not tools()["ready"]:
        return []
    have = {slug_of(remote_url(d)).lower() for d in local_dirs if is_repo(d)}
    r = gh("api", "user/repos?per_page=100&affiliation=owner,collaborator&sort=updated",
           "--jq", '.[] | [.full_name, (.description // ""), (.private|tostring)] | @tsv', check=False, timeout=30)
    out = []
    for line in (r.stdout if r.returncode == 0 else "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[1].startswith(DESC_PREFIX):
            out.append({"repo": parts[0], "name": parts[1][len(DESC_PREFIX):].lstrip(": ").strip() or parts[0].split("/")[1],
                        "private": parts[2] == "true", "local": parts[0].lower() in have})
    return out


def delete_repo(proj):
    """GitHub 레포를 완전히 지운다 (되돌릴 수 없다). 레포 주인만 할 수 있다."""
    need_ready()
    slug = slug_of(remote_url(proj))
    if not slug:
        raise GitError("GitHub에 연결된 프로젝트가 아니에요.")
    r = gh("repo", "delete", slug, "--yes", check=False, timeout=60)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "delete_repo" in err:
            raise GitError("레포를 지울 권한이 아직 없어요. 터미널에서 아래 명령을 한 번 실행한 뒤 다시 시도해 주세요.\n\n"
                           "gh auth refresh -h github.com -s delete_repo")
        if "403" in err or "admin" in err.lower():
            raise GitError("레포 주인만 레포를 지울 수 있어요.")
        raise GitError(err[-300:] or "레포를 지우지 못했어요.")
    git(proj, "remote", "remove", "origin", check=False)
    return slug
