from backend.app.schemas.auth import SignupRequest

users_db: dict[str, dict[str, str]] = {}


def create_user(req: SignupRequest):
    if req.password != req.confirmpassword:
        raise ValueError("Passwords do not match")
    if req.email in users_db:
        raise ValueError("User already exists")

    name = req.name or req.email.split("@")[0]
    users_db[req.email] = {"name": name, "password": req.password}
    return users_db[req.email]


def authenticate_user(email: str, password: str):
    user = users_db.get(email)
    if not user or user["password"] != password:
        return None
    return user
