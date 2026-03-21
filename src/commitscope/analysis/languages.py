from __future__ import annotations

LANGUAGE_MAP = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sh": "shell",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".rs": "rust",
    ".kt": "kotlin",
    ".swift": "swift",
}


def language_for_file(path: str) -> str:
    for suffix, language in LANGUAGE_MAP.items():
        if path.endswith(suffix):
            return language
    return "other"
