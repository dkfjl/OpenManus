#!/usr/bin/env python3
"""
一键运行所有 Dify 知识库测试

这个脚本会按顺序运行所有测试，并生成测试报告
"""
import asyncio
import sys
import os
from datetime import datetime

# 确保可以导入项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


async def run_test(test_name, test_module):
    """运行单个测试"""
    print(f"\n{'='*80}")
    print(f"运行测试: {test_name}")
    print(f"{'='*80}\n")

    try:
        module = __import__(f"tests.manual.{test_module}", fromlist=['main'])
        await module.main()
        return True
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数 - 运行所有测试"""
    print("=" * 80)
    print("Dify 知识库集成 - 完整测试套件")
    print("=" * 80)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 检查配置
    try:
        from app.config import config
        if not config.dify or not config.dify.api_key:
            print("❌ 错误: Dify 配置未设置")
            print("请在 config/config.toml 中配置 [dify] 部分后再运行测试")
            return
    except Exception as e:
        print(f"❌ 配置加载失败: {str(e)}")
        return

    # 定义测试列表
    tests = [
        ("基本连接测试", "test_dify_connection"),
        ("工具功能测试", "test_dify_tool"),
        ("集成测试", "test_manus_integration"),
        ("性能测试", "test_dify_performance"),
    ]

    results = {}

    # 运行所有测试
    for test_name, test_module in tests:
        try:
            # 动态导入并运行测试
            success = await run_test(test_name, test_module)
            results[test_name] = "✅ 通过" if success else "❌ 失败"
        except Exception as e:
            print(f"\n❌ {test_name} 执行失败: {str(e)}")
            results[test_name] = "❌ 异常"

    # 生成测试报告
    print("\n" + "=" * 80)
    print("测试报告")
    print("=" * 80)
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    passed_count = sum(1 for status in results.values() if "✅" in status)
    failed_count = len(results) - passed_count

    print("测试结果:")
    for test_name, status in results.items():
        print(f"  {status} {test_name}")

    print()
    print(f"总测试数: {len(results)}")
    print(f"通过: {passed_count}")
    print(f"失败: {failed_count}")

    print("\n" + "=" * 80)
    if failed_count == 0:
        print("🎉 恭喜！所有测试通过！")
    else:
        print(f"⚠️  {failed_count} 个测试失败，请检查上面的错误信息")
    print("=" * 80)

    # 保存测试报告
    report_file = f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"Dify 知识库集成测试报告\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"测试结果:\n")
        for test_name, status in results.items():
            f.write(f"  {status} {test_name}\n")
        f.write(f"\n总测试数: {len(results)}\n")
        f.write(f"通过: {passed_count}\n")
        f.write(f"失败: {failed_count}\n")

    print(f"\n测试报告已保存到: {report_file}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试运行器出错: {str(e)}")
        import traceback
        traceback.print_exc()
