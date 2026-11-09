"""Automated Security Test Suite: Repository Secret Leakage & .gitignore Validation.

Verifies:
1. .gitignore exists and specifies mandatory exclusions (.env*, *.db, deploy/cloud_run_env.yaml, .venv/, __pycache__/).
2. .env.example exists, contains zero real secrets, and documents all required variables.
3. If .git exists, git ls-files tracks zero secret files and zero database files.
4. Regex scan on tracked files verifies no hardcoded high-entropy API keys, passwords, or tokens.
"""

import re
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# High-entropy secret patterns to detect in tracked files
# We assemble regexes without literals to prevent self-matching false positives
SECRET_PATTERNS = [
    (re.compile(r"AIza" + r"[0-9A-Za-z\-_]{35}"), "Google / Gemini API Key"),
    (re.compile(r"[0-9]{9,10}:[A-Za-z0-9_-]{35}"), "Telegram Bot Token"),
    (re.compile(r"\b[a-z]{4}\s+[a-z]{4}\s+[a-z]{4}\s+[a-z]{4}\b"), "Google App Password (16-char)"),
    (re.compile(r"ghp_" + r"[0-9a-zA-Z]{36}"), "GitHub Personal Access Token (classic)"),
    (re.compile(r"github_pat_" + r"[0-9a-zA-Z_]{82}"), "GitHub Personal Access Token (fine-grained)"),
    (re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP|DSA) PRIVATE KEY-----"), "Private Cryptographic Key"),
]

FORBIDDEN_TRACKED_PATTERNS = [
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(?!example).+$"),
    re.compile(r"(^|/)cloud_run_env\.yaml$"),
    re.compile(r"\.db$"),
    re.compile(r"\.sqlite[0-9]?$"),
    re.compile(r"(^|/)\.venv/"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)\.pytest_cache/"),
    re.compile(r"(^|/)\.agents/"),
]

