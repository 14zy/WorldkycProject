from aiohttp import web
from config.config import AUTHORIZED_TOKEN
import json
import data.repository.userRepository as userRepository

def validate_json(json_data):
    required_fields = ["telegramId", "userId", "accessToken", "refreshToken"]

    missing_fields = [field for field in required_fields if field not in json_data]
    if missing_fields:
        return {"error": "Missing fields", "missing_fields": missing_fields}

    if not isinstance(json_data['telegramId'], int):
        return {"error": "Invalid type for telegramId", "expected": "int"}
    if not isinstance(json_data['userId'], str):
        return {"error": "Invalid type for userId", "expected": "str"}
    if not isinstance(json_data['accessToken'], str):
        return {"error": "Invalid type for accessToken", "expected": "str"}
    if not isinstance(json_data['refreshToken'], str):
        return {"error": "Invalid type for refreshToken", "expected": "str"}

    return True

async def handle_request(request):
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {AUTHORIZED_TOKEN}":
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
        result = validate_json(data)
        if not isinstance(result, bool):
            return web.json_response(result, status=400)
    except json.JSONDecodeError as e:
        return web.json_response({"error": "Bad Request", "message": str(e)}, status=400)
    
    userRepository.saveUser(data['telegramId'], data['userId'], data['accessToken'], data['refreshToken'])

    return web.Response(status=204)

app = web.Application()
app.router.add_post('/api/v1/auth', handle_request)
