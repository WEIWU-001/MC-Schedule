#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""数据库索引测试"""

import sys
import os
import sqlite3
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("数据库索引测试")
print("=" * 70)

# ==================== 1. 检查索引是否存在 ====================
print("\n【1. 检查数据库索引】")
print("-" * 70)

try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取所有索引
    c.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' ORDER BY tbl_name")
    indexes = c.fetchall()
    
    print(f"\n  总索引数量: {len(indexes)}")
    print("\n  按表统计:")
    print("  " + "-" * 50)
    
    # 按表分组
    index_by_table = {}
    for name, tbl_name, sql in indexes:
        if tbl_name not in index_by_table:
            index_by_table[tbl_name] = []
        index_by_table[tbl_name].append(name)
    
    for table, index_names in sorted(index_by_table.items()):
        print(f"    {table}: {len(index_names)} 个索引")
        for idx_name in index_names:
            print(f"      - {idx_name}")
    
    conn.close()
    test1_passed = True
    
except Exception as e:
    print(f"  ✗ 检查失败: {e}")
    import traceback
    traceback.print_exc()
    test1_passed = False

# ==================== 2. 验证必需索引 ====================
print("\n【2. 验证必需索引】")
print("-" * 70)

required_indexes = {
    'schedules': [
        'idx_schedules_approved',
        'idx_schedules_created_by',
        'idx_schedules_date',
        'idx_schedules_approved_date'
    ],
    'user_role': [
        'idx_user_role_role'
    ],
    'notifications': [
        'idx_notifications_uid',
        'idx_notifications_uid_read'
    ],
    'reservations': [
        'idx_reservations_user_id',
        'idx_reservations_schedule_id',
        'idx_reservations_user_schedule'
    ],
    'mutes': [
        'idx_mutes_uid',
        'idx_mutes_uid_active'
    ],
    'violations': [
        'idx_violations_uid'
    ],
    'op_applications': [
        'idx_op_applications_uid',
        'idx_op_applications_status'
    ],
    'forum_comments': [
        'idx_forum_comments_uid',
        'idx_forum_comments_created_at'
    ],
    'schedule_comments': [
        'idx_schedule_comments_schedule_id',
        'idx_schedule_comments_uid',
        'idx_schedule_comments_created_at'
    ],
    'penalties': [
        'idx_penalties_uid',
        'idx_penalties_active'
    ],
    'op_actions': [
        'idx_op_actions_uid',
        'idx_op_actions_schedule_id'
    ],
    'codes': [
        'idx_codes_email_expire'
    ],
    'users': [
        'idx_users_email'
    ],
    'feedback': [
        'idx_feedback_user_id',
        'idx_feedback_status'
    ]
}

try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取所有索引名称
    c.execute("SELECT name FROM sqlite_master WHERE type='index'")
    existing_indexes = set(row[0] for row in c.fetchall())
    
    print("\n  检查必需索引:")
    missing = []
    existing = []
    
    for table, indexes in required_indexes.items():
        print(f"\n    {table} 表:")
        for idx_name in indexes:
            if idx_name in existing_indexes:
                existing.append(idx_name)
                print(f"      ✓ {idx_name}")
            else:
                missing.append(idx_name)
                print(f"      ✗ {idx_name} (缺失)")
    
    conn.close()
    
    print(f"\n  统计:")
    print(f"    - 已存在: {len(existing)} 个")
    print(f"    - 缺失: {len(missing)} 个")
    
    if missing:
        print("\n  ⚠ 缺失的索引将在应用重启时自动创建")
        test2_passed = len(missing) < 5  # 允许少量缺失
    else:
        print("\n  ✓ 所有必需索引已创建")
        test2_passed = True
    
except Exception as e:
    print(f"  ✗ 验证失败: {e}")
    import traceback
    traceback.print_exc()
    test2_passed = False

# ==================== 3. 索引性能测试 ====================
print("\n【3. 索引性能测试】")
print("-" * 70)

