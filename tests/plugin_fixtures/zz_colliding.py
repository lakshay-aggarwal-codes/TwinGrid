from fastapi import APIRouter

router = APIRouter()


@router.get("/api/_fixture/ping")
def clash() -> dict[str, str]:
    return {"pong": "clash"}
