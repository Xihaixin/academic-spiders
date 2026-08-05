"""
慧科研 v2 API 认证诊断工具

帮助你验证 Cookie 和 UID 是否有效，并测试文章搜索接口。
"""

import sys
from scholarin_spider import ScholarInSpider


def diagnose():
    print("╔══════════════════════════════════════════════╗")
    print("║   慧科研 API 认证诊断工具                      ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # ── Step 1: 收集认证信息 ──
    print("━" * 46)
    print("Step 1: 收集认证信息")
    print("━" * 46)
    print()
    print("请从浏览器中获取以下信息：")
    print()
    print("  1. 打开 https://scholarin.cn/explore 并登录")
    print("  2. F12 → Network → 在页面搜索一次")
    print("  3. 找到请求: /hky/api/v2/resources/article")
    print("  4. 查看 Request Headers:")
    print("     - 复制 Cookie 的完整值")
    print("     - 复制 x-xsrf-token 的值（备用）")
    print("  5. 查看 Request Payload:")
    print("     - 复制 uid 的值")
    print()

    # 获取 Cookie
    cookie = input("请输入 Cookie (直接回车跳过): ").strip()
    if not cookie:
        print("\n尝试从 cookies.txt 文件读取...")
        try:
            with open("cookies.txt", "r", encoding="utf-8") as f:
                cookie = f.read().strip()
            print(f"已从文件读取 Cookie ({len(cookie)} 字符)")
        except FileNotFoundError:
            print("未找到 cookies.txt 文件")

    if not cookie:
        print("\n⚠️  未提供 Cookie，v2 API 将会返回 403")
        print("   你可以稍后使用 --cookies 参数传入")

    # 获取 UID
    uid = input("\n请输入 uid (直接回车使用默认App ID): ").strip()

    # ── Step 2: 创建爬虫实例 ──
    print()
    print("━" * 46)
    print("Step 2: 初始化爬虫")
    print("━" * 46)

    # 不设代理（根据之前用户的设置，可能需要）
    use_proxy = input("\n是否使用代理 (http://127.0.0.1:7890)? [y/N]: ").strip().lower()
    if use_proxy == "y":
        spider = ScholarInSpider(
            cookies=cookie if cookie else None,
            uid=uid if uid else None,
            proxy="http://127.0.0.1:7890",
            max_retries=2,
        )
    else:
        spider = ScholarInSpider(
            cookies=cookie if cookie else None,
            uid=uid if uid else None,
            no_proxy=True,
            max_retries=2,
        )

    print(f"  UID: {spider._uid}")
    print(f"  Cookies: {len(spider.session.cookies)} 个")
    print(f"  XSRF-TOKEN: {'✅ 已获取' if spider._xsrf_token else '❌ 未获取'}")

    # ── Step 3: 测试公开接口 ──
    print()
    print("━" * 46)
    print("Step 3: 测试公开接口（验证签名机制）")
    print("━" * 46)

    import time
    timestamp = str(int(time.time() * 1000))
    nonce = spider._generate_nonce()
    signature = spider._generate_signature(timestamp, nonce)

    headers = {
        "nonce": nonce,
        "timestamp": timestamp,
        "signature": signature,
        "x-finger": signature,
        "Origin": "https://scholarin.cn",
    }

    r = spider.session.get(
        "https://scholarin.cn/hky/api/v1/hot-search-keywords",
        headers=headers,
        proxies=spider.proxies,
    )
    if r.status_code == 200:
        data = r.json()
        print(f"  ✅ 公开接口正常，获取到 {len(data)} 条热搜词")
        print(f"     签名: nonce={nonce}, sig={signature[:12]}...")
    else:
        print(f"  ❌ 公开接口失败: {r.status_code} {r.text[:100]}")

    # ── Step 4: 测试 v2 文章接口 ──
    print()
    print("━" * 46)
    print("Step 4: 测试 v2 文章搜索接口")
    print("━" * 46)

    query = input("\n搜索关键词 (默认'人工智能'): ").strip() or "人工智能"

    try:
        result = spider.search_articles(query=query, page=1)
        code = result.get("code", -1)
        data = result.get("data", {})
        total = data.get("total", 0)
        records = data.get("records", [])
        print(f"\n  ✅ v2 接口调用成功！")
        print(f"     状态码: {code}")
        print(f"     总结果数: {total}")
        print(f"     当前页记录数: {len(records)}")
        if records:
            print(f"\n  第一条记录预览:")
            r0 = records[0]
            print(f"     标题: {r0.get('title', 'N/A')[:80]}")
            print(f"     作者: {r0.get('authors', [{}])[0].get('name', 'N/A') if r0.get('authors') else 'N/A'}")
            print(f"     来源: {r0.get('source', 'N/A')}")
            print(f"     日期: {r0.get('pub_date', 'N/A')}")
    except Exception as e:
        print(f"\n  ❌ v2 接口调用失败: {e}")
        print()
        print("  可能原因：")
        print("  1. Cookie 无效或已过期 → 重新从浏览器复制")
        print("  2. UID 不匹配 → 确认 uid 与 Cookie 来自同一会话")
        print("  3. 网站需要重新登录 → 刷新 scholarin.cn 页面")

    # ── 保存配置 ──
    print()
    print("━" * 46)
    print("Step 5: 保存配置")
    print("━" * 46)

    if cookie:
        save = input("\n是否保存 Cookie 到 cookies.txt? [Y/n]: ").strip().lower()
        if save != "n":
            with open("cookies.txt", "w", encoding="utf-8") as f:
                f.write(cookie)
            print("  ✅ 已保存到 cookies.txt")
            print()
            print("  后续可直接使用:")
            print(f'  python scholarin_spider.py -q "关键词" -p 5 --cookies-file cookies.txt --uid {spider._uid} --extract')

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   诊断完成                                    ║")
    print("╚══════════════════════════════════════════════╝")


if __name__ == "__main__":
    diagnose()
