# 测试文档

本文档介绍如何运行项目中的单元测试。

## 测试文件列表

项目包含以下测试文件：

### 1. `test_app_basic.py` - 基础功能测试
测试项目的基础功能，包括：
- 模块导入测试
- 权限常量测试
- 数据库连接测试
- 核心函数测试（如 `get_now_date`、`check_for_keywords`）
- Flask 路由测试（首页、登录页、注册页）
- 模板文件检查
- 数据库表结构检查
- 系统配置检查

**运行方法：**
```bash
python test_app_basic.py
```

### 2. `test_comprehensive.py` - 综合测试
全面的功能测试，覆盖：
- 缓存系统测试
- 数据库索引测试
- API路由测试
- 权限常量测试
- 数据库表结构测试
- 敏感词过滤测试

**运行方法：**
```bash
python test_comprehensive.py
```

### 3. `test_cache.py` - 缓存系统专项测试
专注于缓存系统的测试：
- 缓存管理器基础功能测试
- 缓存失效机制测试
- 业务缓存函数测试（标签、配置、友链）
- 缓存性能测试

**运行方法：**
```bash
python test_cache.py
```

### 4. `test_indexes.py` - 数据库索引测试
检查和验证数据库索引：
- 索引存在性检查
- 必需索引验证
- 索引性能测试
- 查询计划分析（EXPLAIN）
- 自动创建缺失索引

**运行方法：**
```bash
python test_indexes.py
```

### 5. `test_api.py` - API路由测试
测试所有 API 路由：
- 公开路由测试
- 认证路由测试
- API数据格式测试
- 错误处理测试
- 响应时间测试
- 权限控制测试

**运行方法：**
```bash
python test_api.py
```

### 6. `test_main.py` - 主邮箱测试
测试主邮箱配置：
```bash
python test_main.py
```

### 7. `test_email.py` - 邮箱池测试
测试所有邮箱配置：
```bash
python test_email.py
```

### 8. `test_backup.py` - 副邮箱测试
测试副邮箱配置：
```bash
python test_backup.py
```

### 9. `run_all_tests.py` - 测试运行器
一键运行所有测试：
```bash
python run_all_tests.py
```

## 运行所有测试

### 方法一：使用测试运行器（推荐）

```bash
python run_all_tests.py
```

这将自动检测并运行所有测试文件，然后显示汇总结果。

### 方法二：逐个运行

```bash
# 运行单个测试
python test_app_basic.py
python test_comprehensive.py
python test_cache.py
python test_indexes.py
python test_api.py
```

### 方法三：运行特定测试

```bash
# 只运行缓存测试
python -m pytest test_cache.py

# 或者直接运行
python test_cache.py
```

## 测试结果说明

每个测试文件都会输出详细的测试结果：

```
======================================
测试总结
======================================

总测试项: 8
通过: 7
失败: 1

详细结果:
--------------------------------------
✓ basic_import
✓ role_import
✓ db_connection
✓ get_now_date
✓ check_keywords
✓ home_route
✗ login_route
✓ templates
✓ db_tables
✓ system_config

======================================
⚠ 1 个测试未通过
======================================
```

## 常见问题

### Q: 测试失败怎么办？

1. 查看详细的错误信息
2. 检查数据库是否正确初始化
3. 确认所有依赖已安装
4. 检查配置文件是否正确

### Q: 如何查看更详细的输出？

运行测试时添加 `-v` 参数（如适用）：
```bash
python -v test_app_basic.py
```

### Q: 如何只测试特定功能？

可以直接导入并测试特定模块：
```python
from app import cache
cache.set('test', 'value')
assert cache.get('test') == 'value'
```

## 测试覆盖范围

项目测试覆盖以下主要功能：

| 功能模块 | 测试文件 | 覆盖范围 |
|---------|---------|---------|
| 基础功能 | test_app_basic.py | 导入、路由、配置 |
| 缓存系统 | test_cache.py | 缓存管理器、业务函数 |
| 数据库索引 | test_indexes.py | 索引检查、性能测试 |
| API路由 | test_api.py | 公开API、认证、错误处理 |
| 综合测试 | test_comprehensive.py | 全功能覆盖 |
| 邮箱功能 | test_main.py, test_email.py | SMTP配置 |

## 持续集成

建议在以下场景运行测试：

1. **开发时** - 每次修改代码后运行相关测试
2. **提交前** - 推送代码前运行完整测试套件
3. **部署前** - 上线前确保所有测试通过
4. **定时检查** - 定期运行测试确保功能正常

## 性能基准

测试还包含性能基准测试：

- 缓存命中：< 5ms
- 数据库查询（无索引）：< 50ms
- 数据库查询（有索引）：< 10ms
- API响应时间：< 100ms

## 扩展测试

如需添加新的测试，可以：

1. 在 `test_*.py` 文件中添加测试函数
2. 使用标准格式输出结果
3. 更新本文档说明新测试的用途
