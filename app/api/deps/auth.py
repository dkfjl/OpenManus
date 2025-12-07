"""
认证依赖
用于从请求中提取和验证用户身份
"""

import os
from typing import Optional
from fastapi import Header, HTTPException, status

from app.logger import logger


# 从环境变量读取配置
ENABLE_AUTH = os.getenv("ENABLE_AUTH", "false").lower() == "true"
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")


async def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer token"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id", description="开发模式用户ID")
) -> str:
    """
    获取当前用户ID

    认证策略:
    1. 生产模式 (ENABLE_AUTH=true): 解析 Authorization: Bearer <token>
    2. 开发模式 (ENABLE_AUTH=false): 使用 X-User-Id header 或默认用户

    Args:
        authorization: Authorization header
        x_user_id: X-User-Id header (开发模式)

    Returns:
        用户ID (ownerId)

    Raises:
        HTTPException: 认证失败时抛出 401
    """
    # 开发模式：使用 X-User-Id 或默认用户
    if not ENABLE_AUTH:
        user_id = x_user_id or "default_user"
        logger.debug(f"Development mode: using user_id={user_id}")
        return user_id

    # 生产模式：解析 JWT Token
    if not authorization:
        logger.warning("Missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败：缺少 Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 提取 Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning(f"Invalid Authorization header format: {authorization}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败：Authorization header 格式错误（应为 'Bearer <token>'）",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = parts[1]

    # 解析 JWT（简化实现，实际应使用 PyJWT 等库）
    try:
        # TODO: 实际生产环境应使用 PyJWT 解析和验证
        # import jwt
        # payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        # user_id = payload.get("sub")

        # 临时占位实现：假设 token 就是 user_id
        # 或者与现有认证系统集成
        user_id = _decode_token_placeholder(token)

        if not user_id:
            raise ValueError("Token does not contain user ID")

        logger.debug(f"Authenticated user: {user_id}")
        return user_id

    except Exception as e:
        logger.error(f"Token validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败：令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"}
        )


def _decode_token_placeholder(token: str) -> Optional[str]:
    """
    JWT 解析占位实现

    实际生产环境应替换为真实的 JWT 解析逻辑:

    ```python
    import jwt

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")  # 返回用户ID
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "令牌无效")
    ```

    Args:
        token: JWT token 字符串

    Returns:
        用户ID，如果解析失败返回 None
    """
    # 临时实现：假设 token 就是 base64 编码的 user_id
    # 或者从现有系统的认证服务获取
    try:
        import base64
        # 简单示例：token = base64(user_id)
        user_id = base64.b64decode(token).decode('utf-8')
        return user_id
    except Exception:
        # 回退：直接使用 token 作为 user_id（仅用于演示）
        logger.warning("Using token as user_id (placeholder implementation)")
        return token[:50]  # 限制长度


async def get_optional_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
) -> Optional[str]:
    """
    获取当前用户ID（可选，不强制认证）

    用于允许匿名访问的接口（如推荐模板列表）

    Args:
        authorization: Authorization header
        x_user_id: X-User-Id header

    Returns:
        用户ID，如果未认证返回 None
    """
    try:
        return await get_current_user(authorization, x_user_id)
    except HTTPException:
        return None
