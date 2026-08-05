"""
github_mcp.py — HINA's GitHub MCP server

Every tool below funnels its result through `sanitize()` before it ever
touches `hina_sdk.send_ui_json()`. That's the fix for the original bug
(`data=,` — a bare trailing comma with nothing after it, a SyntaxError
the module could never even import) and it's also what makes the
front-end able to trust the shape of what it receives: no raw PyGithub
objects, no datetimes, no accidentally-enormous diffs blowing up the
DOM or the token budget.

UI contract
-----------
Every payload sent to the client uses ui_type="github" and a top-level
"kind" field inside `data` so app.js can pick the right card:

    kind: "repo"          -> repo overview card
    kind: "issue_list"     -> list of issues
    kind: "issue_detail"   -> single issue + comments
    kind: "issue_result"   -> created/closed/reopened confirmation
    kind: "pr_list"        -> list of pull requests
    kind: "pr_detail"      -> PR + file diffs for review
    kind: "pr_result"      -> merge/comment confirmation
    kind: "actions_runs"   -> CI workflow run list
    kind: "commits"        -> commit list
    kind: "branches"       -> branch list
    kind: "releases"       -> release list
    kind: "file"           -> file content viewer
    kind: "code_search"    -> code search results
    kind: "notifications"  -> notification list
    kind: "error"          -> failure card (still rendered nicely, not raw text)

Anything unexpected still degrades gracefully client-side (generic
key/value card), but every tool here now sends a shape app.js knows
how to draw.
"""

import os
import sys
import base64
import datetime
from dotenv import load_dotenv
from github import Github, GithubException
from github import Auth

# Aligning with your core architecture paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
core_dir = os.path.join(parent_dir, "core")
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)

from core import hina_sdk
from mcp.server.fastmcp import FastMCP

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
load_dotenv()
GITHUB_PAT = os.getenv("GITHUB_PAT")

if not GITHUB_PAT:
    print("FATAL: GITHUB_PAT not found in .env file.", file=sys.stderr)
    sys.exit(1)

auth = Auth.Token(GITHUB_PAT)
gh = Github(auth=auth)
mcp = FastMCP("GitHub_Manager_MCP")

GITHUB_ICON = "fa-brands fa-github"

# -----------------------------------------------------------------------------
# Sanitization layer
# -----------------------------------------------------------------------------
# Anything that leaves this file and heads to send_ui_json() passes through
# here first. Goals:
#   1. Never let a non-JSON-serializable object (datetime, PaginatedList,
#      NamedUser, etc.) reach requests' json= encoder.
#   2. Cap string/list/dict size so one tool call can't dump megabytes of
#      diff/README/log text into the UI or the token stream.
#   3. Strip control characters that could break rendering.
#   4. Recurse safely with a depth cap so a pathological/self-referential
#      structure can't hang the process.
MAX_STR_LEN = 4000
MAX_LIST_LEN = 50
MAX_DEPTH = 6


def _clean_str(s: str, limit: int = MAX_STR_LEN) -> str:
    if s is None:
        return ""
    # strip non-printable control chars (keep \n \t)
    s = "".join(ch for ch in s if ch == "\n" or ch == "\t" or ch >= " " or ch == "\r")
    if len(s) > limit:
        return s[:limit].rstrip() + f"\n… [truncated {len(s) - limit} chars]"
    return s


def sanitize(value, depth: int = 0):
    """Recursively coerce any value into safe, bounded, JSON-native data."""
    if depth > MAX_DEPTH:
        return "…"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()

    if isinstance(value, str):
        return _clean_str(value)

    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:MAX_LIST_LEN]:
            out[str(k)] = sanitize(v, depth + 1)
        return out

    if isinstance(value, (list, tuple, set)):
        items = list(value)[:MAX_LIST_LEN]
        result = [sanitize(v, depth + 1) for v in items]
        if len(value) > MAX_LIST_LEN:
            result.append(f"… [{len(value) - MAX_LIST_LEN} more truncated]")
        return result

    # PyGithub objects and anything else unknown: fall back to string repr,
    # sanitized and capped, rather than letting it hit the JSON encoder raw.
    try:
        return _clean_str(str(value), limit=1000)
    except Exception:
        return "<unserializable>"


def ui_payload(kind: str, **fields):
    """Build the standard {kind, ...} envelope, sanitized."""
    return sanitize({"kind": kind, **fields})


def emit(agent_name: str, state: str, msg: str, data=None, done: bool = False,
          color: str = "tool", ui_type: str = "github"):
    hina_sdk.send_ui_json(
        agent_name=agent_name,
        state=state,
        msg=msg,
        data=data if data is not None else {},
        ui_type=ui_type,
        icon=GITHUB_ICON,
        color=color,
        done=done,
    )


