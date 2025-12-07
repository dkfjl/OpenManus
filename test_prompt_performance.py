"""
提示词库性能测试脚本
使用 pytest-benchmark 进行性能基准测试
"""

import time
import statistics
from typing import List, Dict
from fastapi.testclient import TestClient

from app.app import app
from app.services.prompt_service import PromptService
from app.services.prompt_storage import PromptStorage

# 创建测试客户端
client = TestClient(app)

# 测试用户ID
TEST_USER = "perf_test_user"


class PerformanceMetrics:
    """性能指标收集器"""

    def __init__(self):
        self.latencies: List[float] = []

    def record(self, latency_ms: float):
        """记录一次请求的延迟"""
        self.latencies.append(latency_ms)

    def get_percentile(self, p: int) -> float:
        """获取百分位数"""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        index = int(len(sorted_latencies) * p / 100)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]

    def get_stats(self) -> Dict[str, float]:
        """获取统计信息"""
        if not self.latencies:
            return {}

        return {
            "count": len(self.latencies),
            "min": min(self.latencies),
            "max": max(self.latencies),
            "mean": statistics.mean(self.latencies),
            "median": statistics.median(self.latencies),
            "p50": self.get_percentile(50),
            "p90": self.get_percentile(90),
            "p95": self.get_percentile(95),
            "p99": self.get_percentile(99),
        }


def setup_test_data(count: int = 100) -> List[str]:
    """准备测试数据"""
    print(f"\n📦 准备 {count} 条测试数据...")
    prompt_ids = []

    for i in range(count):
        response = client.post(
            "/console/api/prompts",
            json={
                "name": f"性能测试提示词_{i}",
                "description": f"用于性能测试的提示词 #{i}",
                "prompt": f"你是{{role}}，你的任务是{{task}}。这是第 {i} 条测试数据。",
                "ownerId": TEST_USER
            },
            headers={"X-User-Id": TEST_USER}
        )

        if response.status_code == 201:
            data = response.json()
            prompt_ids.append(data["data"]["id"])

    print(f"   ✅ 成功创建 {len(prompt_ids)} 条测试数据")
    return prompt_ids


def cleanup_test_data(prompt_ids: List[str]):
    """清理测试数据"""
    print(f"\n🧹 清理 {len(prompt_ids)} 条测试数据...")
    for prompt_id in prompt_ids:
        client.delete(
            f"/console/api/prompts/{prompt_id}",
            headers={"X-User-Id": TEST_USER}
        )
    print(f"   ✅ 测试数据已清理")


def test_list_recommended_prompts(iterations: int = 100):
    """测试：列出推荐模板性能"""
    print(f"\n🧪 测试 1: 列出推荐模板 ({iterations} 次)")

    metrics = PerformanceMetrics()

    for _ in range(iterations):
        start = time.time()
        response = client.get("/console/api/prompt/overview", params={
            "type": "recommended",
            "page": 1,
            "pageSize": 20
        })
        latency_ms = (time.time() - start) * 1000
        metrics.record(latency_ms)

        assert response.status_code == 200, f"请求失败: {response.status_code}"

    stats = metrics.get_stats()
    print(f"   📊 统计结果:")
    print(f"      - 请求次数: {stats['count']}")
    print(f"      - 平均延迟: {stats['mean']:.2f} ms")
    print(f"      - P50: {stats['p50']:.2f} ms")
    print(f"      - P95: {stats['p95']:.2f} ms")
    print(f"      - P99: {stats['p99']:.2f} ms")

    # 验证性能目标：P50 < 150ms
    if stats['p50'] < 150:
        print(f"   ✅ 性能达标！P50 ({stats['p50']:.2f} ms) < 150 ms")
    else:
        print(f"   ⚠️ 性能未达标！P50 ({stats['p50']:.2f} ms) >= 150 ms")

    return stats


def test_get_prompt_detail(prompt_ids: List[str], iterations: int = 100):
    """测试：获取提示词详情性能"""
    print(f"\n🧪 测试 2: 获取提示词详情 ({iterations} 次)")

    if not prompt_ids:
        print("   ⚠️ 跳过：没有测试数据")
        return

    metrics = PerformanceMetrics()

    for i in range(iterations):
        # 循环使用测试数据
        prompt_id = prompt_ids[i % len(prompt_ids)]

        start = time.time()
        response = client.get("/console/api/prompt/detail", params={
            "type": "personal",
            "id": prompt_id
        }, headers={"X-User-Id": TEST_USER})
        latency_ms = (time.time() - start) * 1000
        metrics.record(latency_ms)

        assert response.status_code == 200, f"请求失败: {response.status_code}"

    stats = metrics.get_stats()
    print(f"   📊 统计结果:")
    print(f"      - 请求次数: {stats['count']}")
    print(f"      - 平均延迟: {stats['mean']:.2f} ms")
    print(f"      - P50: {stats['p50']:.2f} ms")
    print(f"      - P95: {stats['p95']:.2f} ms")
    print(f"      - P99: {stats['p99']:.2f} ms")

    # 验证性能目标：P50 < 150ms
    if stats['p50'] < 150:
        print(f"   ✅ 性能达标！P50 ({stats['p50']:.2f} ms) < 150 ms")
    else:
        print(f"   ⚠️ 性能未达标！P50 ({stats['p50']:.2f} ms) >= 150 ms")

    return stats


