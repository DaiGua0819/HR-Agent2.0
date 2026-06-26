"""控制面启动入口。"""

from __future__ import annotations

import uvicorn
from app.control_plane.main import create_app
from app.core.logging import configure_logging
from app.settings import load_settings

app = create_app()


def main() -> None:
    """启动控制面 FastAPI。"""

    configure_logging()
    settings = load_settings()
    uvicorn.run(
        "run_control_plane:app",
        host=settings.control_plane_host,
        port=settings.control_plane_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
