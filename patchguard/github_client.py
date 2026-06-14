"""
patchguard/github_client.py — GitHub API Client with Demo Mode Fallback

Provides real GitHub connectivity when GITHUB_TOKEN is set,
and gracefully falls back to local tasks.json demo mode when it isn't.
"""

import json
import os
import re
import subprocess
import time
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class RepoMetadata:
    """Repository metadata returned from GitHub or demo mode."""
    owner: str = ""
    name: str = ""
    full_name: str = ""
    description: str = ""
    language: str = ""
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    default_branch: str = "main"
    url: str = ""
    clone_url: str = ""
    is_demo: bool = False
    connected: bool = False
    error: str = ""


@dataclass
class GitHubIssue:
    """A GitHub issue or a demo task repackaged as an issue."""
    number: int = 0
    title: str = ""
    body: str = ""
    state: str = "open"
    labels: list[str] = field(default_factory=list)
    created_at: str = ""
    url: str = ""
    # Extra fields for demo mode task compatibility
    raw_task: dict = field(default_factory=dict)


@dataclass
class PRResult:
    """Result of a pull request creation attempt."""
    success: bool = False
    pr_number: int = 0
    pr_url: str = ""
    title: str = ""
    body: str = ""
    branch: str = ""
    is_demo: bool = False
    error: str = ""


# ─── GitHub Client ────────────────────────────────────────────────────────────

