---
title: Pandoc 功能全方位测试
subtitle: 用于验证 Markdown 转换效果的示例文档
author: Gemini AI & User
date: 2025-11-28
lang: zh-CN
---

# 1. 基础文本格式 (Typography)

这是一个段落，包含 **粗体文字**、*斜体文字*、***粗斜体*** 以及 `行内代码`。
甚至还可以使用 ~~删除线~~ 和上标^2^ 或 下标~sub~。

> **引言块测试：**
> “Pandoc 是一个通用的文档转换工具。”
> —— 这是一段引用文本，用于测试缩进和样式。

---

# 2. 列表结构 (Lists)

## 无序列表
* 苹果
* 香蕉
  * 这是一个嵌套的列表项
  * 测试缩进层级
* 橘子

## 有序列表
1. 第一步：安装 Pandoc
2. 第二步：准备 Markdown 文件
3. 第三步：运行命令

---

# 3. 代码高亮 (Code Highlighting)

Pandoc 支持多种语言的语法高亮。下面是一个 Python 示例：

```python
def fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    
    sequence = [0, 1]
    while len(sequence) < n:
        next_val = sequence[-1] + sequence[-2]
        sequence.append(next_val)
    return sequence

print(fibonacci(10))
