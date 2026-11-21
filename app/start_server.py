"""One web worker: chat delivery and optional in-memory limits are process-local."""
import os

import uvicorn


if __name__ == "__main__":
    on_render = os.getenv("RENDER", "").lower() == "true"
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        proxy_headers=True,
        # Render routes public requests through its ingress proxy.
        forwarded_allow_ips="*" if on_render else "127.0.0.1",
        # Do not log query strings (e.g. one-time WebSocket tickets).
        access_log=False,
    )
