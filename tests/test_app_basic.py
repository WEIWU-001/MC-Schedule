#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 app.py 的基本功能"""

import sys
import os
import sqlite3

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("MC整合包档期排期站 - 基础功能测试")
print("=" * 70)

test_results = {}

# ==================== 1. 导入测试 ====================
print("\n【1. 导入测试】")
print("-" * 70)

print("\n测试 1.1: 检查基础模块导入...")
try:
    from app import app, get_now_date, check_for_keywords
    print("  ✓ 基础模块导入成功")
    test_results['basic_import'] = True
except Exception as e:
    print(f"  ✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    test_results['basic_import'] = False

print("\n测试 1.2: 检查权限常量导入...")
try:
    from app import ROLE_NORMAL, ROLE_OP, ROLE_TRUSTED_OP, ROLE_ADMIN, ROLE_SUPER_ADMIN
    print(f"  ✓ 权限常量导入成功")
    print(f"    - ROLE_NORMAL: {ROLE_NORMAL}")
    print(f"    - ROLE_OP: {ROLE_OP}")
    print(f"    - ROLE_TRUSTED_OP: {ROLE_TRUSTED_OP}")
    print(f"    - ROLE_ADMIN: {ROLE_ADMIN}")
    print(f"    - ROLE_SUPER_ADMIN: {ROLE_SUPER_ADMIN}")
    test_results['role_import'] = True
except Exception as e:
    print(f"  ✗ 导入失败: {e}")
    test_results['role_import'] = False

print("\n测试 1.3: 检查数据库连接...")
try:
    conn = sqlite3.connect('database.db')
    conn.close()
    print("  ✓ 数据库连接成功")
    test_results['db_connection'] = True
except Exception as e:
    print(f"  ✗ 数据库连接失败: {e}")
    test_results['db_connection'] = False

# ==================== 2. 函数测试 ====================
print("\n【2. 函数测试】")
print("-" * 70)

print("\n测试 2.1: 测试 get_now_date 函数...")
try:
    now = get_now_date()
    print(f"  ✓ 返回: {now}")
    assert 'year' in now
    assert 'month' in now
    assert 'day' in now
    print("  ✓ 返回格式正确")
    test_results['get_now_date'] = True
except Exception as e:
    print(f"  ✗ 失败: {e}")
    test_results['get_now_date'] = False

print("\n测试 2.2: 测试 check_for_keywords 函数...")
try:
    from app import load_sensitive_words
    load_sensitive_words()
    
    result1 = check_for_keywords("这是一条正常的消息")
    print(f"  - 正常消息: {'包含敏感词' if result1 else '干净'}")
    
    result2 = check_for_keywords("测试内容")
    print(f"  - 测试内容: {'包含敏感词' if result2 else '干净'}")
    
    print("  ✓ 函数工作正常")
    test_results['check_keywords'] = True
except Exception as e:
    print(f"  ✗ 失败: {e}")
    test_results['check_keywords'] = False

# ==================== 3. Flask路由测试 ====================
print("\n【3. Flask路由测试】")
print("-" * 70)

print("\n测试 3.1: 测试首页路由...")
try:
    with app.test_client() as client:
        response = client.get('/')
        print(f"  状态码: {response.status_code}")
        if response.status_code == 200:
            print("  ✓ 首页正常")
            test_results['home_route'] = True
        else:
            print(f"  ✗ 首页异常")
            test_results['home_route'] = False
except Exception as e:
    print(f"  ✗ 测试失败: {e}")
    test_results['home_route'] = False

print("\n测试 3.2: 测试登录页面...")
try:
    with app.test_client() as client:
        response = client.get('/login')
        print(f"  状态码: {response.status_code}")
        if response.status_code == 200:
            print("  ✓ 登录页正常")
            test_results['login_route'] = True
        else:
            print(f"  ✗ 登录页异常")
            test_results['login_route'] = False
except Exception as e:
    print(f"  ✗ 测试失败: {e}")
    test_results['login_route'] = False

print("\n测试 3.3: 测试注册页面...")
try:
    with app.test_client() as client:
        response = client.get('/register')
        print(f"  状态码: {response.status_code}")
        if response.status_code == 200:
            print("  ✓ 注册页正常")
            test_results['register_route'] = True
        else:
            print(f"  ✗ 注册页异常")
            test_results['register_route'] = False
except Exception as e:
    print(f"  ✗ 测试失败: {e}")
    test_results['register_route'] = False

# ==================== 4. 模板文件测试 ====================
print("\n【4. 模板文件测试】")
print("-" * 70)

print("\n测试 4.1: 检查模板目录...")
try:
    templates_path = os.path.join(os.path.dirname(__file__), 'templates')
    print(f"  模板路径: {templates_path}")
    
    if os.path.exists(templates_path):
        print("  ✓ 模板目录存在")
        files = os.listdir(templates_path)
        print(f"  文件数量: {len(files)}")
        
        required_templates = ['index.html', 'admin.html', 'error.html']
        missing = []
        for tmpl in required_templates:
            if tmpl in files:
                print(f"    ✓ {tmpl}")
            else:
                missing.append(tmpl)
                print(f"    ✗ {tmpl} (缺失)")
        
        test_results['templates'] = len(missing) == 0
    else:
        print("  ✗ 模板目录不存在")
        test_results['templates'] = False
except Exception as e:
    print(f"  ✗ 失败: {e}")
    test_results['templates'] = False

# ==================== 5. 数据库表测试 ====================
print("\n【5. 数据库表测试】")
print("-" * 70)

print("\n测试 5.1: 检查必需的数据表...")
try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    required_tables = [
        'users', 'user_role', 'schedules', 'notifications',
        'reservations', 'forum_comments', 'schedule_comments',
        'keywords', 'mutes', 'violations', 'penalties',
        'system_config', 'tags', 'schedule_tags', 'friend_links',
        'feedback', 'codes', 'email_usage', 'op_applications',
        'op_actions', 'operation_logs'
    ]
    
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = set(row[0] for row in c.fetchall())
    
    missing_tables = [t for t in required_tables if t not in existing_tables]
    
    if missing_tables:
        print(f"  ⚠ 缺失 {len(missing_tables)} 个表:")
        for t in missing_tables:
            print(f"    - {t}")
        test_results['db_tables'] = False
    else:
        print(f"  ✓ 所有 {len(required_tables)} 个必需表已创建")
        test_results['db_tables'] = True
    
    conn.close()
except Exception as e:
    print(f"  ✗ 失败: {e}")
    test_results['db_tables'] = False

# ==================== 6. 配置测试 ====================
print("\n【6. 配置测试】")
print("-" * 70)

print("\n测试 6.1: 检查系统配置...")
try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM system_config")
    count = c.fetchone()[0]
    print(f"  配置项数量: {count}")
    
    c.execute("SELECT key FROM system_config LIMIT 10")
    keys = [row[0] for row in c.fetchall()]
    print(f"  示例配置项: {', '.join(keys[:5])}")
    
    print("  ✓ 配置读取正常")
    test_results['system_config'] = True
    
    conn.close()
except Exception as e:
    print(f"  ✗ 失败: {e}")
    test_results['system_config'] = False

# ==================== 测试总结 ====================
print("\n" + "=" * 70)
print("测试总结")
print("=" * 70)

total = len(test_results)
passed = sum(1 for v in test_results.values() if v)

print(f"\n总测试项: {total}")
print(f"通过: {passed}")
print(f"失败: {total - passed}")

print("\n详细结果:")
print("-" * 70)

for name, result in test_results.items():
    status = "✓" if result else "✗"
    print(f"  {status} {name}")

print("\n" + "=" * 70)

if passed == total:
    print("🎉 所有基础测试通过！")
    print("=" * 70)
    sys.exit(0)
else:
    print(f"⚠ {total - passed} 个测试未通过")
    print("=" * 70)
    sys.exit(1)

