import time
import jwt

SECRET = input("Вставьте секрет")

payload = {
    "sub": "external-service",
    "iss": "my-app",
    "iat": int(time.time()),
    # можно добавить любые свои claims: roles, tenant_id и т.д.
}

token = jwt.encode(payload, SECRET, algorithm="HS256")
print(token)
