"""
提示词库 API 集成测试脚本
测试所有 HTTP 接口的功能
"""

import sys
import time
from fastapi.testclient import TestClient

# 导入 FastAPI 应用
from app.app import app

# 创建测试客户端
client = TestClient(app)

# 测试用户ID
TEST_USER = "test_user_001"


def test_overview_recommended():
    """测试：获取推荐模板列表"""
    print("\n🧪 测试 1: GET /console/api/prompt/overview (推荐模板)")

    response = client.get("/console/api/prompt/overview", params={
        "type": "recommended",
        "page": 1,
        "pageSize": 5
    })

    assert response.status_code == 200, f"状态码错误: {response.status_code}"
    data = response.json()

    assert "items" in data, "响应缺少 items 字段"
    assert "total" in data, "响应缺少 total 字段"
    assert data["total"] > 0, "推荐模板数量为0"

    print(f"   ✅ 成功！共 {data['total']} 个推荐模板")
    print(f"   返回 {len(data['items'])} 个项目")

    return data["items"][0]["id"] if data["items"] else None


def test_detail_recommended(prompt_id):
    """测试：获取推荐模板详情"""
    print(f"\n🧪 测试 2: GET /console/api/prompt/detail (推荐模板详情)")

    response = client.get("/console/api/prompt/detail", params={
        "type": "recommended",
        "id": prompt_id
    })

    assert response.status_code == 200, f"状态码错误: {response.status_code}"
    data = response.json()

    assert "data" in data, "响应缺少 data 字段"
    assert "prompt" in data["data"], "详情缺少 prompt 字段"

    print(f"   ✅ 成功！模板名称: {data['data']['name']}")
    print(f"   提示词长度: {len(data['data']['prompt'])} 字符")


