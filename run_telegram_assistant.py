from __future__ import annotations

import asyncio
import selectors

import uvicorn


def _selector_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


if __name__ == "__main__":
    config = uvicorn.Config("services.telegram_assistant.app:app", host="0.0.0.0", port=8005)
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=_selector_loop)
