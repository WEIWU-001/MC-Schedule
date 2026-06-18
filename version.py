#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本号更新脚本
用于更新 VERSION 文件中的版本号

用法:
    python version.py          # 交互式输入新版本号
    python version.py 1.2.3   # 直接指定版本号
    python version.py minor   # 自动递增小版本 (1.0.0 -> 1.1.0)
    python version.py major   # 自动递增大版本 (1.0.0 -> 2.0.0)
    python version.py patch   # 自动递增补丁版本 (1.0.0 -> 1.0.1)
    python version.py git     # 从 git tag 获取版本号
"""

import os
import sys
import re


def get_current_version():
    """获取当前版本号"""
    version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # 移除开头的 v
            if content.startswith('v'):
                content = content[1:]
            return content
    return "0.0.0"


def parse_version(version):
    """解析版本号字符串"""
    match = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None


def bump_version(version, level):
    """递增版本号"""
    major, minor, patch = parse_version(version)
    if level == 'major':
        return f"{major + 1}.0.0"
    elif level == 'minor':
        return f"{major}.{minor + 1}.0"
    elif level == 'patch':
        return f"{major}.{minor}.{patch + 1}"
    return version


def get_git_tag_version():
    """从 git tag 获取版本号"""
    try:
        import subprocess
        result = subprocess.run(
            ['git', 'describe', '--tags', '--abbrev=0'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            tag = result.stdout.strip()
            # 移除开头的 v
            if tag.startswith('v'):
                tag = tag[1:]
            return tag
    except:
        pass
    return None


def save_version(version):
    """保存版本号到文件"""
    version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(f"v{version}\n")
    print(f"版本号已更新为: v{version}")


def main():
    current = get_current_version()
    print(f"当前版本号: {current}")

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        if arg in ('major', 'minor', 'patch'):
            new_version = bump_version(current, arg)
            save_version(new_version)
            return
        
        if arg == 'git':
            git_version = get_git_tag_version()
            if git_version:
                save_version(git_version)
            else:
                print("错误: 无法从 git tag 获取版本号")
                sys.exit(1)
            return
        
        # 尝试作为直接版本号
        if parse_version(arg):
            save_version(arg)
            return
        
        print(f"错误: 无效的版本号或参数: {arg}")
        print("有效参数: major, minor, patch, git, 或 x.y.z 格式的版本号")
        sys.exit(1)
    else:
        # 交互式输入
        new_version = input("请输入新版本号 (直接回车取消): ").strip()
        if not new_version:
            print("已取消")
            return
        
        if parse_version(new_version):
            save_version(new_version)
        else:
            print("错误: 版本号格式无效，请使用 x.y.z 格式")
            sys.exit(1)


if __name__ == '__main__':
    main()