def test_create_personal():
    """测试：创建个人提示词"""
    print(f"\n🧪 测试 3: POST /console/api/prompts (创建)")

    response = client.post(
        "/console/api/prompts",
        json={
            "name": "集成测试提示词",
            "description": "这是集成测试创建的提示词",
            "prompt": "你是{role}，你的任务是{task}",
            "ownerId": TEST_USER
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 201, f"状态码错误: {response.status_code}\n{response.text}"
    data = response.json()

    assert "data" in data, "响应缺少 data 字段"
    assert "id" in data["data"], "响应缺少 id 字段"
    assert data["message"] == "创建成功", "响应消息错误"

    prompt_id = data["data"]["id"]
    print(f"   ✅ 成功！创建的提示词 ID: {prompt_id}")

    return prompt_id


def test_overview_personal():
    """测试：获取个人提示词列表"""
    print(f"\n🧪 测试 4: GET /console/api/prompt/overview (个人提示词)")

    response = client.get(
        "/console/api/prompt/overview",
        params={
            "type": "personal",
            "page": 1,
            "pageSize": 10
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 200, f"状态码错误: {response.status_code}"
    data = response.json()

    assert data["total"] > 0, "个人提示词数量为0"
    print(f"   ✅ 成功！共 {data['total']} 个个人提示词")


def test_detail_personal(prompt_id):
    """测试：获取个人提示词详情"""
    print(f"\n🧪 测试 5: GET /console/api/prompt/detail (个人提示词详情)")

    response = client.get(
        "/console/api/prompt/detail",
        params={
            "type": "personal",
            "id": prompt_id
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 200, f"状态码错误: {response.status_code}"
    data = response.json()

    assert "data" in data, "响应缺少 data 字段"
    assert data["data"]["ownerId"] == TEST_USER, "所有者ID不匹配"

    print(f"   ✅ 成功！提示词名称: {data['data']['name']}")
    print(f"   版本号: {data['data']['version']}")

    return data["data"]["version"]


def test_update_personal(prompt_id, current_version):
    """测试：更新个人提示词"""
    print(f"\n🧪 测试 6: PUT /console/api/prompts/:id (更新)")

    response = client.put(
        f"/console/api/prompts/{prompt_id}",
        json={
            "name": "集成测试提示词（已更新）",
            "description": "描述已更新",
            "version": current_version
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 200, f"状态码错误: {response.status_code}\n{response.text}"
    data = response.json()

    assert data["message"] == "更新成功", "响应消息错误"
    print(f"   ✅ 成功！")

    # 验证更新
    detail_response = client.get(
        "/console/api/prompt/detail",
        params={"type": "personal", "id": prompt_id},
        headers={"X-User-Id": TEST_USER}
    )
    detail_data = detail_response.json()
    assert detail_data["data"]["name"] == "集成测试提示词（已更新）", "名称未更新"
    assert detail_data["data"]["version"] == current_version + 1, "版本号未自增"
    print(f"   ✅ 验证成功！新版本号: {detail_data['data']['version']}")


def test_search_by_name():
    """测试：按名称搜索"""
    print(f"\n🧪 测试 7: GET /console/api/prompt/overview (名称搜索)")

    response = client.get(
        "/console/api/prompt/overview",
        params={
            "type": "personal",
            "name": "集成测试",
            "page": 1,
            "pageSize": 10
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 200, f"状态码错误: {response.status_code}"
    data = response.json()

    assert data["total"] > 0, "搜索结果为空"
    assert "集成测试" in data["items"][0]["name"], "搜索结果不匹配"

    print(f"   ✅ 成功！找到 {data['total']} 个匹配项")


def test_version_conflict(prompt_id):
    """测试：版本冲突检测"""
    print(f"\n🧪 测试 8: PUT /console/api/prompts/:id (版本冲突)")

    response = client.put(
        f"/console/api/prompts/{prompt_id}",
        json={
            "name": "测试版本冲突",
            "version": 1  # 故意使用旧版本号
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 409, f"应该返回 409，实际: {response.status_code}"
    data = response.json()

    assert data["error"]["code"] == "CONFLICT", "错误码不正确"
    print(f"   ✅ 成功！正确检测到版本冲突")


def test_permission_denied():
    """测试：权限校验"""
    print(f"\n🧪 测试 9: DELETE /console/api/prompts/:id (权限拒绝)")

    # 尝试删除其他用户的提示词
    response = client.delete(
        f"/console/api/prompts/fake-id-12345",
        headers={"X-User-Id": "another_user"}
    )

    assert response.status_code in [403, 404], f"应该返回 403 或 404，实际: {response.status_code}"
    print(f"   ✅ 成功！正确拒绝跨用户访问")


def test_delete_personal(prompt_id):
    """测试：删除个人提示词"""
    print(f"\n🧪 测试 10: DELETE /console/api/prompts/:id (删除)")

    response = client.delete(
        f"/console/api/prompts/{prompt_id}",
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 200, f"状态码错误: {response.status_code}\n{response.text}"
    data = response.json()

    assert data["message"] == "删除成功", "响应消息错误"
    print(f"   ✅ 成功！")

    # 验证已删除
    detail_response = client.get(
        "/console/api/prompt/detail",
        params={"type": "personal", "id": prompt_id},
        headers={"X-User-Id": TEST_USER}
    )
    assert detail_response.status_code == 404, "删除后仍能访问"
    print(f"   ✅ 验证成功！提示词已不存在")


def test_validation_errors():
    """测试：数据验证"""
    print(f"\n🧪 测试 11: 数据验证（各种错误情况）")

    # 测试：名称过长
    response = client.post(
        "/console/api/prompts",
        json={
            "name": "a" * 30,  # 超过 20 字符
            "prompt": "test",
            "ownerId": TEST_USER
        },
        headers={"X-User-Id": TEST_USER}
    )
    assert response.status_code == 400, "应该拒绝过长的名称"
    print(f"   ✅ 正确拒绝过长名称")

    # 测试：缺少必填字段
    response = client.post(
        "/console/api/prompts",
        json={
            "name": "测试",
            "ownerId": TEST_USER
            # 缺少 prompt
        },
        headers={"X-User-Id": TEST_USER}
    )
    assert response.status_code == 422, "应该拒绝缺少必填字段"
    print(f"   ✅ 正确拒绝缺少必填字段")

    # 测试：pageSize 超限
    response = client.get(
        "/console/api/prompt/overview",
        params={
            "type": "recommended",
            "pageSize": 150  # 超过 100
        }
    )
    assert response.status_code == 422, "应该拒绝超限的 pageSize"
    print(f"   ✅ 正确拒绝超限分页参数")


def run_all_tests():
    """执行所有测试"""
    print("=" * 60)
    print("🚀 开始 API 集成测试")
    print("=" * 60)

    try:
        # 推荐模板相关
        recommended_id = test_overview_recommended()
        if recommended_id:
            test_detail_recommended(recommended_id)

        # 个人提示词 CRUD
        personal_id = test_create_personal()
        test_overview_personal()
        version = test_detail_personal(personal_id)
        test_update_personal(personal_id, version)

        # 搜索与过滤
        test_search_by_name()

        # 错误处理
        test_version_conflict(personal_id)
        test_permission_denied()
        test_validation_errors()

        # 清理：删除测试数据
        test_delete_personal(personal_id)

        print("\n" + "=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
        return True

    except AssertionError as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n💥 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
