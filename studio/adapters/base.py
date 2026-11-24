"""Application adapter interface.

An adapter encapsulates everything application-specific: how to open a
controlled test environment, which workflows are tested, how to detect the
application version, and how to verify that a workflow really succeeded.
The demonstration engine is generic and only talks to this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts import Check, EnvironmentRecord, WorkflowSpec


class AppAdapter(ABC):
    app_id: str
    automation: str  # e.g. "playwright"

    @abstractmethod
    def workflows(self) -> dict[str, WorkflowSpec]: ...

    def setup_environment(self, work_dir, log, workflow=None) -> None:
        """Start the isolated test environment (e.g. a local server with synthetic data). Default: nothing."""

    def teardown_environment(self, log) -> None:
        """Stop and clean up whatever setup_environment started. Must be safe to call after a failed setup."""

    @abstractmethod
    def environment_url(self) -> str:
        """URL of the isolated test environment."""

    def allowed_url_prefixes(self) -> list[str]:
        """Network isolation: requests outside these prefixes are blocked."""
        return [self.environment_url()]

    @abstractmethod
    def wait_ready(self, page) -> None: ...

    @abstractmethod
    def detect_environment(self, page, browser) -> EnvironmentRecord: ...

    @abstractmethod
    def observe_before(self, page, workflow: WorkflowSpec) -> dict: ...

    @abstractmethod
    def verify(self, page, workflow: WorkflowSpec, observations: dict) -> list[Check]:
        """Inspect real application state after execution. Must not trust narration or plans."""