SENSITIVE_KEY_INDICATORS = ("KEY", "TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "AUTH")


COMMON_ENGLISH_4WORDS = {
    "free", "tier", "zero", "cost", "test", "file", "mode", "code", "date", "time",
    "word", "user", "pass", "note", "task", "load", "true", "name", "from", "with",
    "that", "this", "have", "will", "your", "more", "make", "each", "read", "sent",
    "view", "open", "call", "send", "done", "drop", "list", "wait", "step", "turn",
    "debt", "must", "fail", "rate",
}


def is_placeholder(match_text: str) -> bool:
    """Return True if match is a known non-secret placeholder or common prose."""
    text = match_text.strip()
    if re.match(r"^(x{4}\s+){3}x{4}$", text) or re.match(r"^(y{4}\s+){3}y{4}$", text):
        return True
    if "your_" in text.lower() or "change_this" in text.lower() or "example" in text.lower():
        return True
    words = text.lower().split()
    if len(words) == 4 and all(w in COMMON_ENGLISH_4WORDS for w in words):
        return True
    return False


class TestGitignoreExclusions:
    """Verifies that .gitignore exists and enforces strict exclusion boundaries."""

    def test_gitignore_exists_in_project_root(self):
        gitignore_path = REPO_ROOT / ".gitignore"
        assert gitignore_path.exists(), ".gitignore file MUST exist in project root"
        assert gitignore_path.is_file(), ".gitignore must be a regular file"

    def test_gitignore_contains_all_mandatory_patterns(self):
        gitignore_path = REPO_ROOT / ".gitignore"
        content = gitignore_path.read_text(encoding="utf-8")

        mandatory_tokens = [
            ".env",
            "deploy/cloud_run_env.yaml",
            "*.db",
            ".venv",
            "__pycache__",
        ]
        for token in mandatory_tokens:
            assert token in content, f"Mandatory token '{token}' missing from .gitignore"

    def test_git_check_ignore_rejects_sensitive_sample_paths(self):
        """Verify git check-ignore programmatically confirms sensitive paths are ignored."""
        git_dir = REPO_ROOT / ".git"
        if not git_dir.exists():
            pytest.skip("Git repository not yet initialized")

        sensitive_samples = [
            ".env",
            ".env.local",
            ".env.production",
            "deploy/cloud_run_env.yaml",
            "data/assistant.db",
            "data/test.sqlite",
            ".venv/bin/python",
            "app/__pycache__/main.cpython-312.pyc",
            ".pytest_cache/v/cache/lastfailed",
            ".agents/test_agent/plan.md",
        ]

        for sample in sensitive_samples:
            result = subprocess.run(
                ["git", "check-ignore", "-q", sample],
                cwd=REPO_ROOT,
                capture_output=True,
            )
            assert result.returncode == 0, (
                f"Path '{sample}' should be ignored according to .gitignore, but git check-ignore returned {result.returncode}"
            )


class TestEnvExampleSanitization:
    """Verifies that .env.example contains no real secrets and documents all required variables."""

    def test_env_example_exists(self):
        env_example = REPO_ROOT / ".env.example"
        assert env_example.exists(), ".env.example must exist in repository root"
        assert env_example.is_file()

    def test_env_example_documents_all_required_variables(self):
        env_example = REPO_ROOT / ".env.example"
        content = env_example.read_text(encoding="utf-8")

        required_keys = [
            "APP_ENV",
            "SECRET_KEY",
            "DATABASE_PATH",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_SECRET_TOKEN",
            "TELEGRAM_WEBHOOK_URL",
            "GMAIL_USER_EMAIL",
            "GMAIL_APP_PASSWORD",
            "GEMINI_API_KEY",
            "DEFAULT_PAYMENT_ACCOUNT",
        ]

        for key in required_keys:
            assert key in content, f"Required variable '{key}' missing from .env.example documentation"

    def test_env_example_contains_only_placeholders(self):
        env_example = REPO_ROOT / ".env.example"
        content = env_example.read_text(encoding="utf-8")

        # Verify no real secret values from local .env exist in .env.example
        env_real = REPO_ROOT / ".env"
        if env_real.exists():
            real_content = env_real.read_text(encoding="utf-8")
            for line in real_content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().upper()
                v = v.strip().strip('"').strip("'")
                # Only check keys that represent confidential secrets
                if any(ind in k for ind in SENSITIVE_KEY_INDICATORS):
                    if len(v) >= 8 and not v.startswith("http") and not v.startswith("0.0.0.0"):
                        assert v not in content, (
                            f"CRITICAL LEAK: Live secret value for '{k}' from .env was found in .env.example!"
                        )

    def test_env_example_has_no_secret_patterns(self):
        env_example = REPO_ROOT / ".env.example"
        content = env_example.read_text(encoding="utf-8")

        for pattern, desc in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                if is_placeholder(match.group(0)):
                    continue
                pytest.fail(f"Real secret pattern for {desc} found in .env.example: '{match.group(0)}'")


class TestGitTrackedFilesCleanliness:
    """Verifies that git repository tracks zero sensitive files and zero unencrypted secrets."""

    def test_git_tracks_zero_forbidden_files(self):
        git_dir = REPO_ROOT / ".git"
        if not git_dir.exists():
            pytest.skip("Git repository not yet initialized")

        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"git ls-files failed: {result.stderr}"

        tracked_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        assert len(tracked_files) > 0, "Expected at least one tracked file in git repository"

        for file_path in tracked_files:
            for pattern in FORBIDDEN_TRACKED_PATTERNS:
                assert not pattern.search(file_path), (
                    f"FORBIDDEN FILE TRACKED IN GIT: '{file_path}' matches forbidden pattern {pattern.pattern}"
                )

    def test_git_tracks_zero_plaintext_secrets_across_all_files(self):
        git_dir = REPO_ROOT / ".git"
        if not git_dir.exists():
            pytest.skip("Git repository not yet initialized")

        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"git ls-files failed: {result.stderr}"

        tracked_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        # Files to exclude from regex scanning (e.g., this test itself, test fixtures with synthetic mock tokens)
        excluded_files = {
            "tests/test_security_git_sanitization.py",
            "tests/fixtures/telegram_updates.json",
            "tests/tier1_feature_coverage/test_r1_agent_core.py",
            "tests/tier2_boundary_corner/test_r1_boundary.py",
            "tests/unit/test_production_features.py",
            "tests/unit/test_gemini_integration.py",
        }

        for rel_path in tracked_files:
            if rel_path in excluded_files:
                continue
            full_path = REPO_ROOT / rel_path
            if not full_path.exists() or full_path.is_dir():
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for pattern, desc in SECRET_PATTERNS:
                for match in pattern.finditer(content):
                    if is_placeholder(match.group(0)):
                        continue
                    pytest.fail(
                        f"POTENTIAL SECRET LEAKAGE: Found {desc} in tracked file '{rel_path}': "
                        f"'{match.group(0)[:10]}...'"
                    )
