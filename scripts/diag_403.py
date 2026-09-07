"""
诊断 Twitter 403 的根因脚本。

背景:twscrape 在生成 x-client-transaction-id 时会先抓取 https://x.com/tesla,
这一步用 `rep.raise_for_status()` 直接抛 HttpStatusError 403,绕过正常错误分支,
导致日志只显示 "Unknown error. Account timeouted for 15 minutes",看不到被谁拒。

本脚本用浏览器指纹的 curl_cffi 后端去抓同一个页面,打印原始响应体,
从而区分是: Cloudflare 拦截 / X 鉴权拒 / 账号被封 / 网络问题。

用法(在项目根目录,有网络的环境):
    .venv/bin/python scripts/diag_403.py

依赖:
    pip install curl_cffi           # 未安装时脚本会提示(见 REQUIRED_BACKEND)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ENV = Path(".env")


def load_env_proxy() -> str:
    """返回 .env 里 PROXY_URL 的原始值(用于判断代理是否本地回环/是否被读到)。"""
    if ENV.exists():
        m = re.search(r"^PROXY_URL=(.*)$", ENV.read_text(), re.M)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return os.getenv("PROXY_URL", "")


def load_env_cookies() -> dict[str, str]:
    """从 .env 读 cookie,仅用于本地对照测试。"""
    if not ENV.exists():
        return {}
    txt = ENV.read_text()
    auth = re.search(r"^TWITTER_AUTH_TOKEN=(.*)$", txt, re.M)
    ct0 = re.search(r"^TWITTER_CT0=(.*)$", txt, re.M)
    d: dict[str, str] = {}
    if auth:
        d["auth_token"] = auth.group(1).strip().strip('"').strip("'")
    if ct0:
        d["ct0"] = ct0.group(1).strip().strip('"').strip("'")
    return d


def verdict(rep) -> str:
    """按响应头和响应体给出结论。"""
    status = rep.status_code
    ct = rep.headers.get("content-type", "")
    body = rep.text[:400] if hasattr(rep, "text") else ""
    low = body.lower()

    if status == 200:
        has_guest = "guest_id" in body or "auth_token" in body or "aria-label" in body
        return (
            "✅ OK 200 —— 引导页 https://x.com/tesla 抓取成功,此页未被拦" 
            + ("(页内含 cookie/guest 标记)" if has_guest else "(页面为空壳)")
            + " => 403 大概率不发生在引导页,而是在之后的 GraphQL 或账号层"
        )
    if status == 403 and ("cf-ray" in dict(rep.headers)):
        return "Cloudflare 拦截(cf-ray 存在)—— 出口 IP/指纹被 Cloudflare 拒"
    if status == 403 and "action=\"https://x.com/x/migrate" in body:
        return "Cloudflare 的 migrate 挑战(浏览器验证)—— 指纹/IP 被风控"
    if status == 403 and ("just a moment" in low or "attention required" in low):
        return "Cloudflare 人机验证页 —— 指纹/IP 被拦"
    if status == 403:
        return f"403 但不是 Cloudflare —— 见响应体判断内容: {body[:200]!r}"
    if status == 429:
        return "429 限流 —— 频次过高"
    if status >= 500:
        return f"{status} —— X 服务器内部错误"
    return f"{status} —— 未匹配到已知模式,见响应体"


async def probe(backend: str, proxy: str | None, cookies: dict[str, str]) -> str:
    httpx_imported = False
    try:
        import curl_cffi  # noqa: F401
        from curl_cffi.requests import AsyncSession
        httpx_imported = True
    except ImportError:
        httpx_imported = False

    if backend == "curl" and not httpx_imported:
        return "[curl 后端] 未安装 curl_cffi(需: pip install curl_cffi),跳过"

    try:
        if backend == "curl":
            session = AsyncSession(impersonate="chrome", proxy=proxy, allow_redirects=True)
            rep = await session.get("https://x.com/tesla", timeout=20)
            return f"[curl_cffi] {verdict(rep)}"
        else:
            import httpx
            async with httpx.AsyncClient(proxy=proxy, follow_redirects=True) as client:
                rep = await client.get("https://x.com/tesla", timeout=20)
                return f"[httpx] {verdict(rep)}"
    except Exception as e:
        return f"[{backend}] 请求异常: {type(e).__name__}: {e}"


async def main():
    proxy = load_env_proxy()
    cookies = load_env_cookies()
    print("=" * 60)
    print("PROXY_URL       :", f"{proxy[:16]}...({len(proxy)}char)" if proxy else "(空)")
    print(f"  scheme          : {proxy.split('://')[0] if '://' in proxy else '(无协议)'}")
    print(f"  是本机回环(127.): {'是 -> CI 上必然失效' if '127.0.0' in proxy else '否'}")
    print("cookie auth_token:", f"OK({len(cookies.get('auth_token',''))}c)" if cookies.get("auth_token") else "缺")
    print("cookie ct0       :", f"OK({len(cookies.get('ct0',''))}c)" if cookies.get("ct0") else "缺")
    print("=" * 60)

    print("\n[1] 用 curl_cffi(浏览器指纹)抓 x.com/tesla —— twscrape 生成签名时抓的就是这个页")
    print("    ", await probe("curl", proxy, cookies))
    print("\n[2] 用 httpx(默认后端)抓同一个页 —— 对照,复现你日志里的 backend=httpx")
    print("    ", await probe("httpx", proxy, cookies))


if __name__ == "__main__":
    asyncio.run(main())
