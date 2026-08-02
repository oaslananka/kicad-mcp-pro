"""Typed error model for KiCad MCP Pro."""

from __future__ import annotations

from typing import Literal, TypedDict

# A transient class tells an agent *why* an error is retryable and how to retry:
#   none    - not transient; do not retry without changing the request.
#   network - IPC/connection problem; safe to retry after a short backoff.
#   timeout - the operation timed out; retry after a longer backoff.
#   lock    - a resource was locked; retry after a short backoff.
#   state   - a precondition is unmet (e.g. no board open); reconcile state first,
#             then retry. Retrying blindly will not help.
TransientClass = Literal["none", "network", "timeout", "lock", "state"]


class ErrorPayload(TypedDict):
    """Stable machine-readable error payload."""

    code: str
    message: str
    hint: str
    retryable: bool
    transient_class: TransientClass
    retry_after_ms: int | None


class KiCadMcpError(Exception):
    """Base class for stable KiCad MCP domain errors."""

    code = "KICAD_MCP_ERROR"
    hint = "Inspect the request, project configuration, and diagnostics output."
    retryable = False
    transient_class: TransientClass = "none"
    retry_after_ms: int | None = None

    def to_payload(self) -> ErrorPayload:
        """Return a stable JSON-serializable error payload."""
        return {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "retryable": self.retryable,
            "transient_class": self.transient_class,
            "retry_after_ms": self.retry_after_ms,
        }


class KiCadNotRunningError(KiCadMcpError):
    """Raised when KiCad IPC is not reachable."""

    code = "KICAD_NOT_RUNNING"
    hint = "Start KiCad and enable the IPC API server, or run doctor for diagnostics."
    retryable = True
    transient_class: TransientClass = "network"
    retry_after_ms = 1000


class KiCadConnectionTimeoutError(KiCadNotRunningError):
    """Raised when KiCad IPC connection attempts time out."""

    code = "KICAD_CONNECTION_TIMEOUT"
    hint = "Increase KICAD_MCP_TIMEOUT_MS or verify that the KiCad IPC API is responding."
    retryable = True
    transient_class: TransientClass = "timeout"
    retry_after_ms = 2000


class KiCadVersionMismatchError(KiCadMcpError):
    """Raised when the detected KiCad version is unsupported."""

    code = "KICAD_VERSION_MISMATCH"
    hint = "Install a supported KiCad version or check the compatibility matrix."
    retryable = False


class KiCadProjectNotFoundError(KiCadMcpError):
    """Raised when a configured KiCad project cannot be found."""

    code = "KICAD_PROJECT_NOT_FOUND"
    hint = "Set KICAD_MCP_PROJECT_DIR or call kicad_set_project() with an existing project."
    retryable = False


class KiCadBoardNotOpenError(KiCadMcpError):
    """Raised when KiCad is reachable but no board is open."""

    code = "KICAD_BOARD_NOT_OPEN"
    hint = "Open a .kicad_pcb file in KiCad or set the active project before using board tools."
    retryable = True
    # Retrying alone will not open a board; reconcile state (open a board) first.
    transient_class: TransientClass = "state"


class BoardAccessError(KiCadMcpError):
    """Raised when one live board collection cannot be read."""

    code = "KICAD_BOARD_ACCESS_UNAVAILABLE"
    hint = "Verify that KiCad IPC and the requested board API are available, then retry."
    retryable = True
    transient_class: TransientClass = "state"

    def __init__(self, operation: str, method_name: str, cause: BaseException) -> None:
        self.operation = operation
        self.method_name = method_name
        if isinstance(cause, KiCadMcpError):
            self.retryable = cause.retryable
            self.transient_class = cause.transient_class
            self.retry_after_ms = cause.retry_after_ms
        detail = str(cause).strip() or cause.__class__.__name__
        super().__init__(f"Could not read board {operation} via {method_name}: {detail}")


class IpcDisconnectedError(KiCadNotRunningError):
    """Raised when the KiCad IPC connection was lost and reconnection failed."""

    code = "IPC_DISCONNECTED"
    hint = "Open KiCad and enable the IPC API server in Preferences, or run doctor for diagnostics."
    retryable = True
    transient_class: TransientClass = "network"
    retry_after_ms = 1000


class ToolRegistrationTimeoutError(KiCadMcpError):
    """Raised when deferred tool registration does not finish within its budget.

    Registration runs in the background; if a request waits longer than the
    configured timeout it gets this retryable error instead of hanging forever.
    """

    code = "SERVER_INITIALIZING"
    hint = "Tool registration is still in progress; retry in a moment."
    retryable = True
    transient_class: TransientClass = "timeout"
    retry_after_ms = 2000


class UnsafePathError(KiCadMcpError, ValueError):
    """Raised when a requested path escapes the configured workspace."""

    code = "UNSAFE_PATH"
    hint = "Use a relative path inside KICAD_MCP_WORKSPACE_ROOT or the active project."
    retryable = False


class ToolValidationError(KiCadMcpError, ValueError):
    """Raised when a tool request is invalid before touching external state."""

    code = "TOOL_VALIDATION_ERROR"
    hint = "Correct the tool arguments and retry."
    retryable = False


class ExternalToolUnavailableError(KiCadMcpError):
    """Raised when a required external executable is unavailable."""

    code = "EXTERNAL_TOOL_UNAVAILABLE"
    hint = "Install the required executable or configure its path explicitly."
    retryable = False


class ManualStepRequiredError(KiCadMcpError):
    """Raised when a workflow cannot complete headlessly and needs a KiCad GUI step.

    Used where KiCad exposes no headless path (e.g. applying a routed Specctra SES
    session). The message describes the exact GUI step so an agent can surface it
    instead of silently dead-ending or falsely reporting success.
    """

    code = "MANUAL_STEP_REQUIRED"
    hint = "Perform the described step in the KiCad GUI, then retry."
    retryable = True
    transient_class: TransientClass = "state"


class SchematicWriteUnsafeError(KiCadMcpError):
    """Raised when a schematic write would lose structure and is refused.

    A round-trip-safe edit verifies that no structural nodes (e.g. global labels,
    sheets) were dropped. If the serializer would silently corrupt the file, the
    original is restored and this is raised instead — writes never silently lose data.
    """

    code = "SCHEMATIC_WRITE_UNSAFE"
    hint = "The original file was restored. Edit the affected construct another way."
    retryable = False


def error_payload(exc: BaseException) -> ErrorPayload:
    """Map an arbitrary exception to the stable error payload shape."""
    if isinstance(exc, KiCadMcpError):
        return exc.to_payload()
    return {
        "code": "INTERNAL_ERROR",
        "message": str(exc) or exc.__class__.__name__,
        "hint": "Run doctor for diagnostics and retry with corrected configuration.",
        "retryable": False,
        "transient_class": "none",
        "retry_after_ms": None,
    }
