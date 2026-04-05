from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    name: str | None = None
    email: str
    password: str
    confirmpassword: str
