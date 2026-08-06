"""
慧科研 API 签名生成工具

签名公式: SHA1(sorted([secret, timestamp, nonce]).join(""))
- nonce: 6位随机大写字母+数字
- timestamp: 13位毫秒时间戳
- signature: 40位十六进制 SHA1
- x-finger: 设备指纹 (MD5，独立于 signature，每次会话保持一致)
"""

import hashlib
import random
import string
import time
import uuid


def generate_nonce(length: int = 6) -> str:
    """生成随机 nonce（6位大写字母数字混合字符串）"""
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=length)
    )


def generate_timestamp() -> str:
    """生成毫秒级时间戳"""
    return str(int(time.time() * 1000))


def generate_signature(secret: str, timestamp: str, nonce: str) -> str:
    """
    核心签名算法
    公式: SHA1(sorted([secret, timestamp, nonce]).join(""))
    """
    parts = sorted([secret, timestamp, nonce])
    raw = "".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def generate_finger() -> str:
    """
    生成设备指纹 X-Finger
    基于 JS 前端 Object(S.f)() — 一个 MD5 格式的伪指纹
    每次蜘蛛会话生成一次，保持一致性
    """
    return hashlib.md5(
        str(uuid.uuid4().hex).encode()
    ).hexdigest()


def build_signature_headers(secret: str, finger: str) -> dict:
    """
    构建包含签名的完整请求头字典

    :param secret: 签名密钥
    :param finger: 设备指纹 (x-finger, 需保持一致)
    :return: dict with nonce, timestamp, signature, x-finger
    """
    nonce = generate_nonce()
    timestamp = generate_timestamp()
    signature = generate_signature(secret, timestamp, nonce)

    return {
        "nonce": nonce,
        "timestamp": timestamp,
        "signature": signature,
        "x-finger": finger,
    }
