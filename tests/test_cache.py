#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""缓存系统专项测试"""

import sys
import os
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("缓存系统专项测试")
print("=" * 70)

# ==================== 1. 缓存管理器基础测试 ====================
print("\n【1. 缓存管理器基础测试】")
print("-" * 70)

try:
    from app import CacheManager
    
    cache = CacheManager(default_ttl=5)  # 5秒过期
    
    print("\n  1.1 测试 set 和 get...")
    cache.set('key1', 'value1')
    assert cache.get('key1') == 'value1'
    print("    ✓ 设置和获取基本值")
    
    cache.set('key2', {'name': 'test', 'value': 123})
    assert cache.get('key2') == {'name': 'test', 'value': 123}
    print("    ✓ 设置和获取复杂对象")
    
    cache.set('key3', [1, 2, 3, 4, 5])
    assert cache.get('key3') == [1, 2, 3, 4, 5]
    print("    ✓ 设置和获取列表")
    
    print("\n  1.2 测试 has 方法...")
    assert cache.has('key1') == True
    assert cache.has('nonexistent') == False
    print("    ✓ has 方法正常工作")
    
    print("\n  1.3 测试 delete 方法...")
    cache.delete('key1')
    assert cache.get('key1') is None
    assert cache.has('key1') == False
    print("    ✓ delete 方法正常工作")
    
    print("\n  1.4 测试过期机制...")
    cache.set('expire_test', 'value', ttl=1)
    assert cache.has('expire_test') == True
    print("    - 等待缓存过期（1秒）...")
    time.sleep(1.5)
    assert cache.has('expire_test') == False
    print("    ✓ 缓存正确过期")
    
    print("\n  1.5 测试 clear 方法...")
    cache.set('key_a', 'value_a')
    cache.set('key_b', 'value_b')
    cache.set('key_c', 'value_c')
    cache.clear()
    assert cache.get('key_a') is None
    assert cache.get('key_b') is None
    assert cache.get('key_c') is None
    print("    ✓ clear 方法清空所有缓存")
    
    print("\n  ✓ 缓存管理器基础测试通过")
    test1_passed = True
    
except Exception as e:
    print(f"  ✗ 缓存管理器基础测试失败: {e}")
    import traceback
    traceback.print_exc()
    test1_passed = False

# ==================== 2. 缓存失效机制测试 ====================
print("\n【2. 缓存失效机制测试】")
print("-" * 70)

try:
    from app import cache, invalidate_cache, invalidate_all_cache
    
    cache.clear()
    
    print("\n  2.1 测试前缀匹配失效...")
    cache.set('user:1:profile', {'id': 1, 'name': 'Alice'})
    cache.set('user:1:settings', {'theme': 'dark'})
    cache.set('user:2:profile', {'id': 2, 'name': 'Bob'})
    cache.set('product:1:info', {'id': 1, 'name': 'Widget'})
    
    # 使 user:1:* 失效
    invalidate_cache('user:1')
    assert cache.get('user:1:profile') is None, "user:1:profile should be invalidated"
    assert cache.get('user:1:settings') is None, "user:1:settings should be invalidated"
    assert cache.get('user:2:profile') is not None, "user:2:profile should still exist"
    assert cache.get('product:1:info') is not None, "product:1:info should still exist"
    print("    ✓ 按前缀失效正确工作")
    
    print("\n  2.2 测试清空所有缓存...")
    cache.set('another_key', 'another_value')
    invalidate_all_cache()
    assert cache.get('user:2:profile') is None
    assert cache.get('another_key') is None
    print("    ✓ 清空所有缓存正确工作")
    
    print("\n  ✓ 缓存失效机制测试通过")
    test2_passed = True
    
except Exception as e:
    print(f"  ✗ 缓存失效机制测试失败: {e}")
    import traceback
    traceback.print_exc()
    test2_passed = False

# ==================== 3. 业务缓存函数测试 ====================
print("\n【3. 业务缓存函数测试】")
print("-" * 70)

