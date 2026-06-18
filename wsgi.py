# ==================== WSGI 入口文件 ====================
# 生产环境使用 Gunicorn 启动时的入口
# 命令: gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app

from app import app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)