"""Filesystem I/O for the COA advisor: the linked-repos registry and the global default ROE
(central, under ~/.claude/scorched-earth/), plus per-repo ROE, jobs, and COA outputs (under
<repo>/.scorched/). Reuses state.py's JSON helpers (atomic write, 0600)."""

from __future__ import annotations

import os
from typing import List, Tuple

from . import state as st
from .jobs import Job, parse_jobs
from .roe import ROE, DEFAULT_ROE, roe_from_dict, merge_roe

REPOS_PATH = os.path.join(st.STATE_DIR, "repos.json")
ROE_DEFAULT_PATH = os.path.join(st.STATE_DIR, "roe.default.json")


def _repo_dir(repo_path: str) -> str:
    return os.path.join(os.path.realpath(os.path.expanduser(repo_path)), ".scorched")


def list_repos() -> List[str]:
    return list(st._read_json(REPOS_PATH, {"repos": []}).get("repos", []))


def link_repo(repo_path: str) -> str:
    ap = os.path.realpath(os.path.expanduser(repo_path))
    repos = list_repos()
    if ap not in repos:
        repos.append(ap)
        st._write_json(REPOS_PATH, {"repos": repos})
    return ap


def unlink_repo(repo_path: str) -> bool:
    ap = os.path.realpath(os.path.expanduser(repo_path))
    repos = list_repos()
    if ap in repos:
        repos.remove(ap)
        st._write_json(REPOS_PATH, {"repos": repos})
        return True
    return False


def load_roe(repo_path: str) -> ROE:
    base = roe_from_dict(st._read_json(ROE_DEFAULT_PATH, {}), DEFAULT_ROE)
    override = roe_from_dict(st._read_json(os.path.join(_repo_dir(repo_path), "roe.json"), {}))
    return merge_roe(base, override)


def load_jobs(repo_path: str) -> List[Job]:
    data = st._read_json(os.path.join(_repo_dir(repo_path), "jobs.json"), [])
    return parse_jobs(data, repo=os.path.realpath(os.path.expanduser(repo_path)))


def write_coa(repo_path: str, md: str, html: str, date: str) -> Tuple[str, str]:
    out = os.path.join(_repo_dir(repo_path), "coa")
    os.makedirs(out, exist_ok=True)
    md_path = os.path.join(out, f"{date}.md")
    html_path = os.path.join(out, f"{date}.html")
    with open(md_path, "w") as f:
        f.write(md)
    with open(html_path, "w") as f:
        f.write(html)
    return md_path, html_path
