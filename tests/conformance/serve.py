"""Loopback-only MCP 2026 conformance fixture over the *actual* KiCad server.

This module is not imported by the application, installed as a console entry point,
or enabled outside the opt-in official conformance test session.
"""

import base64
import json
import os
from typing import cast

import uvicorn
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.prompts.base import UserMessage
from mcp.shared.exceptions import MCPError
from mcp.types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    AudioContent,
    Completion,
    CompletionArgument,
    CompletionContext,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    EmbeddedResource,
    ImageContent,
    InputRequest,
    InputRequiredResult,
    ListRootsRequest,
    PromptReference,
    ResourceTemplateReference,
    SamplingMessage,
    TextContent,
    TextResourceContents,
)
from starlette.applications import Starlette

from kicad_mcp.config import get_config
from kicad_mcp.server import KiCadFastMCP, build_server

_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
)
_WAV = "UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQIAAAA="


def _elicitation(message: str, field: str, field_type: str = "string") -> ElicitRequest:
    return ElicitRequest(
        params=ElicitRequestFormParams(
            message=message,
            requested_schema={
                "type": "object",
                "properties": {field: {"type": field_type}},
                "required": [field],
            },
        )
    )


def _sampling_request(prompt: str = "What is the capital of France?") -> CreateMessageRequest:
    return CreateMessageRequest(
        params=CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=100,
        )
    )


