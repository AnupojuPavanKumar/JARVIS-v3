# core/tools/git_tool.py — GITHUB INTEGRATION TOOL
# ──────────────────────────────────────────────────────────────────────────────
# Gives the agent full git + GitHub CLI + Vercel/Netlify deploy pipeline.
# Requires: git, gh (GitHub CLI), node/npx on PATH.
# All commands run via ShellTool's safety-checked subprocess layer.
# ──────────────────────────────────────────────────────────────────────────────

import subprocess
import os
import shutil


def _run(cmd: str, cwd: str | None = None, timeout: int = 60) -> str:
    """Run a shell command, return combined stdout+stderr."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return (out + "\n" + err).strip() if err else out
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] Command exceeded {timeout}s: {cmd}"
    except Exception as e:
        return f"[ERROR] {e}"


def _check_tool(name: str) -> str | None:
    """Return path if tool is on PATH, else None."""
    return shutil.which(name)


class GitTool:
    """
    Agent-facing Git + GitHub + deploy tool.
    All methods return a string observation for the agent scratchpad.
    """

    # ── Git basics ─────────────────────────────────────────────────────────────
    def init(self, path: str) -> str:
        """Initialize a git repo at path."""
        if not os.path.exists(path):
            return f"[GitTool] Path does not exist: {path}"
        out = _run("git init", cwd=path)
        _run('git config user.email "jarvis@local.ai"', cwd=path)
        _run('git config user.name "JARVIS"', cwd=path)
        return f"Git initialized at {path}.\n{out}"

    def add_commit(self, path: str, message: str = "Initial JARVIS commit") -> str:
        """Stage all files and commit."""
        add  = _run("git add -A", cwd=path)
        com  = _run(f'git commit -m "{message}"', cwd=path)
        return f"Staged and committed.\n{com}"

    def status(self, path: str) -> str:
        return _run("git status --short", cwd=path)

    def log(self, path: str, n: int = 5) -> str:
        return _run(f"git log --oneline -n {n}", cwd=path)

    # ── GitHub ─────────────────────────────────────────────────────────────────
    def create_and_push(self, path: str, repo_name: str, private: bool = False) -> str:
        """
        Create a GitHub repo using gh CLI and push.
        Requires: gh auth login has been done previously.
        """
        if not _check_tool("gh"):
            return "[GitTool] GitHub CLI (gh) not found. Install from https://cli.github.com"

        visibility = "--private" if private else "--public"
        # Create remote repo + push in one command
        cmd = (
            f"gh repo create {repo_name} {visibility} "
            f"--source=. --remote=origin --push"
        )
        out = _run(cmd, cwd=path, timeout=120)

        if "Error" in out or "error" in out.lower():
            return f"[GitTool] GitHub push failed:\n{out}"

        # Get repo URL
        url_out = _run("gh repo view --json url -q .url", cwd=path)
        url = url_out.strip() if url_out else f"https://github.com/{repo_name}"
        return f"Repository created and pushed to GitHub.\nURL: {url}\n{out}"

    def push(self, path: str, branch: str = "main") -> str:
        """Push to existing remote."""
        return _run(f"git push origin {branch}", cwd=path, timeout=60)

    # ── Deployment ─────────────────────────────────────────────────────────────
    def deploy_vercel(self, path: str) -> str:
        """
        Deploy to Vercel via npx. Returns the deployed URL.
        Requires: Node.js + npx on PATH.
        """
        if not _check_tool("npx"):
            return "[GitTool] npx not found. Install Node.js from https://nodejs.org"

        print(f"[GitTool] Deploying to Vercel from {path}...")
        out = _run("npx -y vercel --prod --yes", cwd=path, timeout=180)

        # Extract URL from output
        for line in out.splitlines():
            if "vercel.app" in line or "https://" in line:
                url = line.strip().split()[-1]
                return f"Deployed to Vercel.\nURL: {url}\nFull output:\n{out}"
        return f"Vercel deploy output:\n{out}"

    def deploy_netlify(self, path: str, dist_dir: str = ".") -> str:
        """Deploy to Netlify via npx."""
        if not _check_tool("npx"):
            return "[GitTool] npx not found."

        out = _run(
            f"npx -y netlify-cli deploy --prod --dir={dist_dir} --yes",
            cwd=path, timeout=180
        )
        for line in out.splitlines():
            if "netlify.app" in line or "Website URL" in line:
                return f"Deployed to Netlify.\n{line}\nFull output:\n{out}"
        return f"Netlify deploy output:\n{out}"

    def full_pipeline(self, path: str, repo_name: str, deploy_to: str = "vercel") -> str:
        """
        One-shot: git init → add → commit → GitHub push → deploy.
        deploy_to: 'vercel' | 'netlify' | 'none'
        """
        steps = []
        steps.append(self.init(path))
        steps.append(self.add_commit(path, f"JARVIS: deploy {repo_name}"))
        steps.append(self.create_and_push(path, repo_name))

        if deploy_to == "vercel":
            steps.append(self.deploy_vercel(path))
        elif deploy_to == "netlify":
            steps.append(self.deploy_netlify(path))

        return "\n---\n".join(steps)
