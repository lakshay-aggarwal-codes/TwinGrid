from fastapi import APIRouter

router = APIRouter(prefix="/api/_fixture", tags=["fixture"])


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"pong": "router"}
