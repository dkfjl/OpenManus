from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.config import config
from app.exceptions import ToolError
from app.tool.base import BaseTool


class MarkdownDocumentTool(BaseTool):
    """Create or update a Markdown (.md) document within the workspace.

    Typical usage: provide full Marp markdown string in `content` and set
    `append=False` to overwrite the target file once.
    """

    name: str = "markdown_document"
    description: str = "Write Markdown content to a .md file inside workspace"
    parameters: dict = {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Target .md path (relative to workspace or absolute within it).",
            },
            "content": {
                "type": "string",
                "description": "Markdown content to write. Provide full Marp text if needed.",
            },
            "append": {
                "type": "boolean",
                "default": False,
                "description": "Append to existing file instead of overwriting.",
            },
            "encoding": {
                "type": "string",
                "default": "utf-8",
                "description": "File encoding used when writing.",
            },
            "ensure_trailing_newline": {
                "type": "boolean",
                "default": True,
                "description": "Ensure file ends with a newline.",
            },
        },
        "required": ["filepath", "content"],
    }

    async def execute(
        self,
        *,
        filepath: str,
        content: str,
        append: bool = False,
        encoding: str = "utf-8",
        ensure_trailing_newline: bool = True,
        **_: str,
    ):
        if not isinstance(content, str) or not content.strip():
            raise ToolError("`content` must be a non-empty Markdown string.")

        target = self._resolve_path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> dict:
            mode = "a" if (append and target.exists()) else "w"
            text = content if not ensure_trailing_newline else (content.rstrip("\n") + "\n")
            with open(target, mode, encoding=encoding) as f:
                f.write(text)
            return {"path": str(target), "mode": ("append" if mode == "a" else "overwrite"), "bytes": len(text.encode(encoding))}

        result = await asyncio.to_thread(_write)
        return self.success_response(result)

    @staticmethod
    def _resolve_path(filepath: str) -> Path:
        base = config.workspace_root.resolve()
        candidate = Path(filepath).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        resolved = candidate.resolve()
        if resolved.suffix.lower() != ".md":
            raise ToolError("Only .md files are supported by markdown_document tool.")
        if base not in resolved.parents and resolved != base:
            raise ToolError(f"Target path {resolved} is outside of the workspace directory.")
        return resolved

