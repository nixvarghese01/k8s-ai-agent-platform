"""Message-triage MCP server: one tool, classify_message, backed by the BentoML service.

The model behind it is MLflow's message-triage@champion, served by BentoML in the mlops
profile. This server is tiny and always on (core), so when mlops is off the agent gets a clear
"start the mlops profile" answer instead of a connection error. Served over MCP streamable HTTP
at http://<host>:8000/mcp, like the other MCP servers.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

TRIAGE_URL = os.environ.get("TRIAGE_URL", "http://triage.mlops.svc.cluster.local:3000")
OFF = ("The message classifier isn't running: it's part of the mlops profile. "
       "Start it with `.\\local-up -Profile mlops` (or `make profile P=mlops`) and ask again.")

mcp = FastMCP(
    "triage",
    instructions="Classify messages (SMS, e-mail, chat) as spam or normal (ham).",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")  # healthy even when the model server is off; the tool says so


def describe(r: dict) -> str:
    p = r["spam_probability"]
    verdict = "SPAM" if r["label"] == "spam" else "not spam (ham)"
    confidence = p if r["label"] == "spam" else 1 - p
    return f"{verdict}: {confidence:.0%} confident (spam probability {p:.2f}, model message-triage v{r['model_version']})"


@mcp.tool()
async def classify_message(text: str) -> str:
    """Decide whether a message (SMS, e-mail, chat) is spam/phishing or a normal message.

    Pass the message text itself. Returns the verdict with the model's confidence.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{TRIAGE_URL}/classify", json={"texts": [text]})
            r.raise_for_status()
    except httpx.ConnectError:
        return OFF
    except httpx.HTTPError as e:
        return f"The message classifier failed: {e}"
    return describe(r.json()[0])


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