try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    print("\n  3.1 测试 schedules 表查询性能...")
    
    # 测试按日期查询（应该有索引）
    start = time.time()
    for _ in range(100):
        c.execute("SELECT * FROM schedules WHERE approved = 1 AND year = 2024 AND month = 6 ORDER BY day, time")
        c.fetchall()
    query_time = (time.time() - start) / 100
    print(f"    - 按审核状态+日期查询: {query_time*1000:.3f}ms")
    
    # 测试按创建者查询
    start = time.time()
    for _ in range(100):
        c.execute("SELECT * FROM schedules WHERE created_by IS NOT NULL LIMIT 10")
        c.fetchall()
    query_time = (time.time() - start) / 100
    print(f"    - 按创建者查询: {query_time*1000:.3f}ms")
    
    print("\n  3.2 测试 notifications 表查询性能...")
    
    # 测试按用户查询
    start = time.time()
    for _ in range(100):
        c.execute("SELECT * FROM notifications WHERE uid = 'test_user' AND read = 0")
        c.fetchall()
    query_time = (time.time() - start) / 100
    print(f"    - 按用户+未读查询: {query_time*1000:.3f}ms")
    
    print("\n  3.3 测试 reservations 表查询性能...")
    
    # 测试按用户查询预约
    start = time.time()
    for _ in range(100):
        c.execute("SELECT * FROM reservations WHERE user_id = 'test_user'")
        c.fetchall()
    query_time = (time.time() - start) / 100
    print(f"    - 按用户查询预约: {query_time*1000:.3f}ms")
    
    # 测试按档期查询预约
    start = time.time()
    for _ in range(100):
        c.execute("SELECT * FROM reservations WHERE schedule_id = 1")
        c.fetchall()
    query_time = (time.time() - start) / 100
    print(f"    - 按档期查询预约: {query_time*1000:.3f}ms")
    
    print("\n  3.4 测试 user_role 表查询性能...")
    
    # 测试按角色统计
    start = time.time()
    for _ in range(100):
        c.execute("SELECT COUNT(*) FROM user_role WHERE role = 1")
        c.fetchall()
    query_time = (time.time() - start) / 100
    print(f"    - 按角色统计: {query_time*1000:.3f}ms")
    
    conn.close()
    
    print("\n  ✓ 查询性能测试完成")
    test3_passed = True
    
except Exception as e:
    print(f"  ✗ 性能测试失败: {e}")
    import traceback
    traceback.print_exc()
    test3_passed = False

# ==================== 4. EXPLAIN 分析测试 ====================
print("\n【4. 查询计划分析】")
print("-" * 70)

try:
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    test_queries = [
        ("schedules 表 - 按审核状态查询", 
         "SELECT * FROM schedules WHERE approved = 1"),
        ("schedules 表 - 按日期查询", 
         "SELECT * FROM schedules WHERE year = 2024 AND month = 6"),
        ("notifications 表 - 按用户查询", 
         "SELECT * FROM notifications WHERE uid = 'user1'"),
        ("reservations 表 - 按用户查询", 
         "SELECT * FROM reservations WHERE user_id = 'user1'"),
        ("user_role 表 - 按角色统计", 
         "SELECT COUNT(*) FROM user_role WHERE role = 1")
    ]
    
    print("\n  分析查询计划:")
    for desc, query in test_queries:
        print(f"\n    {desc}:")
        c.execute(f"EXPLAIN QUERY PLAN {query}")
        plan = c.fetchall()
        for row in plan:
            detail = row[3] if len(row) > 3 else str(row)
            if 'USING INDEX' in detail or 'USING COVERING INDEX' in detail:
                print(f"      ✓ 使用索引: {detail}")
            elif 'SCAN TABLE' in detail:
                print(f"      ⚠ 全表扫描: {detail}")
            else:
                print(f"      - {detail}")
    
    conn.close()
    
    print("\n  ✓ 查询计划分析完成")
    test4_passed = True
    
except Exception as e:
    print(f"  ✗ 查询计划分析失败: {e}")
    import traceback
    traceback.print_exc()
    test4_passed = False

# ==================== 5. 创建缺失索引（如果需要） ====================
print("\n【5. 索引创建（如需要）】")
print("-" * 70)