def make_app() -> Starlette:
    config = get_config()
    config.transport = "streamable-http"
    config.protocol_lane = "2026-07-28-rc"
    config.stateful_http = False
    config.enable_tasks = False
    config.auth_token = None
    config.port = int(os.environ.get("MCP_CONFORMANCE_PORT", "39780"))
    config.host = "127.0.0.1"
    server = cast(KiCadFastMCP, build_server("minimal"))

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    def test_simple_text() -> str:
        return "This is a simple text response for testing."

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    def test_image_content() -> list[ImageContent]:
        return [ImageContent(type="image", data=_PNG, mime_type="image/png")]

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    def test_audio_content() -> list[AudioContent]:
        return [AudioContent(type="audio", data=_WAV, mime_type="audio/wav")]

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    def test_embedded_resource() -> list[EmbeddedResource]:
        return [
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri="test://embedded-resource",
                    mime_type="text/plain",
                    text="Fixture embedded resource",
                ),
            )
        ]

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    def test_multiple_content_types() -> list[TextContent | ImageContent | EmbeddedResource]:
        return [
            TextContent(type="text", text="Fixture mixed content"),
            ImageContent(type="image", data=_PNG, mime_type="image/png"),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri="test://mixed-content-resource",
                    mime_type="application/json",
                    text='{"test":true}',
                ),
            ),
        ]

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_missing_capability(ctx: Context) -> str:
        capabilities = ctx.session.client_capabilities if ctx.session is not None else None
        if capabilities is None or capabilities.sampling is None:
            raise MCPError(
                code=MISSING_REQUIRED_CLIENT_CAPABILITY,
                message="This tool requires client sampling capability",
                data={"requiredCapabilities": {"sampling": {}}},
            )
        return "Sampling is supported"

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_tool_with_progress(ctx: Context) -> str:
        for progress in (0, 50, 100):
            await ctx.report_progress(progress=progress, total=100)
        return "Progress complete"

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_elicitation(ctx: Context) -> str | InputRequiredResult:
        responses = ctx.input_responses
        if responses and "user_name" in responses:
            answer = responses["user_name"]
            name = (
                answer.content.get("name")
                if isinstance(answer, ElicitResult) and answer.content
                else "?"
            )
            return f"Hello, {name}!"
        return InputRequiredResult(
            input_requests={
                "user_name": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="What is your name?",
                        requested_schema={
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    )
                )
            }
        )

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_sampling(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses and "capital_question" in ctx.input_responses:
            return "Model response received"
        return InputRequiredResult(input_requests={"capital_question": _sampling_request()})

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_list_roots(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses and "client_roots" in ctx.input_responses:
            return "Client roots received"
        return InputRequiredResult(input_requests={"client_roots": ListRootsRequest()})

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_request_state(ctx: Context) -> str | InputRequiredResult:
        if (
            ctx.input_responses
            and "confirm" in ctx.input_responses
            and ctx.request_state == "request-state-nonce"
        ):
            return "state-ok: confirmation received"
        return InputRequiredResult(
            input_requests={"confirm": _elicitation("Please confirm", "ok", "boolean")},
            request_state="request-state-nonce",
        )

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_multiple_inputs(ctx: Context) -> str | InputRequiredResult:
        if (
            ctx.input_responses
            and {"user_name", "greeting", "client_roots"} <= ctx.input_responses.keys()
        ):
            return "All inputs received"
        return InputRequiredResult(
            input_requests={
                "user_name": _elicitation("What is your name?", "name"),
                "greeting": _sampling_request("Generate a greeting"),
                "client_roots": ListRootsRequest(),
            },
            request_state="multiple-inputs",
        )

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_multi_round(ctx: Context) -> str | InputRequiredResult:
        state = json.loads(ctx.request_state) if ctx.request_state else {"round": 0}
        answers = ctx.input_responses or {}
        if state["round"] == 0:
            return InputRequiredResult(
                input_requests={"step1": _elicitation("Step 1: What is your name?", "name")},
                request_state=json.dumps({"round": 1}),
            )
        if state["round"] == 1 and "step1" in answers:
            response = answers["step1"]
            name = (
                response.content.get("name")
                if isinstance(response, ElicitResult) and response.content
                else "?"
            )
            return InputRequiredResult(
                input_requests={
                    "step2": _elicitation("Step 2: What is your favorite color?", "color")
                },
                request_state=json.dumps({"round": 2, "name": name}),
            )
        if state["round"] == 2 and "step2" in answers:
            response = answers["step2"]
            color = (
                response.content.get("color")
                if isinstance(response, ElicitResult) and response.content
                else "?"
            )
            return f"{state.get('name')} likes {color}"
        return InputRequiredResult(
            input_requests={"step1": _elicitation("Step 1: What is your name?", "name")},
            request_state=json.dumps({"round": 1}),
        )

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_tampered_state(ctx: Context) -> str | InputRequiredResult:
        if ctx.request_state is not None:
            return f"state-ok: {ctx.request_state}"
        return InputRequiredResult(
            input_requests={"confirm": _elicitation("Please confirm", "ok", "boolean")},
            request_state="round-1",
        )

    @server.tool(
        description="Test-only MCP conformance fixture exercising the actual KiCad server protocol."
    )
    async def test_input_required_result_capabilities(ctx: Context) -> InputRequiredResult:
        caps = ctx.client_capabilities
        requests: dict[str, InputRequest] = {}
        if caps is None or caps.sampling is not None:
            requests["sample"] = _sampling_request("Say hello")
        if caps is None or caps.elicitation is not None:
            requests["ask"] = _elicitation("What is your name?", "name")
        return InputRequiredResult(input_requests=requests, request_state="capability-gated")

    @server.resource("test://static-text")
    def static_text() -> str:
        return "This is the content of the static text resource."

    @server.resource("test://static-binary")
    def static_binary() -> bytes:
        return base64.b64decode(_PNG)

    @server.resource("test://template/{resource_id}/data")
    def template(resource_id: str) -> str:
        return json.dumps(
            {"id": resource_id, "templateTest": True, "data": f"Data for ID: {resource_id}"}
        )

    @server.prompt(description="Test-only MCP conformance prompt using the actual server.")
    def test_simple_prompt() -> str:
        return "This is a simple prompt for testing."

    @server.prompt(description="Test-only MCP conformance prompt using the actual server.")
    def test_prompt_with_arguments(arg1: str, arg2: str) -> str:
        return f"Prompt with arguments: arg1='{arg1}', arg2='{arg2}'"

    @server.prompt(description="Test-only MCP conformance prompt using the actual server.")
    def test_prompt_with_embedded_resource(resourceUri: str) -> list[UserMessage]:  # noqa: N803
        return [
            UserMessage(
                role="user",
                content=EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri=resourceUri,
                        text="Embedded resource content for testing.",
                        mime_type="text/plain",
                    ),
                ),
            )
        ]

    @server.prompt(description="Test-only MCP conformance prompt using the actual server.")
    def test_prompt_with_image() -> list[UserMessage]:
        return [
            UserMessage(
                role="user",
                content=ImageContent(
                    type="image",
                    data=_PNG,
                    mime_type="image/png",
                ),
            )
        ]

    @server.prompt(description="Test-only MCP conformance prompt using the actual server.")
    async def test_input_required_result_prompt(
        ctx: Context,
    ) -> list[UserMessage] | InputRequiredResult:
        if ctx.input_responses and "user_context" in ctx.input_responses:
            return [
                UserMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="Context received",
                    ),
                )
            ]
        return InputRequiredResult(
            input_requests={
                "user_context": _elicitation("What context should the prompt use?", "context"),
            }
        )

    @server.completion()  # type: ignore[no-untyped-call, untyped-decorator]
    async def complete(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion:
        return Completion(values=[], total=0, has_more=False)

    allowed_tools = server.allowed_tool_names
    if allowed_tools is None:
        raise RuntimeError("Conformance fixtures require an explicit restricted tool profile")
    allowed_tools.update(
        {
            "test_simple_text",
            "test_image_content",
            "test_audio_content",
            "test_embedded_resource",
            "test_multiple_content_types",
            "test_missing_capability",
            "test_tool_with_progress",
            "test_input_required_result_elicitation",
            "test_input_required_result_sampling",
            "test_input_required_result_list_roots",
            "test_input_required_result_request_state",
            "test_input_required_result_multiple_inputs",
            "test_input_required_result_multi_round",
            "test_input_required_result_tampered_state",
            "test_input_required_result_capabilities",
        }
    )
    return server.streamable_http_app()


if __name__ == "__main__":
    port = int(os.environ.get("MCP_CONFORMANCE_PORT", "39780"))
    uvicorn.run(make_app(), host="127.0.0.1", port=port, log_level="error")
