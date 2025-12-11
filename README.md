# recipe-hub-50520-50606

FastAPI backend now includes JWT-based authentication.

Auth endpoints:
- POST /auth/register: Register a new user (email, password, full_name optional).
- POST /auth/login: Login with OAuth2 form (username=email, password) to receive {access_token, token_type:'bearer'}.
- GET /auth/me: Example protected endpoint returning current user.

Environment variables (see recipe_backend/.env.example):
- DATABASE_URL
- JWT_SECRET
- JWT_ALGORITHM (default HS256)
- ACCESS_TOKEN_EXPIRE_MINUTES (default 60)

Dependencies are listed in recipe_backend/requirements.txt and already include passlib[bcrypt] and python-jose.