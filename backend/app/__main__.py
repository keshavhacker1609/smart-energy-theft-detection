"""Server entry point: python -m app (AppSail start command)."""

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("X_ZOHO_CATALYST_LISTEN_PORT") or os.environ.get("PORT") or 8000)
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, proxy_headers=True)


if __name__ == "__main__":
    main()
