import requests

# 填入你的 Upstash 信息
UPSTASH_URL = "https://your-database.upstash.io"
UPSTASH_TOKEN = "your_token_here"

key_to_delete = "xueqiu:status:last_ids"
url = f"{UPSTASH_URL}/del/{key_to_delete}"
headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}

resp = requests.get(url, headers=headers)
print(resp.json()) 
# 如果返回 {"result": 1} 说明删除成功
# 如果返回 {"result": 0} 说明本来就没这个 Key
