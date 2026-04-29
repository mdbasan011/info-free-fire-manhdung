import time
import httpx
import json
from collections import defaultdict
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from cachetools import TTLCache
from typing import Tuple
from proto import FreeFire_pb2, main_pb2, AccountPersonalShow_pb2
from google.protobuf import json_format, message
from google.protobuf.message import Message
from Crypto.Cipher import AES
import base64
import asyncio

# === Settings ===

MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB53"
USERAGENT = "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)"
SUPPORTED_REGIONS = ["VN", "SG", "IND", "BR", "US", "NA", "RU", "ID", "TW", "TH", "ME", "PK", "CIS", "BD", "EUROPE"]

# === Flask App Setup ===

app = Flask(__name__)
CORS(app)
cache = TTLCache(maxsize=100, ttl=300)
cached_tokens = defaultdict(dict)
uid_region_cache = {}

# === Helper Functions ===

def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))

def decode_protobuf(encoded_data: bytes, message_type: message.Message) -> message.Message:
    instance = message_type()
    instance.ParseFromString(encoded_data)
    return instance

async def json_to_proto(json_data: str, proto_message: Message) -> bytes:
    json_format.ParseDict(json.loads(json_data), proto_message)
    return proto_message.SerializeToString()

def get_account_credentials(region: str) -> str:
    r = region.upper()
    if r == "IND":
        return "uid=4363983977&password=ISHITA_0AFN5_BY_SPIDEERIO_GAMING_UY12H"
    elif r in {"BR", "US", "NA"}:
        return "uid=4682784982&password=GHOST_TNVW1_RIZER_QTFT0"
    else:
        return "uid=4418979127&password=RIZER_K4CY1_RIZER_WNX02"

# === Token Generation ===

async def get_access_token(account: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = account + "&response_type=token&client_type=2&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3&client_id=100067"
    headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip", 'Content-Type': "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload, headers=headers)
        data = resp.json()
        return data.get("access_token", "0"), data.get("open_id", "0")

async def create_jwt(region: str):
    print(f"[DEBUG] Creating JWT for region: {region}")
    account = get_account_credentials(region)
    token_val, open_id = await get_access_token(account)
    
    body = json.dumps({"open_id": open_id, "open_id_type": "4", "login_token": token_val, "orign_platform_type": "4"})
    proto_bytes = await json_to_proto(body, FreeFire_pb2.LoginReq())
    payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)
    url = "https://loginbp.ggblueshark.com/MajorLogin"
    headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
               'Content-Type': "application/octet-stream", 'Expect': "100-continue", 'X-Unity-Version': "2018.4.11f1",
               'X-GA': "v1 1", 'ReleaseVersion': RELEASEVERSION}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload, headers=headers)
        
        try:
            msg = json.loads(json_format.MessageToJson(decode_protobuf(resp.content, FreeFire_pb2.LoginRes)))
            
            if 'queueInfo' in msg:
                print(f"[WARNING] Region {region} is in queue, skipping...")
                return False
            
            cached_tokens[region] = {
                'token': f"Bearer {msg.get('token','0')}",
                'region': msg.get('lockRegion','0'),
                'server_url': msg.get('serverUrl','0'),
                'expires_at': time.time() + 25200
            }
            print(f"[DEBUG] ✓ Token cached for {region}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to create JWT for {region}: {e}")
            return False

async def initialize_tokens():
    print("[DEBUG] Initializing tokens...")
    for region in SUPPORTED_REGIONS[:5]:  # Chỉ lấy 5 region đầu để tránh timeout
        await create_jwt(region)
        await asyncio.sleep(0.3)
    print("[DEBUG] Initialization complete")

async def get_token_info(region: str) -> Tuple[str, str, str]:
    info = cached_tokens.get(region)
    if info and time.time() < info['expires_at']:
        return info['token'], info['region'], info['server_url']
    await create_jwt(region)
    info = cached_tokens[region]
    return info['token'], info['region'], info['server_url']

# === Tạo payload cho GetPlayerBriefInfo ===

def make_brief_info_payload(uid: int) -> bytes:
    result = bytearray()
    result.append(0x08)
    n = uid
    while n > 0x7F:
        result.append((n & 0x7F) | 0x80)
        n >>= 7
    result.append(n)
    result.extend([0x10, 0x01])
    return bytes(result)

# === API Call ===

async def GetPlayerBriefInfo(uid: int, region: str):
    print(f"[DEBUG] Fetching UID: {uid}, region: {region}")
    
    payload = make_brief_info_payload(uid)
    data_enc = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, payload)
    
    token, lock, server = await get_token_info(region)
    
    headers = {
        'User-Agent': USERAGENT,
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Content-Type': "application/octet-stream",
        'Authorization': token,
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': RELEASEVERSION
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            server + "/GetPlayerBriefInfo", 
            data=data_enc, 
            headers=headers,
            timeout=30.0
        )
        
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")
        
        if len(resp.content) < 10:
            raise Exception("Empty response")
        
        result = decode_protobuf(resp.content, AccountPersonalShow_pb2.AccountPersonalShowInfo)
        return json.loads(json_format.MessageToJson(result))

# === Flask Routes ===

@app.route('/player-info')
def get_account_info():
    uid_param = request.args.get('uid')
    if not uid_param:
        return jsonify({"error": "Please provide UID."}), 400
    
    try:
        uid = int(uid_param)
    except ValueError:
        return jsonify({"error": "UID must be a number."}), 400
    
    # Tạo event loop mới cho request
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Thử từng region
        for region in SUPPORTED_REGIONS:
            if region not in cached_tokens:
                continue
                
            try:
                return_data = loop.run_until_complete(GetPlayerBriefInfo(uid, region))
                uid_region_cache[uid_param] = region
                formatted_json = json.dumps(return_data, indent=2, ensure_ascii=False)
                return formatted_json, 200, {'Content-Type': 'application/json; charset=utf-8'}
            except Exception as e:
                print(f"[ERROR] {region} failed: {e}")
                continue
        
        return jsonify({"error": "UID not found in any region."}), 404
    
    finally:
        loop.close()

@app.route('/refresh', methods=['GET', 'POST'])
def refresh_tokens():
    """Refresh tokens (có thể gọi bằng cron job)"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(initialize_tokens())
        return jsonify({'message': 'Tokens refreshed.'}), 200
    except Exception as e:
        return jsonify({'error': f'Refresh failed: {e}'}), 500
    finally:
        loop.close()

@app.route('/')
def home():
    return jsonify({
        'message': 'FreeFire API on Vercel',
        'endpoints': {
            '/player-info?uid=XXX': 'Get player info',
            '/refresh': 'Refresh tokens',
        }
    })

# Vercel cần biến 'app' để export
# Không chạy app.run() khi ở Vercel
if __name__ == '__main__':
    # Chỉ chạy local development
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(initialize_tokens())
    app.run(host='0.0.0.0', port=5000, debug=True)