class GitHubClient:
    """
    GitHub API client with automatic demo-mode fallback.

    When GITHUB_TOKEN is set and a valid repo URL is provided,
    all operations hit the real GitHub REST API.

    When credentials are missing, the client enters demo mode
    and uses tasks.json for issue data and simulates Git operations.
    """

    API_BASE = "https://api.github.com"

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.is_demo = self.token is None
        self.owner = ""
        self.repo_name = ""
        self.repo_url = ""
        self.clone_dir = ""
        self.metadata: RepoMetadata | None = None
        self._tasks: list[dict] = []

        # Pre-load demo tasks
        self._load_demo_tasks()

    def _load_demo_tasks(self):
        """Load tasks.json for demo mode fallback."""
        try:
            candidates = [
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "tasks.json"),
                os.path.join(os.getcwd(), "tasks.json"),
                "tasks.json",
            ]
            for path in candidates:
                if os.path.exists(path):
                    with open(path) as f:
                        self._tasks = json.load(f)
                    break
        except Exception:
            self._tasks = []

    # ── URL Parsing ───────────────────────────────────────────────────────

    @staticmethod
    def parse_repo_url(url: str) -> tuple[str, str]:
        """Extract owner and repo name from a GitHub URL."""
        url = url.strip().rstrip("/").removesuffix(".git")
        match = re.match(r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+)", url)
        if match:
            return match.group(1), match.group(2)
        raise ValueError(f"Invalid GitHub URL: {url}")

    # ── API Helpers ───────────────────────────────────────────────────────

    def _api_request(self, endpoint: str, method: str = "GET",
                     data: dict | None = None) -> dict:
        """Make an authenticated GitHub API request."""
        url = f"{self.API_BASE}{endpoint}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "PatchGuard-AI/3.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise RuntimeError(f"GitHub API {e.code}: {error_body[:200]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}")

    # ── Connection ────────────────────────────────────────────────────────

    def connect(self, repo_url: str) -> RepoMetadata:
        """
        Connect to a GitHub repository.
        Returns metadata about the repo, or demo metadata if in demo mode.
        """
        self.repo_url = repo_url

        # Demo mode — return simulated metadata
        if self.is_demo:
            try:
                owner, name = self.parse_repo_url(repo_url)
            except ValueError:
                owner, name = "demo-user", "demo-repo"

            self.owner = owner
            self.repo_name = name
            self.metadata = RepoMetadata(
                owner=owner,
                name=name,
                full_name=f"{owner}/{name}",
                description="Demo mode — using local task dataset",
                language="Python",
                stars=0,
                forks=0,
                open_issues=len(self._tasks),
                default_branch="main",
                url=repo_url,
                clone_url=f"https://github.com/{owner}/{name}.git",
                is_demo=True,
                connected=True,
            )
            return self.metadata

        # Real mode — hit GitHub API
        try:
            owner, name = self.parse_repo_url(repo_url)
            self.owner = owner
            self.repo_name = name

            data = self._api_request(f"/repos/{owner}/{name}")
            self.metadata = RepoMetadata(
                owner=owner,
                name=name,
                full_name=data.get("full_name", f"{owner}/{name}"),
                description=data.get("description", "") or "",
                language=data.get("language", "") or "",
                stars=data.get("stargazers_count", 0),
                forks=data.get("forks_count", 0),
                open_issues=data.get("open_issues_count", 0),
                default_branch=data.get("default_branch", "main"),
                url=data.get("html_url", repo_url),
                clone_url=data.get("clone_url", f"https://github.com/{owner}/{name}.git"),
                is_demo=False,
                connected=True,
            )
            return self.metadata

        except Exception as e:
            self.metadata = RepoMetadata(
                owner=owner if 'owner' in dir() else "",
                name=name if 'name' in dir() else "",
                error=str(e),
                connected=False,
                is_demo=False,
            )
            return self.metadata

    # ── Issues ────────────────────────────────────────────────────────────

    def fetch_issues(self, state: str = "open", limit: int = 20) -> list[GitHubIssue]:
        """
        Fetch issues from the connected repository.
        Falls back to tasks.json in demo mode.
        """
        if self.is_demo or not self.metadata or not self.metadata.connected:
            return self._demo_issues()

        try:
            data = self._api_request(
                f"/repos/{self.owner}/{self.repo_name}/issues?state={state}&per_page={limit}"
            )
            issues = []
            for item in data:
                if item.get("pull_request"):
                    continue  # Skip PRs
                issues.append(GitHubIssue(
                    number=item.get("number", 0),
                    title=item.get("title", ""),
                    body=item.get("body", "") or "",
                    state=item.get("state", "open"),
                    labels=[l.get("name", "") for l in item.get("labels", [])],
                    created_at=item.get("created_at", ""),
                    url=item.get("html_url", ""),
                ))
            return issues
        except Exception:
            return self._demo_issues()

    def _demo_issues(self) -> list[GitHubIssue]:
        """Convert tasks.json entries to GitHubIssue objects."""
        issues = []
        for task in self._tasks:
            diff_label = task.get("difficulty", "medium")
            issues.append(GitHubIssue(
                number=int(task.get("id", 0)),
                title=task.get("pr_title", "Untitled"),
                body=task.get("pr_description", ""),
                state="open",
                labels=[diff_label],
                created_at="",
                url="",
                raw_task=task,
            ))
        return issues

    def get_task_for_issue(self, issue: GitHubIssue) -> dict:
        """
        Get the raw task data for an issue.
        In demo mode, returns the task from tasks.json directly.
        In real mode, constructs a task-like dict from the issue.
        """
        if issue.raw_task:
            return issue.raw_task

        # Find by number in demo tasks
        for task in self._tasks:
            if str(task.get("id")) == str(issue.number):
                return task

        # Construct a synthetic task for real GitHub issues
        return {
            "id": str(issue.number),
            "difficulty": "medium",
            "pr_title": issue.title,
            "pr_description": issue.body,
            "files_changed": [],
            "code_diff": "",
            "language": self.metadata.language if self.metadata else "python",
            "tests_passed": False,
            "ci_logs": "",
            "repository_context": self.metadata.description if self.metadata else "",
            "expected_action": "request_changes",
            "keywords": [],
        }

    # ── Git Operations ────────────────────────────────────────────────────

    def clone_repo(self, target_dir: str | None = None) -> str:
        """
        Clone the repository locally.
        In demo mode, creates a skeleton directory.
        """
        if not target_dir:
            target_dir = os.path.join(
                os.getcwd(), ".patchguard_workspace",
                f"{self.owner}_{self.repo_name}"
            )

        if self.is_demo:
            os.makedirs(target_dir, exist_ok=True)
            readme = os.path.join(target_dir, "README.md")
            if not os.path.exists(readme):
                with open(readme, "w") as f:
                    f.write(f"# {self.repo_name}\nDemo workspace\n")
            self.clone_dir = target_dir
            return target_dir

        # Real clone
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        clone_url = self.metadata.clone_url if self.metadata else self.repo_url
        # Inject token for private repos
        if self.token and "github.com" in clone_url:
            clone_url = clone_url.replace(
                "https://", f"https://x-access-token:{self.token}@"
            )

        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, target_dir],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise RuntimeError(f"Clone failed: {result.stderr[:300]}")

        self.clone_dir = target_dir
        return target_dir

    def create_branch(self, branch_name: str) -> bool:
        """Create and checkout a new branch in the cloned repo."""
        if self.is_demo:
            return True

        if not self.clone_dir:
            raise RuntimeError("Repository not cloned. Call clone_repo() first.")

        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True, text=True, cwd=self.clone_dir
        )
        return result.returncode == 0

    def commit_changes(self, message: str, files: list[str] | None = None) -> bool:
        """Stage and commit changes in the cloned repo."""
        if self.is_demo:
            return True

        if not self.clone_dir:
            raise RuntimeError("Repository not cloned.")

        if files:
            for f in files:
                subprocess.run(["git", "add", f], cwd=self.clone_dir)
        else:
            subprocess.run(["git", "add", "."], cwd=self.clone_dir)

        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=self.clone_dir,
            env={**os.environ, "GIT_AUTHOR_NAME": "PatchGuard AI",
                 "GIT_AUTHOR_EMAIL": "patchguard@ai.bot",
                 "GIT_COMMITTER_NAME": "PatchGuard AI",
                 "GIT_COMMITTER_EMAIL": "patchguard@ai.bot"},
        )
        return result.returncode == 0

    def push_branch(self, branch_name: str) -> bool:
        """Push a branch to the remote."""
        if self.is_demo:
            return True

        if not self.clone_dir:
            raise RuntimeError("Repository not cloned.")

        result = subprocess.run(
            ["git", "push", "origin", branch_name],
            capture_output=True, text=True, cwd=self.clone_dir
        )
        return result.returncode == 0

    # ── Pull Request Creation ─────────────────────────────────────────────

    def create_pull_request(self, title: str, body: str,
                            branch: str, base: str | None = None) -> PRResult:
        """
        Create a pull request on GitHub.
        In demo mode, returns a simulated success result.
        """
        base = base or (self.metadata.default_branch if self.metadata else "main")

        if self.is_demo:
            return PRResult(
                success=True,
                pr_number=42,
                pr_url=f"https://github.com/{self.owner}/{self.repo_name}/pull/42",
                title=title,
                body=body,
                branch=branch,
                is_demo=True,
            )

        try:
            data = self._api_request(
                f"/repos/{self.owner}/{self.repo_name}/pulls",
                method="POST",
                data={
                    "title": title,
                    "body": body,
                    "head": branch,
                    "base": base,
                },
            )
            return PRResult(
                success=True,
                pr_number=data.get("number", 0),
                pr_url=data.get("html_url", ""),
                title=title,
                body=body,
                branch=branch,
                is_demo=False,
            )
        except Exception as e:
            return PRResult(
                success=False,
                title=title,
                body=body,
                branch=branch,
                error=str(e),
            )

    # ── Status ────────────────────────────────────────────────────────────

    @property
    def connection_status(self) -> str:
        """Human-readable connection status string."""
        if not self.metadata:
            return "⚪ Not connected"
        if self.metadata.error:
            return f"🔴 Error: {self.metadata.error}"
        if self.metadata.is_demo:
            return "🟡 Demo Mode — using local task dataset"
        if self.metadata.connected:
            return f"🟢 Connected to {self.metadata.full_name}"
        return "🔴 Connection failed"

    @property
    def mode_label(self) -> str:
        """Short mode label."""
        return "Demo" if self.is_demo else "GitHub"
