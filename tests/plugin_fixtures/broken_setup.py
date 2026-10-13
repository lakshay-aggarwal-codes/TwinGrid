from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/_fixture")


@router.get("/never-registered")
def never() -> dict[str, str]:
    return {"x": "y"}


def setup(app: FastAPI) -> None:
    raise RuntimeError("setup exploded")
