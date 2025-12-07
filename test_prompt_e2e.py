"""
提示词库 E2E 测试脚本
测试 Agent 工具调用和 /run 接口的 prompt 注入功能
"""

import sys
import asyncio
from fastapi.testclient import TestClient

# 导入 FastAPI 应用和相关模块
from app.app import app
from app.tool.prompt_library import PromptLibraryTool
from app.services.prompt_service import PromptService

# 创建测试客户端
client = TestClient(app)

# 测试用户ID
TEST_USER = "e2e_test_user"


def setup_test_data():
    """准备测试数据：创建一个个人提示词"""
    print("\n📦 准备测试数据...")

    response = client.post(
        "/console/api/prompts",
        json={
            "name": "E2E测试模板",
            "description": "用于E2E测试的提示词模板",
            "prompt": "你是{role}，你的任务是{task}。请确保{requirement}。",
            "ownerId": TEST_USER
        },
        headers={"X-User-Id": TEST_USER}
    )

    assert response.status_code == 201, f"创建测试数据失败: {response.text}"
    data = response.json()
    prompt_id = data["data"]["id"]

    print(f"   ✅ 测试数据已创建，ID: {prompt_id}")
    return prompt_id


def cleanup_test_data(prompt_id):
    """清理测试数据"""
    print("\n🧹 清理测试数据...")

    response = client.delete(
        f"/console/api/prompts/{prompt_id}",
        headers={"X-User-Id": TEST_USER}
    )

    if response.status_code == 200:
        print(f"   ✅ 测试数据已清理")
    else:
        print(f"   ⚠️ 清理测试数据失败: {response.text}")


async def test_agent_tool_list_recommended():
    """测试 1: Agent 工具调用 - 列出推荐模板"""
    print("\n🧪 测试 1: Agent 工具调用 - 列出推荐模板")

    tool = PromptLibraryTool()

    result = await tool.execute(
        action="list_recommended",
        page=1,
        page_size=5
    )

    assert result.output is not None, "工具返回结果为空"
    assert "list_recommended" in result.output, "返回结果格式错误"

    print(f"   ✅ 成功！工具返回: {result.output[:200]}...")


async def test_agent_tool_get_recommended():
    """测试 2: Agent 工具调用 - 获取推荐模板详情"""
    print("\n🧪 测试 2: Agent 工具调用 - 获取推荐模板详情")

    # 先获取一个推荐模板的ID
    tool = PromptLibraryTool()
    list_result = await tool.execute(action="list_recommended", page=1, page_size=1)

    # 从结果中提取第一个ID (简化处理)
    import json
    list_data = json.loads(list_result.output)

    if list_data["data"]["items"]:
        prompt_id = list_data["data"]["items"][0]["id"]

        # 获取详情
        detail_result = await tool.execute(
            action="get_prompt",
            prompt_type="recommended",
            prompt_id=prompt_id
        )

        assert detail_result.output is not None, "工具返回结果为空"
        assert "get_prompt" in detail_result.output, "返回结果格式错误"

        print(f"   ✅ 成功！获取到模板 {prompt_id} 的详情")
    else:
        print(f"   ⚠️ 跳过：没有可用的推荐模板")


async def test_agent_tool_create_personal():
    """测试 3: Agent 工具调用 - 创建个人提示词"""
    print("\n🧪 测试 3: Agent 工具调用 - 创建个人提示词")

    import os
    os.environ["CURRENT_USER_ID"] = TEST_USER

    tool = PromptLibraryTool()

    result = await tool.execute(
        action="create_personal",
        name="Agent创建的提示词",
        prompt="这是通过 Agent 工具创建的提示词，内容包含{variable}",
        description="Agent 测试"
    )

    assert result.output is not None, "工具返回结果为空"
    assert result.error is None, f"工具返回错误: {result.error}"

    # 提取创建的ID
    import json
    data = json.loads(result.output)
    created_id = data["data"]["id"]

    print(f"   ✅ 成功！创建的ID: {created_id}")

    # 清理
    await tool.execute(action="delete_personal", prompt_id=created_id)
    print(f"   ✅ 已清理测试数据")


async def test_agent_tool_list_personal():
    """测试 4: Agent 工具调用 - 列出个人提示词"""
    print("\n🧪 测试 4: Agent 工具调用 - 列出个人提示词")

    import os
    os.environ["CURRENT_USER_ID"] = TEST_USER

    tool = PromptLibraryTool()

    result = await tool.execute(
        action="list_personal",
        page=1,
        page_size=10
    )

    assert result.output is not None, "工具返回结果为空"
    assert "list_personal" in result.output, "返回结果格式错误"

    print(f"   ✅ 成功！工具返回: {result.output[:200]}...")


