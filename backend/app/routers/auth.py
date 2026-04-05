from fastapi import APIRouter, HTTPException

from backend.app.schemas.auth import LoginRequest, SignupRequest
from backend.app.services.user_service import authenticate_user, create_user

router = APIRouter(tags=["auth"])


@router.post("/signup")
def signup(req: SignupRequest):
    try:
        user = create_user(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "message": "Signup successful",
        "user": {"email": req.email, "name": user["name"]},
    }


@router.post("/login")
def login(req: LoginRequest):
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "message": "Login successful",
        "user": {"email": req.email, "name": user["name"]},
    }