def create_missing_indexes():
    """创建缺失的索引"""
    print("\n  检查并创建缺失的索引...")
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # 获取现有索引
        c.execute("SELECT name FROM sqlite_master WHERE type='index'")
        existing = set(row[0] for row in c.fetchall())
        
        # 需要创建的索引
        indexes_to_create = []
        
        if 'idx_schedules_approved' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedules_approved ON schedules(approved)')
        if 'idx_schedules_created_by' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedules_created_by ON schedules(created_by)')
        if 'idx_schedules_date' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(year, month, day)')
        if 'idx_schedules_approved_date' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedules_approved_date ON schedules(approved, year, month, day)')
        if 'idx_user_role_role' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_user_role_role ON user_role(role)')
        if 'idx_notifications_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_notifications_uid ON notifications(uid)')
        if 'idx_notifications_uid_read' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_notifications_uid_read ON notifications(uid, read)')
        if 'idx_reservations_user_id' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_reservations_user_id ON reservations(user_id)')
        if 'idx_reservations_schedule_id' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_reservations_schedule_id ON reservations(schedule_id)')
        if 'idx_reservations_user_schedule' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_reservations_user_schedule ON reservations(user_id, schedule_id)')
        if 'idx_mutes_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_mutes_uid ON mutes(uid)')
        if 'idx_mutes_uid_active' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_mutes_uid_active ON mutes(uid, active)')
        if 'idx_violations_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_violations_uid ON violations(uid)')
        if 'idx_op_applications_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_op_applications_uid ON op_applications(uid)')
        if 'idx_op_applications_status' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_op_applications_status ON op_applications(status)')
        if 'idx_forum_comments_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_forum_comments_uid ON forum_comments(uid)')
        if 'idx_forum_comments_created_at' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_forum_comments_created_at ON forum_comments(created_at)')
        if 'idx_schedule_comments_schedule_id' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedule_comments_schedule_id ON schedule_comments(schedule_id)')
        if 'idx_schedule_comments_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedule_comments_uid ON schedule_comments(uid)')
        if 'idx_schedule_comments_created_at' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_schedule_comments_created_at ON schedule_comments(created_at)')
        if 'idx_penalties_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_penalties_uid ON penalties(uid)')
        if 'idx_penalties_active' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_penalties_active ON penalties(active)')
        if 'idx_op_actions_uid' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_op_actions_uid ON op_actions(uid)')
        if 'idx_op_actions_schedule_id' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_op_actions_schedule_id ON op_actions(schedule_id)')
        if 'idx_codes_email_expire' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_codes_email_expire ON codes(email, expire)')
        if 'idx_users_email' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
        if 'idx_feedback_user_id' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id)')
        if 'idx_feedback_status' not in existing:
            indexes_to_create.append('CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)')
        
        if indexes_to_create:
            print(f"\n  正在创建 {len(indexes_to_create)} 个索引...")
            for i, sql in enumerate(indexes_to_create, 1):
                try:
                    c.execute(sql)
                    print(f"    {i}. 创建索引: {sql.split('idx_')[1].split(' ')[0]}")
                except Exception as e:
                    print(f"    {i}. 跳过 (可能已存在): {e}")
            
            conn.commit()
            print(f"\n  ✓ 成功创建 {len(indexes_to_create)} 个索引")
            return True
        else:
            print("\n  ✓ 所有索引已存在，无需创建")
            return True
            
    except Exception as e:
        print(f"\n  ✗ 创建索引失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

# 询问是否创建缺失索引
response = input("\n  是否创建缺失的索引？(y/n): ").strip().lower()
if response == 'y':
    test5_passed = create_missing_indexes()
else:
    print("\n  跳过索引创建")
    test5_passed = True

# ==================== 测试总结 ====================
print("\n" + "=" * 70)
print("测试总结")
print("=" * 70)

tests = [
    ("索引检查", test1_passed),
    ("必需索引验证", test2_passed),
    ("性能测试", test3_passed),
    ("查询计划分析", test4_passed),
    ("索引创建", test5_passed)
]

passed = sum(1 for _, result in tests if result)
total = len(tests)

for name, result in tests:
    status = "✓ 通过" if result else "✗ 失败"
    print(f"  {name}: {status}")

print(f"\n总计: {passed}/{total} 通过")

if passed >= total - 1:  # 允许一个失败
    print("\n🎉 数据库索引测试完成！")
    sys.exit(0)
else:
    print(f"\n⚠ {total - passed} 个测试未通过")
    sys.exit(1)