def emit_error(agent_name: str, msg: str, exc: Exception):
    detail = str(exc)
    payload = ui_payload("error", message=msg, detail=detail)
    emit(agent_name, "error", msg, data=payload, done=True, color="error")
    return {"error": msg, "detail": detail}


# -----------------------------------------------------------------------------
# Toolset: Repository & Context
# -----------------------------------------------------------------------------
@mcp.tool()
def github_get_repo_context(repo_name: str):
    """Fetches high-level repository details: description, stars, forks,
    open issue/PR counts, primary languages, topics, license, and a README
    snippet. Use this first when you need orientation on a repo."""
    emit("GitHub", "fetching...", f"Pulling context for {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        lang_stats = repo.get_languages()

        try:
            readme = repo.get_readme().decoded_content.decode("utf-8")[:1500]
        except Exception:
            readme = None

        try:
            topics = repo.get_topics()
        except Exception:
            topics = []

        data = ui_payload(
            "repo",
            name=repo.full_name,
            description=repo.description,
            url=repo.html_url,
            stars=repo.stargazers_count,
            forks=repo.forks_count,
            watchers=repo.subscribers_count,
            open_issues=repo.open_issues_count,
            default_branch=repo.default_branch,
            languages=lang_stats,
            topics=topics,
            license=(repo.license.name if repo.license else None),
            is_private=repo.private,
            is_fork=repo.fork,
            pushed_at=repo.pushed_at,
            created_at=repo.created_at,
            readme_snippet=readme,
        )
        emit("GitHub", "found", f"Retrieved {repo_name} context.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to retrieve repo context for {repo_name}.", e)


@mcp.tool()
def github_search_repos(query: str, limit: int = 8):
    """Searches GitHub for repositories matching a query
    (e.g. 'language:python stars:>1000 llm agent')."""
    emit("GitHub", "searching...", f"Searching repos for '{query}'", done=False, color="search")
    try:
        results = gh.search_repositories(query=query)
        items = []
        for r in results[: max(1, min(limit, 20))]:
            items.append({
                "name": r.full_name,
                "description": r.description,
                "url": r.html_url,
                "stars": r.stargazers_count,
                "language": r.language,
            })
        data = ui_payload("repo_search", query=query, results=items)
        emit("GitHub", "found", f"Found {len(items)} repos.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", "Repo search failed.", e)


@mcp.tool()
def github_list_branches(repo_name: str, limit: int = 20):
    """Lists branches on a repository, flagging the default branch."""
    emit("GitHub", "listing...", f"Listing branches for {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        default = repo.default_branch
        branches = []
        for b in repo.get_branches():
            branches.append({
                "name": b.name,
                "is_default": b.name == default,
                "protected": b.protected,
                "sha": b.commit.sha[:7],
            })
            if len(branches) >= limit:
                break
        data = ui_payload("branches", repo=repo.full_name, default_branch=default, branches=branches)
        emit("GitHub", "found", f"{len(branches)} branches.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to list branches for {repo_name}.", e)


@mcp.tool()
def github_list_commits(repo_name: str, branch: str = "", limit: int = 10, path: str = ""):
    """Lists recent commits on a repo (optionally filtered to a branch
    and/or file path) with author, message, and short SHA."""
    emit("GitHub", "fetching...", f"Pulling commits for {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        kwargs = {}
        if branch:
            kwargs["sha"] = branch
        if path:
            kwargs["path"] = path
        commits = repo.get_commits(**kwargs)
        items = []
        for c in commits[: max(1, min(limit, 30))]:
            items.append({
                "sha": c.sha[:7],
                "message": (c.commit.message or "").split("\n")[0],
                "author": c.commit.author.name if c.commit.author else "unknown",
                "date": c.commit.author.date if c.commit.author else None,
                "url": c.html_url,
            })
        data = ui_payload("commits", repo=repo.full_name, branch=branch or repo.default_branch, commits=items)
        emit("GitHub", "found", f"{len(items)} commits.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to list commits for {repo_name}.", e)


@mcp.tool()
def github_get_file_content(repo_name: str, file_path: str, ref: str = ""):
    """Fetches the text content of a specific file in a repo at a given
    ref (branch/tag/sha). Useful for reading source before editing or
    reviewing. Binary files are reported but not decoded."""
    emit("GitHub", "reading...", f"Reading {file_path} from {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        kwargs = {"ref": ref} if ref else {}
        content_file = repo.get_contents(file_path, **kwargs)
        if isinstance(content_file, list):
            data = ui_payload(
                "file",
                repo=repo.full_name,
                path=file_path,
                is_dir=True,
                entries=[{"name": f.name, "type": f.type, "path": f.path} for f in content_file],
            )
            emit("GitHub", "found", f"{file_path} is a directory.", data=data, done=True, color="success")
            return data

        is_binary = content_file.encoding not in ("base64",) or _looks_binary(content_file.name)
        if is_binary:
            text = None
        else:
            try:
                text = base64.b64decode(content_file.content).decode("utf-8")
            except Exception:
                text = None

        data = ui_payload(
            "file",
            repo=repo.full_name,
            path=file_path,
            ref=ref or repo.default_branch,
            size=content_file.size,
            url=content_file.html_url,
            is_binary=text is None,
            content=text[:6000] if text else None,
        )
        emit("GitHub", "found", f"Retrieved {file_path}.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to read {file_path} from {repo_name}.", e)


def _looks_binary(name: str) -> bool:
    binary_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
                  ".zip", ".gz", ".tar", ".exe", ".dll", ".so", ".bin", ".woff", ".woff2")
    return name.lower().endswith(binary_ext)


@mcp.tool()
def github_search_code(repo_name: str, query: str, limit: int = 10):
    """Searches code within a specific repository for a string/symbol.
    Great for 'where is X defined/used' questions."""
    emit("GitHub", "searching...", f"Searching code in {repo_name} for '{query}'", done=False, color="search")
    try:
        full_query = f"{query} repo:{repo_name}"
        results = gh.search_code(query=full_query)
        items = []
        for r in results[: max(1, min(limit, 20))]:
            items.append({"path": r.path, "url": r.html_url, "sha": r.sha[:7] if r.sha else ""})
        data = ui_payload("code_search", repo=repo_name, query=query, results=items)
        emit("GitHub", "found", f"{len(items)} matches.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Code search failed in {repo_name}.", e)


# -----------------------------------------------------------------------------
# Toolset: Issues (Triage & Management)
# -----------------------------------------------------------------------------
@mcp.tool()
def github_manage_issues(repo_name: str, action: str, title: str = "", body: str = "",
                          issue_number: int = 0, labels: str = "", comment: str = ""):
    """
    Manages issues on a repo.
    Actions:
      'list'    - top 10 open issues
      'create'  - needs `title` (and optionally `body`, `labels` comma-separated)
      'read'    - needs `issue_number`, returns issue + comments
      'comment' - needs `issue_number` and `comment`
      'close'   - needs `issue_number`
      'reopen'  - needs `issue_number`
    """
    emit("GitHub", "syncing...", f"Executing '{action}' on {repo_name} issues.", done=False)
    try:
        repo = gh.get_repo(repo_name)

        if action == "list":
            issues = [i for i in repo.get_issues(state="open") if i.pull_request is None][:10]
            items = [{
                "number": i.number, "title": i.title, "user": i.user.login,
                "comments": i.comments, "labels": [l.name for l in i.labels],
                "url": i.html_url, "created_at": i.created_at,
            } for i in issues]
            data = ui_payload("issue_list", repo=repo.full_name, issues=items)
            emit("GitHub", "success", f"{len(items)} open issues.", data=data, done=True, color="success")
            return data

        if action == "create":
            if not title:
                return emit_error("GitHub", "Title required to create issue.", Exception("missing title"))
            label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
            issue = repo.create_issue(title=title, body=body, labels=label_list or None)
            data = ui_payload("issue_result", action="created", url=issue.html_url,
                                number=issue.number, title=issue.title)
            emit("GitHub", "success", f"Created issue #{issue.number}.", data=data, done=True, color="success")
            return data

        if action == "read":
            if not issue_number:
                return emit_error("GitHub", "Issue number required for reading.", Exception("missing issue_number"))
            issue = repo.get_issue(number=issue_number)
            comments = [{"user": c.user.login, "body": c.body, "created_at": c.created_at}
                        for c in issue.get_comments()][:20]
            data = ui_payload(
                "issue_detail",
                repo=repo.full_name, number=issue.number, title=issue.title, body=issue.body,
                state=issue.state, user=issue.user.login, labels=[l.name for l in issue.labels],
                url=issue.html_url, comments=comments,
            )
            emit("GitHub", "success", f"Loaded issue #{issue.number}.", data=data, done=True, color="success")
            return data

        if action == "comment":
            if not issue_number or not comment:
                return emit_error("GitHub", "issue_number and comment required.", Exception("missing fields"))
            issue = repo.get_issue(number=issue_number)
            c = issue.create_comment(comment)
            data = ui_payload("issue_result", action="commented", number=issue_number, url=c.html_url)
            emit("GitHub", "success", f"Commented on issue #{issue_number}.", data=data, done=True, color="success")
            return data

        if action in ("close", "reopen"):
            if not issue_number:
                return emit_error("GitHub", "issue_number required.", Exception("missing issue_number"))
            issue = repo.get_issue(number=issue_number)
            issue.edit(state="closed" if action == "close" else "open")
            data = ui_payload("issue_result", action=action, number=issue_number, url=issue.html_url)
            emit("GitHub", "success", f"Issue #{issue_number} {action}d.", data=data, done=True, color="success")
            return data

        return emit_error("GitHub", "Invalid action.", Exception("use list, create, read, comment, close, reopen"))

    except Exception as e:
        return emit_error("GitHub", f"Issue operation '{action}' failed.", e)


# -----------------------------------------------------------------------------
# Toolset: CI/CD Actions Intelligence
# -----------------------------------------------------------------------------
@mcp.tool()
def github_actions_logs(repo_name: str, status: str = "failure", limit: int = 5):
    """Queries recent GitHub Actions workflow runs, filtered by status
    ('failure', 'success', 'in_progress', etc.) and returns run metadata
    for debugging or status reporting."""
    emit("GitHub", "debugging...", f"Checking '{status}' workflows in {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        runs = repo.get_workflow_runs(status=status)

        if runs.totalCount == 0:
            data = ui_payload("actions_runs", repo=repo.full_name, status=status, runs=[])
            emit("GitHub", "clean", f"No workflows found with status '{status}'.", data=data, done=True, color="success")
            return data

        items = []
        for run in runs[: max(1, min(limit, 15))]:
            items.append({
                "name": run.name,
                "conclusion": run.conclusion,
                "status": run.status,
                "url": run.html_url,
                "branch": run.head_branch,
                "event": run.event,
                "created_at": run.created_at,
                "run_number": run.run_number,
            })
        data = ui_payload("actions_runs", repo=repo.full_name, status=status, runs=items)
        emit("GitHub", "found", f"{len(items)} workflow run(s).", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Actions query failed for {repo_name}.", e)


@mcp.tool()
def github_rerun_workflow(repo_name: str, run_id: int):
    """Re-triggers a specific workflow run by its numeric run ID
    (get this from github_actions_logs)."""
    emit("GitHub", "restarting...", f"Re-running workflow {run_id} in {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        run = repo.get_workflow_run(run_id)
        run.rerun()
        data = ui_payload("actions_runs", repo=repo.full_name, action="rerun_triggered", run_id=run_id, url=run.html_url)
        emit("GitHub", "success", f"Rerun triggered for run {run_id}.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to rerun workflow {run_id}.", e)


# -----------------------------------------------------------------------------
# Toolset: Pull Requests
# -----------------------------------------------------------------------------
@mcp.tool()
def github_manage_pull_requests(repo_name: str, action: str, pr_number: int = 0,
                                  title: str = "", body: str = "", head: str = "", base: str = "",
                                  comment: str = "", merge_method: str = "merge"):
    """
    Manages pull requests.
    Actions:
      'list'    - top 10 open PRs
      'analyze' - needs `pr_number`, returns diff + metadata for review
      'create'  - needs `title`, `head`, `base` (and optionally `body`)
      'comment' - needs `pr_number` and `comment`
      'merge'   - needs `pr_number` (optionally `merge_method`: merge/squash/rebase)
    """
    emit("GitHub", "syncing...", f"Executing '{action}' on {repo_name} PRs.", done=False)
    try:
        repo = gh.get_repo(repo_name)

        if action == "list":
            prs = repo.get_pulls(state="open")[:10]
            items = [{
                "number": p.number, "title": p.title, "user": p.user.login,
                "head": p.head.ref, "base": p.base.ref, "url": p.html_url,
                "draft": p.draft, "created_at": p.created_at,
            } for p in prs]
            data = ui_payload("pr_list", repo=repo.full_name, pull_requests=items)
            emit("GitHub", "success", f"{len(items)} open PRs.", data=data, done=True, color="success")
            return data

        if action == "analyze":
            if not pr_number:
                return emit_error("GitHub", "pr_number required.", Exception("missing pr_number"))
            pr = repo.get_pull(pr_number)
            files = pr.get_files()
            file_changes = [{
                "filename": f.filename, "additions": f.additions, "deletions": f.deletions,
                "status": f.status, "patch": (f.patch[:600] if f.patch else ""),
            } for f in files][:25]
            data = ui_payload(
                "pr_detail",
                repo=repo.full_name, number=pr.number, title=pr.title, body=pr.body,
                user=pr.user.login, head=pr.head.ref, base=pr.base.ref, url=pr.html_url,
                mergeable=pr.mergeable, additions=pr.additions, deletions=pr.deletions,
                changed_files=file_changes,
            )
            emit("GitHub", "ready", f"PR #{pr.number} loaded for review.", data=data, done=True, color="success")
            return data

        if action == "create":
            if not (title and head and base):
                return emit_error("GitHub", "title, head, and base are required.", Exception("missing fields"))
            pr = repo.create_pull(title=title, body=body, head=head, base=base)
            data = ui_payload("pr_result", action="created", number=pr.number, url=pr.html_url, title=pr.title)
            emit("GitHub", "success", f"Created PR #{pr.number}.", data=data, done=True, color="success")
            return data

        if action == "comment":
            if not pr_number or not comment:
                return emit_error("GitHub", "pr_number and comment required.", Exception("missing fields"))
            pr = repo.get_pull(pr_number)
            c = pr.create_issue_comment(comment)
            data = ui_payload("pr_result", action="commented", number=pr_number, url=c.html_url)
            emit("GitHub", "success", f"Commented on PR #{pr_number}.", data=data, done=True, color="success")
            return data

        if action == "merge":
            if not pr_number:
                return emit_error("GitHub", "pr_number required.", Exception("missing pr_number"))
            pr = repo.get_pull(pr_number)
            if not pr.mergeable:
                return emit_error("GitHub", f"PR #{pr_number} is not currently mergeable.",
                                    Exception("mergeable=False (conflicts or checks pending)"))
            result = pr.merge(merge_method=merge_method if merge_method in ("merge", "squash", "rebase") else "merge")
            data = ui_payload("pr_result", action="merged", number=pr_number,
                                merged=result.merged, sha=result.sha, message=result.message)
            emit("GitHub", "success", f"PR #{pr_number} merged.", data=data, done=True, color="success")
            return data

        return emit_error("GitHub", "Invalid action.", Exception("use list, analyze, create, comment, merge"))

    except Exception as e:
        return emit_error("GitHub", f"PR operation '{action}' failed.", e)


# -----------------------------------------------------------------------------
# Toolset: Releases, Notifications, Stars
# -----------------------------------------------------------------------------
@mcp.tool()
def github_list_releases(repo_name: str, limit: int = 8):
    """Lists recent releases/tags for a repo with changelog snippets."""
    emit("GitHub", "fetching...", f"Pulling releases for {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        items = []
        for r in repo.get_releases()[: max(1, min(limit, 20))]:
            items.append({
                "tag": r.tag_name, "name": r.title, "url": r.html_url,
                "prerelease": r.prerelease, "published_at": r.published_at,
                "notes": (r.body or "")[:500],
            })
        data = ui_payload("releases", repo=repo.full_name, releases=items)
        emit("GitHub", "found", f"{len(items)} releases.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to list releases for {repo_name}.", e)


@mcp.tool()
def github_get_notifications(limit: int = 15, unread_only: bool = True):
    """Fetches the authenticated user's GitHub notifications
    (mentions, review requests, CI failures on watched repos, etc.)."""
    emit("GitHub", "checking...", "Pulling notifications", done=False)
    try:
        notifs = gh.get_user().get_notifications(all=not unread_only)
        items = []
        for n in notifs[: max(1, min(limit, 30))]:
            items.append({
                "repo": n.repository.full_name,
                "reason": n.reason,
                "title": n.subject.title,
                "type": n.subject.type,
                "unread": n.unread,
                "updated_at": n.updated_at,
            })
        data = ui_payload("notifications", notifications=items)
        emit("GitHub", "found", f"{len(items)} notification(s).", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", "Failed to fetch notifications.", e)


@mcp.tool()
def github_star_repo(repo_name: str, action: str = "star"):
    """Stars or unstars a repository. `action` is 'star' or 'unstar'."""
    emit("GitHub", "syncing...", f"{action}ring {repo_name}", done=False)
    try:
        repo = gh.get_repo(repo_name)
        user = gh.get_user()
        if action == "unstar":
            user.remove_from_starred(repo)
        else:
            user.add_to_starred(repo)
        data = ui_payload("issue_result", action=f"{action}red", repo=repo.full_name, url=repo.html_url)
        emit("GitHub", "success", f"{repo.full_name} {action}red.", data=data, done=True, color="success")
        return data
    except Exception as e:
        return emit_error("GitHub", f"Failed to {action} {repo_name}.", e)


if __name__ == "__main__":
    mcp.run()