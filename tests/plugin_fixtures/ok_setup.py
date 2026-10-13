from fastapi import FastAPI


def setup(app: FastAPI) -> None:
    app.state.fixture_setup_ran = True

    @app.get("/api/_fixture/setup")
    def _route() -> dict[str, str]:
        return {"pong": "setup"}
