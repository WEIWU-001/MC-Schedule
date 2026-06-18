# ==================== Gunicorn 配置文件 ====================
# 使用方式: gunicorn -c gunicorn.conf.py wsgi:app

# 工作进程数（建议设置为 CPU核心数 * 2 + 1）
workers = 4

# 工作线程数（每个进程的线程数）
threads = 2

# 绑定地址和端口
bind = '0.0.0.0:5000'

# 超时时间（秒）
timeout = 120

# 保持连接时间（秒）
keepalive = 60

# 进程名称
proc_name = 'mc-schedule'

# 日志配置
accesslog = 'logs/gunicorn_access.log'
errorlog = 'logs/gunicorn_error.log'
loglevel = 'info'

# 访问日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# 预加载应用（减少内存占用）
preload_app = True

# 最大请求数（自动重启进程，防止内存泄漏）
max_requests = 1000
max_requests_jitter = 100

# 用户和组（生产环境建议使用非root用户）
# user = 'www-data'
# group = 'www-data'