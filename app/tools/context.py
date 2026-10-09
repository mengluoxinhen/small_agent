"""Per-run context handed to tools by the runner.

Tools never receive host paths from the model. The workspace is decided by the backend
(one directory per session) and reaches the tool through `RunContextWrapper[AppContext]`,
which the SDK deliberately keeps out of the model-visible schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppContext:
    workspace: Path
    """Root that all file tools are confined to."""

    max_read_bytes: int = 200_000
    max_write_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
