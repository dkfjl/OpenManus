#!/usr/bin/env python3
"""
测试 AIPPT 集成的简单脚本
验证从大纲生成到 PPTX 文件的完整流程
"""

import asyncio
import json
from pathlib import Path

from app.services.aippt_generation_service import generate_pptx_from_aippt
from app.services.aippt_outline_service import generate_aippt_outline
from app.services.aippt_to_pptx_service import convert_aippt_slides_to_pptx


async def test_outline_generation():
    """测试大纲生成"""
    print("=== 测试大纲生成 ===")

    topic = "人工智能在医疗健康领域的应用"

    try:
        result = await generate_aippt_outline(
            topic=topic,
            language="zh",
            reference_content=None
        )

        print(f"大纲生成状态: {result['status']}")
        print(f"幻灯片数量: {len(result['outline'])}")

        # 保存大纲到文件用于调试
        outline_file = Path("test_outline.json")
        with open(outline_file, 'w', encoding='utf-8') as f:
            json.dump(result['outline'], f, ensure_ascii=False, indent=2)
        print(f"大纲已保存到: {outline_file}")

        return result['outline']

    except Exception as e:
        print(f"大纲生成失败: {e}")
        return None


async def test_pptx_conversion(slides_data):
    """测试 PPTX 转换"""
    print("\n=== 测试 PPTX 转换 ===")

    output_path = "test_output.pptx"

    try:
        result = convert_aippt_slides_to_pptx(slides_data, output_path)

        print(f"转换状态: {result['status']}")
        print(f"输出文件: {result['filepath']}")
        print(f"处理幻灯片数: {result['slides_processed']}")
        print(f"文件大小: {result['file_size']} 字节")

        # 检查文件是否存在
        if Path(output_path).exists():
            print(f"✅ PPTX 文件生成成功: {output_path}")
        else:
            print("❌ PPTX 文件未生成")

        return result

    except Exception as e:
        print(f"PPTX 转换失败: {e}")
        return None


async def test_full_integration():
    """测试完整集成流程"""
    print("=== 测试完整集成流程 ===")

    topic = "人工智能在医疗健康领域的应用"

    try:
        # 步骤1: 生成大纲
        outline_result = await generate_aippt_outline(
            topic=topic,
            language="zh",
            reference_content=None
        )

        if outline_result["status"] == "failed":
            print(f"大纲生成失败: {outline_result.get('error')}")
            return

        # 步骤2: 生成 PPTX（这会调用 AIPPT API）
        pptx_result = await generate_pptx_from_aippt(
            topic=topic,
            outline=outline_result["outline"],
            language="zh",
            style="通用",
            model="gemini-3-pro-preview",
            filepath="test_full_integration.pptx"
        )

        print(f"完整集成状态: {pptx_result['status']}")
        print(f"输出文件: {pptx_result['filepath']}")
        print(f"幻灯片数量: {pptx_result.get('slides_count', 0)}")
        print(f"生成时间: {pptx_result.get('generation_time', 0):.2f} 秒")

        if pptx_result["status"] == "completed":
            print("✅ 完整集成测试成功")
        else:
            print(f"❌ 完整集成测试失败: {pptx_result.get('error')}")

    except Exception as e:
        print(f"完整集成测试失败: {e}")


async def main():
    """主测试函数"""
    print("AIPPT 集成测试开始...\n")

    # 测试1: 仅大纲生成
    outline = await test_outline_generation()

    if outline:
        # 测试2: 本地 PPTX 转换（不调用 AIPPT API）
        await test_pptx_conversion(outline)

    # 测试3: 完整集成流程（调用 AIPPT API）
    # 注意：这需要 AIPPT API 服务运行在 http://192.168.1.119:3001
    # 如果 API 不可用，这个测试会失败
    print("\n" + "="*50)
    print("注意: 完整集成测试需要 AIPPT API 服务运行")
    print("如果 API 不可用，测试失败是正常的")
    print("="*50)

    try:
        await test_full_integration()
    except Exception as e:
        print(f"完整集成测试跳过（API 不可用）: {e}")

    print("\n测试完成！")


if __name__ == "__main__":
    asyncio.run(main())
