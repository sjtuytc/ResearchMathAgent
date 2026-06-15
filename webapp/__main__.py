"""Run the Research Math Agent web app:  python -m webapp

Honors HOST and PORT environment variables (defaults: 127.0.0.1:8000).
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("webapp.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