def test_list_personal_prompts(iterations: int = 100):
    """测试：列出个人提示词性能"""
    print(f"\n🧪 测试 3: 列出个人提示词 ({iterations} 次)")

    metrics = PerformanceMetrics()

    for _ in range(iterations):
        start = time.time()
        response = client.get("/console/api/prompt/overview", params={
            "type": "personal",
            "page": 1,
            "pageSize": 20
        }, headers={"X-User-Id": TEST_USER})
        latency_ms = (time.time() - start) * 1000
        metrics.record(latency_ms)

        assert response.status_code == 200, f"请求失败: {response.status_code}"

    stats = metrics.get_stats()
    print(f"   📊 统计结果:")
    print(f"      - 请求次数: {stats['count']}")
    print(f"      - 平均延迟: {stats['mean']:.2f} ms")
    print(f"      - P50: {stats['p50']:.2f} ms")
    print(f"      - P95: {stats['p95']:.2f} ms")
    print(f"      - P99: {stats['p99']:.2f} ms")

    # 验证性能目标：P50 < 150ms
    if stats['p50'] < 150:
        print(f"   ✅ 性能达标！P50 ({stats['p50']:.2f} ms) < 150 ms")
    else:
        print(f"   ⚠️ 性能未达标！P50 ({stats['p50']:.2f} ms) >= 150 ms")

    return stats


def test_create_prompt_performance(iterations: int = 50):
    """测试：创建提示词性能"""
    print(f"\n🧪 测试 4: 创建提示词 ({iterations} 次)")

    metrics = PerformanceMetrics()
    created_ids = []

    for i in range(iterations):
        start = time.time()
        response = client.post(
            "/console/api/prompts",
            json={
                "name": f"性能测试创建_{i}",
                "description": "性能测试",
                "prompt": "测试内容",
                "ownerId": TEST_USER
            },
            headers={"X-User-Id": TEST_USER}
        )
        latency_ms = (time.time() - start) * 1000
        metrics.record(latency_ms)

        if response.status_code == 201:
            created_ids.append(response.json()["data"]["id"])

    stats = metrics.get_stats()
    print(f"   📊 统计结果:")
    print(f"      - 请求次数: {stats['count']}")
    print(f"      - 平均延迟: {stats['mean']:.2f} ms")
    print(f"      - P50: {stats['p50']:.2f} ms")
    print(f"      - P95: {stats['p95']:.2f} ms")
    print(f"      - P99: {stats['p99']:.2f} ms")

    # 清理创建的数据
    for prompt_id in created_ids:
        client.delete(
            f"/console/api/prompts/{prompt_id}",
            headers={"X-User-Id": TEST_USER}
        )

    return stats


def test_service_layer_performance():
    """测试：Service 层直接调用性能"""
    print(f"\n🧪 测试 5: Service 层性能（100 次）")

    service = PromptService()
    metrics = PerformanceMetrics()

    # 测试列表推荐模板
    for _ in range(100):
        start = time.time()
        service.list_prompts(prompt_type="recommended", page=1, page_size=20)
        latency_ms = (time.time() - start) * 1000
        metrics.record(latency_ms)

    stats = metrics.get_stats()
    print(f"   📊 Service 层统计:")
    print(f"      - 平均延迟: {stats['mean']:.2f} ms")
    print(f"      - P50: {stats['p50']:.2f} ms")
    print(f"      - P95: {stats['p95']:.2f} ms")

    if stats['p50'] < 50:
        print(f"   ✅ Service 层性能优秀！P50 ({stats['p50']:.2f} ms) < 50 ms")
    else:
        print(f"   ⚠️ Service 层性能需要优化")

    return stats


def run_all_performance_tests():
    """执行所有性能测试"""
    print("=" * 60)
    print("🚀 开始性能测试")
    print("=" * 60)

    # 准备测试数据
    test_data_ids = setup_test_data(100)

    try:
        # 运行测试
        test_list_recommended_prompts(100)
        test_get_prompt_detail(test_data_ids, 100)
        test_list_personal_prompts(100)
        test_create_prompt_performance(50)
        test_service_layer_performance()

        print("\n" + "=" * 60)
        print("🎉 性能测试完成！")
        print("=" * 60)

    finally:
        # 清理测试数据
        cleanup_test_data(test_data_ids)


if __name__ == "__main__":
    run_all_performance_tests()
