try:
    from ..models import ReviewAction, PRObservation
    from .pullrequest_environment import PullRequestEnvironment
    from .ui import create_ui
except ImportError:
    from models import ReviewAction, PRObservation
    from server.pullrequest_environment import PullRequestEnvironment
    from server.ui import create_ui

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from openenv.core.env_server import create_app

env_app = create_app(
    PullRequestEnvironment,
    ReviewAction,
    PRObservation,
    env_name="patchguard"
)

# Add /health endpoint so Docker HEALTHCHECK passes
@env_app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "env": "patchguard"})

# Render production UI overlay
ui = create_ui()
app = gr.mount_gradio_app(env_app, ui, path="/")

def main():
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=7860)

if __name__ == "__main__":
    main()
