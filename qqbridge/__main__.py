import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "qqbridge.app:create_app",
        factory=True,
        host=settings.qqbridge_host,
        port=settings.qqbridge_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