try:
    from app import (
        get_all_tags, get_all_tags_simple, get_tag_name,
        get_site_configs_cached, get_single_config,
        get_all_friend_links, get_enabled_friend_links
    )
    
    cache.clear()  # 确保从干净状态开始
    
    print("\n  3.1 测试标签缓存...")
    
    # 首次调用 - 从数据库
    print("    - 首次获取标签列表...")
    tags1 = get_all_tags()
    print(f"      获取到 {len(tags1)} 个标签")
    
    # 第二次调用 - 从缓存
    print("    - 第二次获取标签列表（应从缓存）...")
    start = time.time()
    tags2 = get_all_tags()
    elapsed = time.time() - start
    assert tags1 == tags2
    assert elapsed < 0.01  # 缓存应该很快
    print(f"      耗时: {elapsed*1000:.3f}ms - 从缓存获取")
    
    # 测试简化版
    print("    - 测试简化标签列表...")
    tags_simple = get_all_tags_simple()
    assert isinstance(tags_simple, list)
    print(f"      获取到 {len(tags_simple)} 个简化标签")
    
    # 测试单个标签名称
    if tags_simple:
        tag_id = tags_simple[0]['id']
        tag_name = get_tag_name(tag_id)
        print(f"      标签ID {tag_id} 的名称: {tag_name}")
    
    print("\n  3.2 测试配置缓存...")
    
    # 首次调用 - 从数据库
    print("    - 首次获取配置...")
    configs1 = get_site_configs_cached()
    print(f"      获取到 {len(configs1)} 个配置项")
    
    # 第二次调用 - 从缓存
    print("    - 第二次获取配置（应从缓存）...")
    start = time.time()
    configs2 = get_site_configs_cached()
    elapsed = time.time() - start
    assert configs1 == configs2
    assert elapsed < 0.01
    print(f"      耗时: {elapsed*1000:.3f}ms - 从缓存获取")
    
    # 测试单个配置
    print("    - 测试单个配置获取...")
    site_title = get_single_config('site_title')
    print(f"      site_title: {site_title}")
    
    print("\n  3.3 测试友链缓存...")
    
    # 首次调用 - 从数据库
    print("    - 首次获取友链列表...")
    links1 = get_all_friend_links()
    print(f"      获取到 {len(links1)} 个友链")
    
    # 第二次调用 - 从缓存
    print("    - 第二次获取友链列表（应从缓存）...")
    start = time.time()
    links2 = get_all_friend_links()
    elapsed = time.time() - start
    assert links1 == links2
    assert elapsed < 0.01
    print(f"      耗时: {elapsed*1000:.3f}ms - 从缓存获取")
    
    # 测试启用友链
    print("    - 测试启用友链列表...")
    enabled_links = get_enabled_friend_links()
    assert isinstance(enabled_links, list)
    print(f"      获取到 {len(enabled_links)} 个启用友链")
    
    print("\n  ✓ 业务缓存函数测试通过")
    test3_passed = True
    
except Exception as e:
    print(f"  ✗ 业务缓存函数测试失败: {e}")
    import traceback
    traceback.print_exc()
    test3_passed = False

# ==================== 4. 缓存性能测试 ====================
print("\n【4. 缓存性能测试】")
print("-" * 70)

try:
    from app import get_all_tags, get_site_configs_cached, cache
    
    cache.clear()
    
    print("\n  4.1 测试标签缓存性能...")
    
    # 无缓存测试
    print("    - 无缓存（首次）...")
    start = time.time()
    for _ in range(10):
        cache.delete('get_all_tags')
        get_all_tags()
    no_cache_time = (time.time() - start) / 10
    print(f"      平均耗时: {no_cache_time*1000:.2f}ms")
    
    # 有缓存测试
    print("    - 有缓存（后续9次）...")
    start = time.time()
    for _ in range(9):
        get_all_tags()
    with_cache_time = (time.time() - start) / 9
    print(f"      平均耗时: {with_cache_time*1000:.2f}ms")
    
    speedup = no_cache_time / with_cache_time if with_cache_time > 0 else float('inf')
    print(f"    - 性能提升: {speedup:.1f}x")
    
    print("\n  4.2 测试配置缓存性能...")
    
    # 无缓存测试
    print("    - 无缓存（首次）...")
    start = time.time()
    for _ in range(10):
        cache.delete('get_site_configs')
        get_site_configs_cached()
    no_cache_time = (time.time() - start) / 10
    print(f"      平均耗时: {no_cache_time*1000:.2f}ms")
    
    # 有缓存测试
    print("    - 有缓存（后续9次）...")
    start = time.time()
    for _ in range(9):
        get_site_configs_cached()
    with_cache_time = (time.time() - start) / 9
    print(f"      平均耗时: {with_cache_time*1000:.2f}ms")
    
    speedup = no_cache_time / with_cache_time if with_cache_time > 0 else float('inf')
    print(f"    - 性能提升: {speedup:.1f}x")
    
    print("\n  ✓ 缓存性能测试完成")
    test4_passed = True
    
except Exception as e:
    print(f"  ✗ 缓存性能测试失败: {e}")
    import traceback
    traceback.print_exc()
    test4_passed = False

# ==================== 测试总结 ====================
print("\n" + "=" * 70)
print("测试总结")
print("=" * 70)

tests = [
    ("基础测试", test1_passed),
    ("失效机制测试", test2_passed),
    ("业务函数测试", test3_passed),
    ("性能测试", test4_passed)
]

passed = sum(1 for _, result in tests if result)
total = len(tests)

for name, result in tests:
    status = "✓ 通过" if result else "✗ 失败"
    print(f"  {name}: {status}")

print(f"\n总计: {passed}/{total} 通过")

if passed == total:
    print("\n🎉 所有缓存系统测试通过！")
    sys.exit(0)
else:
    print(f"\n⚠ {total - passed} 个测试未通过")
    sys.exit(1)
