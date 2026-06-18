#!/bin/bash
# ==================== 生产环境部署脚本 ====================
# 使用方式:
#   bash deploy.sh start    # 启动服务
#   bash deploy.sh stop     # 停止服务
#   bash deploy.sh restart  # 重启服务
#   bash deploy.sh status   # 查看状态

APP_NAME="mc-schedule"
APP_DIR=$(cd "$(dirname "$0")" && pwd)
PID_FILE="$APP_DIR/gunicorn.pid"
LOG_FILE="$APP_DIR/logs/gunicorn_error.log"

start() {
    echo "[$APP_NAME] 启动中..."
    
    # 确保日志目录存在
    mkdir -p "$APP_DIR/logs"
    
    # 使用 Gunicorn 启动（后台运行）
    gunicorn -c "$APP_DIR/gunicorn.conf.py" wsgi:app --daemon --pid "$PID_FILE"
    
    if [ $? -eq 0 ]; then
        echo "[$APP_NAME] 启动成功！"
        echo "[$APP_NAME] 进程ID: $(cat "$PID_FILE")"
        echo "[$APP_NAME] 访问地址: http://localhost:5000"
    else
        echo "[$APP_NAME] 启动失败！"
        cat "$LOG_FILE" | tail -20
        exit 1
    fi
}

stop() {
    echo "[$APP_NAME] 停止中..."
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            sleep 2
            
            if kill -0 "$PID" 2>/dev/null; then
                echo "[$APP_NAME] 强制停止..."
                kill -9 "$PID"
            fi
            
            rm -f "$PID_FILE"
            echo "[$APP_NAME] 停止成功！"
        else
            rm -f "$PID_FILE"
            echo "[$APP_NAME] 进程已不存在"
        fi
    else
        echo "[$APP_NAME] 未运行（无PID文件）"
    fi
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        
        if kill -0 "$PID" 2>/dev/null; then
            echo "[$APP_NAME] 运行中"
            echo "进程ID: $PID"
            echo "内存使用: $(ps -p "$PID" -o %mem,rss | tail -1)"
            echo "启动时间: $(ps -p "$PID" -o lstart | tail -1)"
        else
            echo "[$APP_NAME] 未运行（PID文件存在但进程已死）"
            rm -f "$PID_FILE"
        fi
    else
        echo "[$APP_NAME] 未运行"
    fi
}

restart() {
    stop
    sleep 1
    start
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac