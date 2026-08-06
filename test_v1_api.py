"""v1 API 连通性测试 — 使用真实 Cookie 和完整请求头"""
from academic_spiders.utils.signing import build_signature_headers
import requests
import json

url = "https://pubscholar.cn/hky/open/resources/api/v1/articles"
secret = "6m6pingbinwaktg227gngifoocrfbo95"

session = requests.Session()

# 直接设置 Cookie（来自用户浏览器）
session.cookies.set("XSRF-TOKEN", "115318a2-c245-446e-b005-1cee19f9fe49", domain="pubscholar.cn")
session.cookies.set("JSESSIONID", "ADE2864C54C437C14B2E7CB2C2CAB732", domain="pubscholar.cn")

headers = build_signature_headers(secret)
headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0",
    "Origin": "https://pubscholar.cn",
    "Referer": "https://pubscholar.cn/",
    # CSRF token
    "X-XSRF-TOKEN": "115318a2-c245-446e-b005-1cee19f9fe49",
    # 设备指纹 (独立于 signature)
    "x-finger": "c84069ed4e4270f9897e3a07acb81355",
    # Sec-Fetch 同源标记
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
})

payload = {
    "page": 1, "size": 10,
    "order_field": "date", "order_direction": "desc",
    "user_id": "0b68c4370e9a43e4ad1690fdd31f643f",
    "lang": "zh",
    "aggregations": {"type":"","subject":"","year":"","keyword":"","collection":"","lang":"C","source":"","correspAuthor":"","funding":"","institution":"","license":""}
}

print("Testing v1 API with real cookies...")
resp = session.post(url, json=payload, headers=headers, timeout=15)
print(f"Status: {resp.status_code}")

if resp.status_code == 200:
    data = resp.json()
    total = data.get("total", 0)
    content = data.get("content", [])
    print(f"Total: {total:,}, Page records: {len(content)}, is_last: {data.get('is_last')}")
    if content:
        r0 = content[0]
        print(f"Title: {r0.get('title','')[:80]}")
        print(f"Source: {r0.get('source')}, Year: {r0.get('year')}")
        print(f"DOI: {r0.get('doi')}")
        print(f"Authors: {r0.get('author')}")
        print(f"Keywords: {r0.get('keywords')}")
        print(f"Fields: {sorted(r0.keys())}")
        # Save first record for reference
        with open("result/sample_v1_record.json", "w", encoding="utf-8") as f:
            json.dump(r0, f, ensure_ascii=False, indent=2)
        print("\nSaved sample to result/sample_v1_record.json")
    print("✅ v1 API WORKS!")
else:
    print(f"❌ Failed: {resp.text[:300]}")
