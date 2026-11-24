"""Start the studio: python -m studio"""
import uvicorn

from .config import load_settings
from .web.app import create_app


def main() -> None:
    settings = load_settings()
    print(f"Tutorial Studio running at http://{settings.host}:{settings.port}  (mode: {settings.mode})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
