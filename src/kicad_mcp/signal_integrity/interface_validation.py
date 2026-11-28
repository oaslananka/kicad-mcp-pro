"""Validate SI interface inputs against the shared design-intent contract."""

from pydantic import ValidationError

from ..models.intent import InterfaceSpec


def validate_interfaces(interfaces: list[dict[str, object]]) -> list[InterfaceSpec]:
    """Validate the complete list before calculating or writing any rules."""
    result = []
    for index, raw in enumerate(interfaces):
        normalized = dict(raw)
        kind = normalized.get("kind")
        if isinstance(kind, str):
            normalized["kind"] = kind.lower()
        try:
            result.append(InterfaceSpec.model_validate(normalized, strict=True, extra="forbid"))
        except ValidationError as exc:
            fields = ", ".join(".".join(map(str, error["loc"])) for error in exc.errors())
            raise ValueError(
                f"Invalid interface {index + 1}: check {fields} against InterfaceSpec."
            ) from None
    return result
