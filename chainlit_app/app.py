# chainlit_app/app.py
"""
Chainlit shell — HITL entry point for conversational agents.
In SP3, individual agent handlers will be registered here.
For now this shell confirms Chainlit is wired to the FastAPI backend.
"""
import chainlit as cl
import httpx

FASTAPI_BASE = "http://localhost:8000"


@cl.on_chat_start
async def start():
    await cl.Message(
        content="AgentPool ready. Which project would you like to work on? "
                "Type the project slug (e.g. `acme-rail`) to begin."
    ).send()
    cl.user_session.set("project_slug", None)


@cl.on_message
async def handle_message(msg: cl.Message):
    slug = cl.user_session.get("project_slug")

    if slug is None:
        # Treat first message as project slug
        candidate = msg.content.strip().lower()
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{FASTAPI_BASE}/projects/{candidate}/status")
        if resp.status_code == 200:
            cl.user_session.set("project_slug", candidate)
            await cl.Message(
                content=f"Project **{candidate}** loaded. Which agent would you like to start? "
                        "(value_chain_mapper / requirements_analyst / portfolio_manager / "
                        "roadmap_generator / business_plan_generator)"
            ).send()
        else:
            await cl.Message(
                content=f"Project `{candidate}` not found. "
                        "Create it first via the web platform or API, then try again."
            ).send()
        return

    # Placeholder — agent routing added in SP3
    await cl.Message(
        content=f"[{slug}] Agent routing will be wired in SP3. "
                f"Your message: _{msg.content}_"
    ).send()