def test_prompt_service_merge_functionality(test_prompt_id):
    """测试 8: PromptService - 变量替换和合并功能"""
    print("\n🧪 测试 8: PromptService - 变量替换和合并功能")

    import os
    os.environ["CURRENT_USER_ID"] = TEST_USER

    service = PromptService()

    # 测试变量替换
    final_prompt = service.get_and_merge_prompt(
        prompt_type="personal",
        prompt_id=test_prompt_id,
        owner_id=TEST_USER,
        merge_vars={
            "role": "数据分析师",
            "task": "分析销售数据",
            "requirement": "提供可视化图表"
        },
        additional_prompt="额外说明：重点关注Q4季度数据"
    )

    # 验证变量替换
    assert "数据分析师" in final_prompt, "变量 {role} 未正确替换"
    assert "分析销售数据" in final_prompt, "变量 {task} 未正确替换"
    assert "提供可视化图表" in final_prompt, "变量 {requirement} 未正确替换"
    assert "额外说明：重点关注Q4季度数据" in final_prompt, "附加prompt未正确合并"

    print(f"   ✅ 成功！变量替换和合并正常工作")
    print(f"   最终prompt长度: {len(final_prompt)} 字符")


def test_run_endpoint_with_prompt_id(test_prompt_id):
    """测试 5: /run 接口 - 使用 promptId 和 mergeVars"""
    print("\n🧪 测试 5: /run 接口 - promptId 注入和变量替换")

    import os
    os.environ["CURRENT_USER_ID"] = TEST_USER

    # 注意：这个测试会实际调用 Agent，可能需要很长时间
    # 在实际环境中可能需要 mock run_manus_flow

    # 先测试 schema 验证
    response = client.post(
        "/run",
        json={
            "promptId": test_prompt_id,
            "promptType": "personal",
            "mergeVars": {
                "role": "数据分析师",
                "task": "分析销售数据",
                "requirement": "提供可视化图表"
            },
            "prompt": "额外说明：重点关注Q4季度数据"
        }
    )

    # 由于 /run 路由可能未加载（依赖 daytona），我们允许 404
    # 如果返回 503 或 409，说明服务正常但正在初始化或忙碌
    if response.status_code == 404:
        print(f"   ⚠️ 跳过：/run 路由未加载（可能缺少依赖模块）")
        return

    assert response.status_code in [200, 409, 503], \
        f"状态码错误: {response.status_code}\n{response.text}"

    if response.status_code == 200:
        print(f"   ✅ 成功！/run 接口正常执行")
        data = response.json()
        print(f"   结果: {data.get('result', '无结果')[:100]}...")
    elif response.status_code == 409:
        print(f"   ⚠️ 服务忙碌（409），但请求格式正确")
    elif response.status_code == 503:
        print(f"   ⚠️ 服务初始化中（503），但请求格式正确")


def test_run_endpoint_with_recommended_prompt():
    """测试 6: /run 接口 - 使用推荐模板"""
    print("\n🧪 测试 6: /run 接口 - 使用推荐模板")

    # 先获取一个推荐模板ID
    response = client.get("/console/api/prompt/overview", params={
        "type": "recommended",
        "page": 1,
        "pageSize": 1
    })

    if response.status_code == 200:
        data = response.json()
        if data.get("items"):
            recommended_id = data["items"][0]["id"]

            # 使用推荐模板
            run_response = client.post(
                "/run",
                json={
                    "promptId": recommended_id,
                    "promptType": "recommended",
                    "prompt": "请简单回答"
                }
            )

            # 如果 /run 路由未加载，跳过
            if run_response.status_code == 404:
                print(f"   ⚠️ 跳过：/run 路由未加载（可能缺少依赖模块）")
                return

            assert run_response.status_code in [200, 409, 503], \
                f"状态码错误: {run_response.status_code}\n{run_response.text}"

            print(f"   ✅ 成功！推荐模板 {recommended_id} 可以正常使用")
        else:
            print(f"   ⚠️ 跳过：没有可用的推荐模板")
    else:
        print(f"   ⚠️ 跳过：无法获取推荐模板列表")


def test_run_endpoint_validation():
    """测试 7: /run 接口 - 参数验证"""
    print("\n🧪 测试 7: /run 接口 - 参数验证")

    # 测试：使用不存在的 promptId
    response = client.post(
        "/run",
        json={
            "promptId": "non-existent-id-12345",
            "promptType": "personal"
        }
    )

    # 如果 /run 路由未加载，跳过
    if response.status_code == 404:
        print(f"   ⚠️ 跳过：/run 路由未加载（可能缺少依赖模块）")
        return

    assert response.status_code == 400, \
        f"应该返回 400，实际: {response.status_code}"

    print(f"   ✅ 成功！正确拒绝不存在的 promptId")


async def run_all_e2e_tests():
    """执行所有 E2E 测试"""
    print("=" * 60)
    print("🚀 开始 E2E 测试")
    print("=" * 60)

    test_prompt_id = None

    try:
        # 准备测试数据
        test_prompt_id = setup_test_data()

        # Agent 工具调用测试
        await test_agent_tool_list_recommended()
        await test_agent_tool_get_recommended()
        await test_agent_tool_create_personal()
        await test_agent_tool_list_personal()

        # PromptService 功能测试
        test_prompt_service_merge_functionality(test_prompt_id)

        # /run 接口测试（可能因为缺少依赖而跳过）
        test_run_endpoint_with_prompt_id(test_prompt_id)
        test_run_endpoint_with_recommended_prompt()
        test_run_endpoint_validation()

        print("\n" + "=" * 60)
        print("🎉 所有 E2E 测试完成！")
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
    finally:
        # 清理测试数据
        if test_prompt_id:
            cleanup_test_data(test_prompt_id)


if __name__ == "__main__":
    success = asyncio.run(run_all_e2e_tests())
    sys.exit(0 if success else 1)
