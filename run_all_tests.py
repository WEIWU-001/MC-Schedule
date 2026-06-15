#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""运行所有测试"""

import sys
import os
import subprocess
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def print_banner(text):
    """打印横幅"""
    width = 70
    print("\n" + "=" * width)
    print(text.center(width))
    print("=" * width)

def run_test(test_file, description):
    """运行单个测试文件"""
    print_banner(f"运行 {description}")
    
    try:
        # 运行测试文件
        result = subprocess.run(
            [sys.executable, test_file],
            capture_output=True,
            text=True,
            timeout=60  # 60秒超时
        )
        
        # 打印输出
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        # 返回是否成功
        if result.returncode == 0:
            print(f"\n✓ {description} 通过")
            return True
        else:
            print(f"\n✗ {description} 失败 (退出码: {result.returncode})")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"\n✗ {description} 超时")
        return False
    except Exception as e:
        print(f"\n✗ {description} 出错: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主函数"""
    print_banner("MC整合包档期排期站 - 测试套件")
    
    print("\n测试环境:")
    print(f"  - Python: {sys.version.split()[0]}")
    print(f"  - 工作目录: {os.getcwd()}")
    
    # 测试文件列表（tests/ 目录下）
    tests = [
        ("tests/test_app_basic.py", "基础功能测试"),
        ("tests/test_comprehensive.py", "综合测试"),
        ("tests/test_cache.py", "缓存系统测试"),
        ("tests/test_indexes.py", "数据库索引测试"),
        ("tests/test_api.py", "API路由测试")
    ]
    
    # 检查测试文件是否存在
    print("\n检查测试文件:")
    available_tests = []
    for test_file, description in tests:
        if os.path.exists(test_file):
            print(f"  ✓ {test_file}")
            available_tests.append((test_file, description))
        else:
            print(f"  ✗ {test_file} (不存在)")
    
    if not available_tests:
        print("\n没有找到任何测试文件！")
        sys.exit(1)
    
    # 询问是否运行所有测试
    print(f"\n找到 {len(available_tests)} 个测试文件")
    response = input("\n是否运行所有测试？(y/n): ").strip().lower()
    
    if response != 'y':
        print("\n取消测试")
        return
    
    # 运行所有测试
    print_banner("开始运行测试")
    
    results = {}
    start_time = time.time()
    
    for test_file, description in available_tests:
        results[description] = run_test(test_file, description)
        print()
    
    total_time = time.time() - start_time
    
    # 打印总结
    print_banner("测试总结")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\n总测试数: {total}")
    print(f"通过: {passed}")
    print(f"失败: {total - passed}")
    print(f"总耗时: {total_time:.2f}秒")
    
    print("\n详细结果:")
    print("-" * 50)
    for description, passed_test in results.items():
        status = "✓ 通过" if passed_test else "✗ 失败"
        print(f"  {description}: {status}")
    
    print("\n" + "=" * 70)
    
    if passed == total:
        print("🎉 所有测试通过！")
        sys.exit(0)
    else:
        print(f"⚠ {total - passed} 个测试未通过")
        sys.exit(1)

if __name__ == '__main__':
    main()
