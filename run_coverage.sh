#!/bin/bash
# 测试覆盖率运行脚本 (Linux/Mac)
# 使用方法: ./run_coverage.sh

echo "========================================"
echo "   运行测试并生成覆盖率报告"
echo "========================================"
echo

# 检查是否安装了coverage
if ! python -c "import coverage" 2>/dev/null; then
    echo "[错误] 未安装 coverage，正在安装..."
    pip install coverage
fi

# 运行测试并收集覆盖率数据
echo "[1/3] 运行测试并收集覆盖率数据..."
coverage run -m pytest test_app_basic.py test_comprehensive.py test_cache.py test_indexes.py test_api.py -v --tb=short

# 生成覆盖率报告
echo
echo "[2/3] 生成覆盖率报告..."
coverage report --include="app.py,config.py"

# 生成HTML报告
echo
echo "[3/3] 生成HTML报告..."
coverage html --include="app.py,config.py"

echo
echo "========================================"
echo "   测试完成！"
echo "========================================"
echo
echo "覆盖率报告已生成："
echo "  - 控制台报告：上方显示"
echo "  - HTML报告：htmlcov/index.html"
echo
echo "查看HTML报告：open htmlcov/index.html"
echo
