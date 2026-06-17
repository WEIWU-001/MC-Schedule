from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_mail import Mail, Message
import sqlite3
import hashlib
import random
from datetime import datetime, date, timedelta
import os
import time
import logging
from logging.handlers import RotatingFileHandler
import json # for TMS counter persistence
import shutil
import io
import csv
import bcrypt

# 服务器状态缓存
server_status_cache = {}
SERVER_STATUS_CACHE_DURATION = 10 * 60  # 10分钟缓存


# 导入腾讯云 SDK
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.tms.v20201229.tms_client import TmsClient
from tencentcloud.tms.v20201229.models import TextModerationRequest
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

# ===================== 日志配置 =====================
if os.name == 'posix':
    # Unix/Linux: 彩色输出
    os.environ['TERM'] = 'xterm-256color'
else:
    # Windows: 不支持颜色
    pass

def setup_logging():
    """配置日志系统"""
    # 创建日志目录
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 日志格式
    log_format = '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # 创建格式化器
    formatter = logging.Formatter(log_format, datefmt=date_format)
    
    # 获取根日志器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # 文件处理器（带轮转）
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # 错误日志文件处理器
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # 添加处理器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    
    return logger

# 初始化日志
logger = setup_logging()

# ===================== 权限常量 =====================
ROLE_NORMAL = 0       # 普通成员
ROLE_OP = 1          # 档主
ROLE_TRUSTED_OP = 2  # 信用档主（免审核，放宽限制）
ROLE_ADMIN = 3       # 普通管理员（不能设置管理员/信用档主）
ROLE_SUPER_ADMIN = 4 # 最高管理员（服主）
# ======================================================================

# ===================== 邮箱池配置 =====================
# 配置从 config.py 中读取
from config import EMAIL_POOL, TENCENT_SECRET_ID, TENCENT_SECRET_KEY, TMS_FREE_LIMIT, SUPER_ADMIN_ID
TMS_TOTAL_LIMIT = TMS_FREE_LIMIT

# TMS 计数器文件
TMS_STATUS_FILE = "tms_status.json"

def load_tms_status():
    """加载 TMS 调用计数状态"""
    if os.path.exists(TMS_STATUS_FILE):
        with open(TMS_STATUS_FILE, "r") as f:
            return json.load(f)
    return {"count": 0, "tms_status": "active", "last_update_date": str(date.today())}

def save_tms_status(status):
    """保存 TMS 调用计数状态"""
    with open(TMS_STATUS_FILE, "w") as f:
        json.dump(status, f)


# ===================== 内容审核模块 =====================
def tms_moderation(text):
    """使用腾讯云 TMS 进行文本审核"""
    if not TENCENT_SECRET_ID or not TENCENT_SECRET_KEY:
        print("[TMS] 警告: 未配置腾讯云 SecretId 或 SecretKey，跳过 TMS 审核。")
        return {"action": "pass", "reason": "未配置"}

    status = load_tms_status()

    if status["tms_status"] == "exhausted":
        print(f"[TMS] 已达到总调用限制 ({TMS_TOTAL_LIMIT} 条)，TMS 服务已停止。请更换 API 密钥或充值。")
        return {"action": "exhausted", "reason": "达到总调用限制"}

    if status["count"] >= TMS_TOTAL_LIMIT:
        status["tms_status"] = "exhausted"
        save_tms_status(status)
        print(f"[TMS] 已达到总调用限制 ({TMS_TOTAL_LIMIT} 条)，TMS 服务已停止。请更换 API 密钥或充值。")
        return {"action": "exhausted", "reason": "达到总调用限制"}

    try:
        cred = credential.Credential(TENCENT_SECRET_ID, TENCENT_SECRET_KEY)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "tms.tencentcloudapi.com"

        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        client = TmsClient(cred, "ap-guangzhou", clientProfile) # 假设区域为广州，可根据实际情况调整

        req = TextModerationRequest()
        req.Content = text.encode("utf-8").hex() # 文本内容需要进行hex编码

        resp = client.TextModeration(req)

        # 增加计数
        status["count"] += 1
        save_tms_status(status)

        # 解析响应
        # 更多详细信息请参考腾讯云文档：https://cloud.tencent.com/document/product/1124/51871
        if resp.Suggestion == "Block":
            print(f"[TMS] 评论被阻止: {text[:50]}...")
            return {"action": "block", "reason": resp.Keywords}
        elif resp.Suggestion == "Review":
            print(f"[TMS] 评论需要人工审核: {text[:50]}...")
            return {"action": "review", "reason": resp.Keywords}
        else:
            return {"action": "pass", "reason": ""}
    except TencentCloudSDKException as err:
        print(f"[TMS] 调用失败: {err}")
        return {"action": "error", "reason": str(err)}
    except Exception as e:
        print(f"[TMS] 发生未知错误: {e}")
        return {"action": "error", "reason": str(e)}

def perform_content_moderation(content):
    """执行内容审核，腾讯云 TMS -> 本地关键词过滤"""
    try:
        # 1. 本地关键词过滤 (始终执行)
        if check_for_keywords(content):
            return {"action": "block", "reason": "本地关键词过滤"}

        # 2. 腾讯云 TMS 审核
        tms_result = tms_moderation(content)
        if tms_result["action"] == "block":
            return tms_result
        elif tms_result["action"] == "review":
            return {"action": "block", "reason": "TMS 人工审核建议"}
        elif tms_result["action"] == "exhausted":
            print("[审核] TMS 已达到总调用限制，后续评论将仅使用本地关键词过滤。")
            return {"action": "pass", "reason": "TMS 已达限制，本地关键词通过"}
        elif tms_result["action"] == "error":
            print(f"[审核] TMS 调用失败，原因: {tms_result['reason']}。后续评论将仅使用本地关键词过滤。")
            return {"action": "pass", "reason": "TMS 异常，本地关键词通过"}
        
        # 3. 如果 TMS 通过，则内容通过审核
        return {"action": "pass", "reason": "TMS 通过"}

    except TencentCloudSDKException as err:
        print(f"[TMS] 调用失败: {err}，转为辅助过滤。")
        return {"action": "error", "reason": str(err)}
    except Exception as e:
        print(f"[TMS] 发生未知错误: {e}，转为辅助过滤。")
        return {"action": "error", "reason": str(e)}


# ===================== 初始化邮件配置 =====================
def init_mail_config(app, email_config):
    """初始化邮件配置"""
    app.config['MAIL_SERVER'] = email_config['smtp_server']
    app.config['MAIL_PORT'] = email_config['smtp_port']
    app.config['MAIL_USERNAME'] = email_config['username']
    app.config['MAIL_PASSWORD'] = email_config['password']
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_USE_SSL'] = True
    app.config['MAIL_DEFAULT_SENDER'] = email_config['username']

# 初始化数据库
def init_db(admin_username, admin_password, admin_email):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 用户表 - 添加数字ID和昵称字段
    c.execute('''CREATE TABLE IF NOT EXISTS users
                  (id TEXT PRIMARY KEY, 
                   uid INTEGER UNIQUE, 
                   nickname TEXT, 
                   pwd TEXT, 
                   email TEXT UNIQUE, 
                   verified INTEGER DEFAULT 0,
                   login_method INTEGER DEFAULT 0)''')  # login_method: 0-数字ID, 1-邮箱

    # 登录尝试记录表（防暴力破解）
    c.execute('''CREATE TABLE IF NOT EXISTS login_attempts
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   username TEXT,
                   ip_address TEXT,
                   attempt_time TEXT DEFAULT CURRENT_TIMESTAMP,
                   success INTEGER DEFAULT 0,
                   lock_until TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # 操作日志表
    c.execute('''CREATE TABLE IF NOT EXISTS operation_logs
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   ip_address TEXT,
                   action TEXT,
                   target TEXT,
                   detail TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (uid) REFERENCES users(id))''')
    
    # IP黑名单表
    c.execute('''CREATE TABLE IF NOT EXISTS ip_blacklist
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ip_address TEXT UNIQUE NOT NULL,
                   reason TEXT,
                   blocked_by TEXT,
                   blocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   expires_at TEXT,
                   created_by TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # 安全日志表
    c.execute('''CREATE TABLE IF NOT EXISTS security_logs
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT NOT NULL,
                   ip_address TEXT,
                   action TEXT NOT NULL,
                   target TEXT,
                   details TEXT,
                   created_at TEXT NOT NULL)''')

    # 用户权限表
    c.execute('''CREATE TABLE IF NOT EXISTS user_role
                  (uid TEXT PRIMARY KEY, role INTEGER DEFAULT 0,
                   FOREIGN KEY (uid) REFERENCES users(id))''')

    # 档期表（最新结构）
    c.execute('''CREATE TABLE IF NOT EXISTS schedules
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   year INTEGER, month INTEGER, day INTEGER,
                   type TEXT DEFAULT 'short',
                   end_year INTEGER, end_month INTEGER, end_day INTEGER,
                   time TEXT, server_id TEXT, 
                   ip TEXT, contact_type TEXT, contact_value TEXT,
                   keep INTEGER DEFAULT 1,
                   approved INTEGER DEFAULT 0,
                   active_status INTEGER DEFAULT 1,
                   mc_status_check INTEGER DEFAULT 0,
                   created_by TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # 弹幕表
    c.execute('''CREATE TABLE IF NOT EXISTS danmakus
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT, content TEXT,
                   likes INTEGER DEFAULT 0, time TEXT)''')

    # 验证码表
    c.execute('''CREATE TABLE IF NOT EXISTS codes
                  (email TEXT PRIMARY KEY, code TEXT, expire TEXT)''')

    # 档主申请表
    c.execute('''CREATE TABLE IF NOT EXISTS op_applications
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   server_ip TEXT,
                   qq_group TEXT,
                   status INTEGER DEFAULT 0,  -- 0: 待审核, 1: 已批准, 2: 已拒绝
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (uid) REFERENCES users(id))''')
    
    # 邮箱使用记录表
    c.execute('''CREATE TABLE IF NOT EXISTS email_usage
                  (email TEXT,
                   date TEXT,
                   count INTEGER DEFAULT 0,
                   last_used TEXT,
                   PRIMARY KEY (email, date))''')
    
    # 预约表
    c.execute('''CREATE TABLE IF NOT EXISTS reservations
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id TEXT,
                   schedule_id INTEGER,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   reminder_sent INTEGER DEFAULT 0,
                   FOREIGN KEY (user_id) REFERENCES users(id),
                   FOREIGN KEY (schedule_id) REFERENCES schedules(id))''')
    
    # 主论坛评论表（简化版）
    c.execute('''CREATE TABLE IF NOT EXISTS forum_comments
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   content TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (uid) REFERENCES users(id))''')
    
    # 档期小论坛评论表（简化版）
    c.execute('''CREATE TABLE IF NOT EXISTS schedule_comments
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   schedule_id INTEGER,
                   uid TEXT,
                   content TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (schedule_id) REFERENCES schedules(id),
                   FOREIGN KEY (uid) REFERENCES users(id))''')
    
    # 关键词表
    c.execute('''CREATE TABLE IF NOT EXISTS keywords
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   word TEXT UNIQUE)''')
    
    # 禁言记录表
    c.execute('''CREATE TABLE IF NOT EXISTS mutes
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   reason TEXT,
                   muted_by TEXT,
                   mute_type INTEGER,  -- 0: 永久禁言, 1: 限时禁言
                   mute_until TEXT,   -- NULL for permanent
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   active INTEGER DEFAULT 1,
                   unmuted_by TEXT,
                   unmuted_at TEXT,
                   FOREIGN KEY (uid) REFERENCES users(id),
                   FOREIGN KEY (muted_by) REFERENCES users(id))''')
    
    # 迁移：为 mutes 表添加 unmuted_by 和 unmuted_at 列
    try:
        c.execute("ALTER TABLE mutes ADD COLUMN unmuted_by TEXT")
    except:
        pass
    try:
        c.execute("ALTER TABLE mutes ADD COLUMN unmuted_at TEXT")
    except:
        pass
    
    # 通知表
    c.execute('''CREATE TABLE IF NOT EXISTS notifications
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   title TEXT,
                   content TEXT,
                   type TEXT,
                   read INTEGER DEFAULT 0,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (uid) REFERENCES users(id))''')
    
    # 档主操作记录表
    c.execute('''CREATE TABLE IF NOT EXISTS op_actions
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   action_type TEXT,  -- add_schedule, edit_schedule, edit_notify
                   schedule_id INTEGER,
                   date TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (uid) REFERENCES users(id),
                   FOREIGN KEY (schedule_id) REFERENCES schedules(id))''')
    
    # 检查并为用户表添加 is_muted 字段（如果不存在）
    try:
        c.execute("ALTER TABLE users ADD COLUMN is_muted INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # 检查并为用户表添加 email_locked 字段（如果不存在）
    try:
        c.execute("ALTER TABLE users ADD COLUMN email_locked INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # 用户违规记录表
    c.execute('''CREATE TABLE IF NOT EXISTS violations
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   content TEXT,
                   violation_type TEXT,  -- 违规类型（敏感词、AI检测等）
                   level INTEGER,        -- 违规等级（0:提醒, 1:警告, 2:通知管理员）
                   action_taken TEXT,     -- 已采取的措施
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (uid) REFERENCES users(id))''')
    
    # 惩罚记录表（包括禁言和其他惩罚）
    c.execute('''CREATE TABLE IF NOT EXISTS penalties
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   uid TEXT,
                   penalty_type TEXT,  -- 惩罚类型（mute, ban, warning等）
                   reason TEXT,
                   issued_by TEXT,
                   duration TEXT,      -- NULL 表示永久
                   active INTEGER DEFAULT 1,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   lifted_by TEXT,
                   lifted_at TEXT,
                   FOREIGN KEY (uid) REFERENCES users(id),
                   FOREIGN KEY (issued_by) REFERENCES users(id))''')
    
    # 检查并为用户表添加违规计数字段（如果不存在）
    try:
        c.execute("ALTER TABLE users ADD COLUMN violation_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # 检查并为用户表添加 is_banned 字段（如果不存在）
    try:
        c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # 系统配置表
    c.execute('''CREATE TABLE IF NOT EXISTS system_config
                  (key TEXT PRIMARY KEY, value TEXT)''')
    
    # 标签表
    c.execute('''CREATE TABLE IF NOT EXISTS tags
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT UNIQUE NOT NULL,
                   color TEXT DEFAULT '#42C9D8',
                   description TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # 档期标签关联表
    c.execute('''CREATE TABLE IF NOT EXISTS schedule_tags
                  (schedule_id INTEGER,
                   tag_id INTEGER,
                   PRIMARY KEY (schedule_id, tag_id),
                   FOREIGN KEY (schedule_id) REFERENCES schedules(id),
                   FOREIGN KEY (tag_id) REFERENCES tags(id))''')
    
    # 友链表
    c.execute('''CREATE TABLE IF NOT EXISTS friend_links
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL,
                   url TEXT NOT NULL,
                   icon TEXT,
                   description TEXT,
                   sort_order INTEGER DEFAULT 0,
                   enabled INTEGER DEFAULT 1,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # 用户反馈表
    c.execute('''CREATE TABLE IF NOT EXISTS feedback
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id TEXT,
                   nickname TEXT,
                   email TEXT,
                   type TEXT,
                   content TEXT,
                   status INTEGER DEFAULT 0,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    # 初始化默认配置：注册人数显示开关（默认关闭）
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("show_user_count", "0"))
    # 初始化默认配置：预约排行榜显示开关（默认关闭）
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("show_ranking", "0"))
    # 初始化默认配置：友链显示开关（默认关闭）
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("show_friend_links", "0"))
    # 初始化默认配置：网站维护模式（默认关闭）
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("maintenance_mode", "0"))
    # 初始化默认配置：维护模式提示信息
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("maintenance_message", "网站正在维护中，请稍后再试..."))
    
    # 初始化网站标题和公告
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("site_title", "MC整合包档期排期站"))
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("site_announcement", "公告：全年档期管理 | 注册需邮箱验证，权限划分：最高管理员 / 档主 / 普通成员"))
    c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)", 
              ("footer_text", "© 2026 MC整合包档期排期站 | 仅供学习交流使用"))
    
    conn.commit()
    
    # 检查并添加新字段（用于兼容现有数据库）
    try:
        c.execute("PRAGMA table_info(schedules)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'approved' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN approved INTEGER DEFAULT 0")
            print("已添加 approved 字段")
        
        if 'created_by' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN created_by TEXT")
            print("已添加 created_by 字段")
        
        if 'created_at' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
            print("已添加 created_at 字段")
        
        if 'type' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN type TEXT DEFAULT 'short'")
            print("已添加 type 字段")
        
        if 'end_year' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN end_year INTEGER")
            print("已添加 end_year 字段")
        
        if 'end_month' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN end_month INTEGER")
            print("已添加 end_month 字段")
        
        if 'end_day' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN end_day INTEGER")
            print("已添加 end_day 字段")
        
        if 'active_status' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN active_status INTEGER DEFAULT 1")
            print("已添加 active_status 字段")
        
        if 'mc_status_check' not in columns:
            c.execute("ALTER TABLE schedules ADD COLUMN mc_status_check INTEGER DEFAULT 0")
            print("已添加 mc_status_check 字段")
        
        conn.commit()
    except Exception as e:
        print(f"数据库迁移提示: {e}")
    
    # 迁移 login_attempts 表
    try:
        c.execute("PRAGMA table_info(login_attempts)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'created_at' not in columns:
            c.execute("ALTER TABLE login_attempts ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
            print("已为 login_attempts 添加 created_at 字段")
        
        conn.commit()
    except Exception as e:
        print(f"login_attempts 迁移提示: {e}")
    
    # 迁移 ip_blacklist 表
    try:
        c.execute("PRAGMA table_info(ip_blacklist)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'created_by' not in columns:
            c.execute("ALTER TABLE ip_blacklist ADD COLUMN created_by TEXT")
            print("已为 ip_blacklist 添加 created_by 字段")
        
        if 'created_at' not in columns:
            c.execute("ALTER TABLE ip_blacklist ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
            print("已为 ip_blacklist 添加 created_at 字段")
        
        conn.commit()
    except Exception as e:
        print(f"ip_blacklist 迁移提示: {e}")
    
    # 迁移旧版管理员(role=2)为最高管理员(role=4)
    try:
        c.execute("UPDATE user_role SET role = ? WHERE role = ?", (ROLE_SUPER_ADMIN, 2))
        if c.rowcount > 0:
            print(f"[迁移] 已将 {c.rowcount} 个旧版管理员升级为最高管理员")
        conn.commit()
    except Exception as e:
        print(f"[迁移] 失败: {e}")
    
    # 自动加载敏感词库
    try:
        # 检查是否已有敏感词
        c.execute("SELECT COUNT(*) FROM keywords")
        count = c.fetchone()[0]
        
        if count == 0:
            # 尝试从 sensitive_words.txt 加载
            if os.path.exists('sensitive_words.txt'):
                with open('sensitive_words.txt', 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                added = 0
                for line in lines:
                    word = line.strip()
                    if word and not word.startswith('#'):
                        try:
                            c.execute("INSERT OR IGNORE INTO keywords (word) VALUES (?)", (word,))
                            added += 1
                        except:
                            pass
                conn.commit()
                print(f"[敏感词] 已从文件加载 {added} 个敏感词")
            else:
                # 文件不存在，添加一些默认的敏感词
                default_words = ['赌博', '诈骗', '暴力', '色情', '毒品']
                for word in default_words:
                    try:
                        c.execute("INSERT OR IGNORE INTO keywords (word) VALUES (?)", (word,))
                    except:
                        pass
                conn.commit()
                print(f"[敏感词] 已添加默认敏感词库")
    except Exception as e:
        print(f"[敏感词] 加载失败: {e}")
    
    conn.close()
    
    load_sensitive_words()

# ===================== 禁言和通知模块 =====================
def is_user_muted(uid):
    """检查用户是否被禁言"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 先检查用户表的 is_muted 字段
        c.execute("SELECT is_muted FROM users WHERE id = ?", (uid,))
        result = c.fetchone()
        if not result or result[0] != 1:
            conn.close()
            return False, None
        
        # 检查活跃的禁言记录
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""SELECT id, reason, muted_by, mute_type, mute_until, created_at 
                      FROM mutes 
                      WHERE uid = ? AND active = 1
                      ORDER BY created_at DESC LIMIT 1""", (uid,))
        mute_record = c.fetchone()
        
        # 如果没有禁言记录，但有 is_muted=1，说明是旧数据，创建一个默认记录
        if not mute_record:
            c.execute("""INSERT INTO mutes (uid, reason, muted_by, mute_type, mute_until) 
                         VALUES (?, ?, ?, ?, ?)""", 
                      (uid, "系统禁言（旧数据迁移）", "系统", 0, None))
            conn.commit()
            mute_id = c.lastrowid
            mute_info = {
                'id': mute_id,
                'reason': "系统禁言（旧数据迁移）",
                'muted_by': "系统",
                'mute_type': '永久',
                'mute_until': None,
                'created_at': now
            }
            conn.close()
            return True, mute_info
        
        mute_id, reason, muted_by, mute_type, mute_until, created_at = mute_record
        
        # 如果是限时禁言，检查是否已过期
        if mute_type == 1 and mute_until:
            mute_until_dt = datetime.strptime(mute_until, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > mute_until_dt:
                # 已过期，更新为不活跃
                c.execute("UPDATE mutes SET active = 0 WHERE id = ?", (mute_id,))
                c.execute("UPDATE users SET is_muted = 0 WHERE id = ?", (uid,))
                conn.commit()
                conn.close()
                return False, None
        
        mute_info = {
            'id': mute_id,
            'reason': reason,
            'muted_by': muted_by,
            'mute_type': '永久' if mute_type == 0 else '限时',
            'mute_until': mute_until,
            'created_at': created_at
        }
        
        conn.close()
        return True, mute_info
    except Exception as e:
        print(f"[禁言] 检查失败: {e}")
        conn.close()
        return False, None


def create_notification(uid, title, content, notif_type='system'):
    """创建通知"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("""INSERT INTO notifications (uid, title, content, type) 
                     VALUES (?, ?, ?, ?)""", (uid, title, content, notif_type))
        conn.commit()
        print(f"[通知] 已发送通知给用户 {uid}: {title}")
        
        # 尝试发送邮件通知
        try:
            c.execute("SELECT email, verified FROM users WHERE id = ?", (uid,))
            user = c.fetchone()
            if user and user[0] and user[1] == 1:
                send_notification_email(user[0], title, content)
        except Exception as e:
            print(f"[通知] 邮件发送失败: {e}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"[通知] 创建失败: {e}")
        conn.close()
        return False


def send_notification_email(email, title, content):
    """发送邮件通知"""
    try:
        message = f"主题: {title}\n\n{content}\n\n--\n来自 MC 档期网站"
        msg = Message("来自MC档期网站的通知",
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[email])
        msg.body = message
        if use_pool and email_pool_manager:
            success = email_pool_manager.send_message(msg)
            if success:
                print(f"[邮件通知] 已发送邮件到 {email}")
            return success
        else:
            mail.send(msg)
            print(f"[邮件通知] 已发送邮件到 {email}")
            return True
    except Exception as e:
        print(f"[邮件通知] 发送失败: {e}")
        return False


NOTIFICATION_SETTINGS = {
    'welcome_notify': {
        'name': '注册欢迎通知',
        'description': '用户注册成功后的欢迎消息',
        'default_inbox': True,
        'default_email': False
    },
    'reservation_success': {
        'name': '预约成功通知',
        'description': '用户成功预约档期时的通知',
        'default_inbox': True,
        'default_email': True
    },
    'reservation_cancel': {
        'name': '预约取消通知',
        'description': '用户取消预约时的通知',
        'default_inbox': True,
        'default_email': False
    },
    'mute_notify': {
        'name': '禁言通知',
        'description': '用户被禁言时的通知',
        'default_inbox': True,
        'default_email': True
    },
    'unmute_notify': {
        'name': '解除禁言通知',
        'description': '用户被解除禁言时的通知',
        'default_inbox': True,
        'default_email': True
    },
    'penalty_notify': {
        'name': '惩罚通知',
        'description': '用户收到惩罚（警告、封禁等）时的通知',
        'default_inbox': True,
        'default_email': True
    },
    'violation_notify': {
        'name': '违规提醒',
        'description': '用户违规被检测到时的通知',
        'default_inbox': True,
        'default_email': False
    },
    'schedule_apply': {
        'name': '档期申请通知',
        'description': '档主提交新档期申请时通知管理员',
        'default_inbox': True,
        'default_email': True
    },
    'schedule_approve': {
        'name': '档期审核结果通知',
        'description': '档期审核通过或拒绝时通知档主',
        'default_inbox': True,
        'default_email': True
    },
    'schedule_delete': {
        'name': '档期取消通知',
        'description': '档期被取消时通知预约玩家',
        'default_inbox': True,
        'default_email': True
    },
    'op_apply': {
        'name': '档主申请通知',
        'description': '玩家申请成为档主时通知管理员',
        'default_inbox': True,
        'default_email': True
    },
    'op_approve': {
        'name': '档主申请结果通知',
        'description': '档主申请审核通过或拒绝时通知申请人',
        'default_inbox': True,
        'default_email': True
    },
    'reservation_reminder': {
        'name': '预约提醒',
        'description': '开服前提醒玩家',
        'default_inbox': True,
        'default_email': True
    },
    'system_notify': {
        'name': '系统通知',
        'description': '其他系统消息',
        'default_inbox': True,
        'default_email': False
    },
    'broadcast_notify': {
        'name': '管理员广播',
        'description': '管理员发送的全站广播消息',
        'default_inbox': True,
        'default_email': False
    },
    'schedule_update': {
        'name': '档期修改通知',
        'description': '档期信息修改时通知预约玩家',
        'default_inbox': True,
        'default_email': True
    }
}


def get_notification_setting(key, channel='inbox'):
    """获取通知设置"""
    if key not in NOTIFICATION_SETTINGS:
        return True
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        setting_key = f"notify_{key}_{channel}"
        c.execute("SELECT value FROM system_config WHERE key = ?", (setting_key,))
        row = c.fetchone()
        conn.close()
        
        if row is not None:
            return row[0] == '1'
        
        default = NOTIFICATION_SETTINGS[key].get(f'default_{channel}', True)
        return default
    except Exception as e:
        conn.close()
        print(f"[通知设置] 获取失败: {e}")
        return NOTIFICATION_SETTINGS[key].get(f'default_{channel}', True)


def save_notification_setting(key, channel, enabled):
    """保存通知设置"""
    if key not in NOTIFICATION_SETTINGS:
        return False
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        setting_key = f"notify_{key}_{channel}"
        c.execute("REPLACE INTO system_config (key, value) VALUES (?, ?)", 
                  (setting_key, '1' if enabled else '0'))
        conn.commit()
        conn.close()
        print(f"[通知设置] 已保存: {setting_key} = {enabled}")
        return True
    except Exception as e:
        conn.close()
        print(f"[通知设置] 保存失败: {e}")
        return False


def get_all_notification_settings():
    """获取所有通知设置"""
    result = {}
    for key, info in NOTIFICATION_SETTINGS.items():
        result[key] = {
            'name': info['name'],
            'description': info['description'],
            'inbox': get_notification_setting(key, 'inbox'),
            'email': get_notification_setting(key, 'email')
        }
    return result


def send_notification(uid, title, content, notif_type='system'):
    """统一发送通知（根据设置决定发送方式）"""
    inbox_enabled = get_notification_setting(notif_type, 'inbox')
    email_enabled = get_notification_setting(notif_type, 'email')
    
    if inbox_enabled:
        create_inbox_notification(uid, title, content, notif_type)
    
    if email_enabled:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        try:
            c.execute("SELECT email, verified FROM users WHERE id = ?", (uid,))
            user = c.fetchone()
            if user and user[0] and user[1] == 1:
                send_notification_email(user[0], title, content)
        except Exception as e:
            print(f"[通知] 邮件发送失败: {e}")
        finally:
            conn.close()


def create_inbox_notification(uid, title, content, notif_type='system'):
    """仅创建站内通知"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("""INSERT INTO notifications (uid, title, content, type) 
                     VALUES (?, ?, ?, ?)""", (uid, title, content, notif_type))
        conn.commit()
        print(f"[通知] 已发送站内通知给用户 {uid}: {title}")
        conn.close()
        return True
    except Exception as e:
        print(f"[通知] 创建站内通知失败: {e}")
        conn.close()
        return False


def mute_user(target_uid, reason, muted_by, mute_type=0, mute_hours=0):
    """禁言用户"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 先将用户现有的活跃禁言设置为不活跃
        c.execute("UPDATE mutes SET active = 0 WHERE uid = ? AND active = 1", (target_uid,))
        
        mute_until = None
        if mute_type == 1 and mute_hours > 0:
            mute_until_dt = datetime.now() + timedelta(hours=mute_hours)
            mute_until = mute_until_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("""INSERT INTO mutes (uid, reason, muted_by, mute_type, mute_until) 
                     VALUES (?, ?, ?, ?, ?)""", 
                  (target_uid, reason, muted_by, mute_type, mute_until))
        
        c.execute("UPDATE users SET is_muted = 1 WHERE id = ?", (target_uid,))
        
        conn.commit()
        
        # 发送通知
        mute_duration_text = "永久禁言" if mute_type == 0 else f"限时禁言 {mute_hours} 小时"
        notif_title = f"您已被 {mute_duration_text}"
        notif_content = f"原因: {reason}\n操作人: {muted_by}"
        if mute_until:
            notif_content += f"\n解禁时间: {mute_until}"
        send_notification(target_uid, notif_title, notif_content, 'mute_notify')
        
        print(f"[禁言] 用户 {target_uid} 已被禁言")
        conn.close()
        return True
    except Exception as e:
        print(f"[禁言] 失败: {e}")
        conn.close()
        return False


def unmute_user(target_uid, unmuted_by):
    """解禁用户"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        c.execute("UPDATE penalties SET active = 0, lifted_by = ?, lifted_at = ? WHERE uid = ? AND penalty_type = 'mute' AND active = 1", 
                  (unmuted_by, now, target_uid))
        c.execute("UPDATE users SET is_muted = 0 WHERE id = ?", (target_uid,))
        
        conn.commit()
        
        # 发送通知
        notif_title = "您已被解除禁言"
        notif_content = f"操作人: {unmuted_by}"
        send_notification(target_uid, notif_title, notif_content, 'unmute_notify')
        
        print(f"[禁言] 用户 {target_uid} 已被解禁")
        conn.close()
        return True
    except Exception as e:
        print(f"[禁言] 解禁失败: {e}")
        conn.close()
        return False


def is_user_banned(uid):
    """检查用户是否被封禁"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("SELECT is_banned FROM users WHERE id = ?", (uid,))
        result = c.fetchone()
        conn.close()
        return result is not None and result[0] == 1
    except Exception as e:
        print(f"[封禁] 检查失败: {e}")
        conn.close()
        return False


def ban_user(target_uid, reason, banned_by, ban_type=0, ban_days=0):
    """封禁用户"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (target_uid,))
        
        ban_until = None
        if ban_type == 1 and ban_days > 0:
            ban_until_dt = datetime.now() + timedelta(days=ban_days)
            ban_until = ban_until_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        duration = None
        if ban_type == 1 and ban_days > 0:
            duration = f"{ban_days}天"
        
        issue_penalty(target_uid, 'ban' if ban_type == 0 else 'temporary_ban', reason, banned_by, duration)
        
        conn.commit()
        
        ban_duration_text = "永久封禁" if ban_type == 0 else f"限时封禁 {ban_days} 天"
        notif_title = f"您已被 {ban_duration_text}"
        notif_content = f"原因: {reason}\n操作人: {banned_by}"
        if ban_until:
            notif_content += f"\n解封时间: {ban_until}"
        send_notification(target_uid, notif_title, notif_content, 'penalty_notify')
        
        print(f"[封禁] 用户 {target_uid} 已被封禁")
        conn.close()
        return True
    except Exception as e:
        print(f"[封禁] 失败: {e}")
        conn.close()
        return False


def unban_user(target_uid, unbanned_by):
    """解封用户"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        c.execute("UPDATE penalties SET active = 0, lifted_by = ?, lifted_at = ? WHERE uid = ? AND penalty_type IN ('ban', 'temporary_ban') AND active = 1", 
                  (unbanned_by, now, target_uid))
        c.execute("UPDATE users SET is_banned = 0 WHERE id = ?", (target_uid,))
        
        conn.commit()
        
        notif_title = "您已被解除封禁"
        notif_content = f"操作人: {unbanned_by}"
        send_notification(target_uid, notif_title, notif_content, 'penalty_notify')
        
        print(f"[封禁] 用户 {target_uid} 已被解封")
        conn.close()
        return True
    except Exception as e:
        print(f"[封禁] 解封失败: {e}")
        conn.close()
        return False


def get_mute_history(uid=None, active_only=False):
    """获取禁言记录"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        sql = """SELECT m.id, m.uid, m.reason, m.muted_by, 
                        CASE m.mute_type WHEN 0 THEN '永久' ELSE '限时' END as mute_type,
                        m.mute_until, m.created_at, m.active, u.email,
                        m.unmuted_by, m.unmuted_at
                 FROM mutes m
                 LEFT JOIN users u ON m.uid = u.id"""
        params = []
        
        if uid:
            sql += " WHERE m.uid = ?"
            params.append(uid)
            if active_only:
                sql += " AND m.active = 1"
        elif active_only:
            sql += " WHERE m.active = 1"
        
        sql += " ORDER BY m.created_at DESC"
        
        c.execute(sql, params)
        results = c.fetchall()
        
        records = []
        for row in results:
            records.append({
                'id': row[0],
                'uid': row[1],
                'reason': row[2],
                'muted_by': row[3],
                'mute_type': row[4],
                'mute_until': row[5],
                'created_at': row[6],
                'active': bool(row[7]),
                'email': row[8],
                'unmuted_by': row[9],
                'unmuted_at': row[10]
            })
        
        conn.close()
        return records
    except Exception as e:
        print(f"[禁言] 获取记录失败: {e}")
        conn.close()
        return []


def get_user_notifications(uid, unread_only=False):
    """获取用户通知"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        sql = "SELECT id, title, content, type, read, created_at FROM notifications WHERE uid = ?"
        params = [uid]
        
        if unread_only:
            sql += " AND read = 0"
        
        sql += " ORDER BY created_at DESC"
        
        c.execute(sql, params)
        results = c.fetchall()
        
        notifications = []
        for row in results:
            notifications.append({
                'id': row[0],
                'title': row[1],
                'content': row[2],
                'type': row[3],
                'read': bool(row[4]),
                'created_at': row[5]
            })
        
        conn.close()
        return notifications
    except Exception as e:
        print(f"[通知] 获取失败: {e}")
        conn.close()
        return []


def mark_notification_read(notif_id, uid):
    """标记通知已读"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("UPDATE notifications SET read = 1 WHERE id = ? AND uid = ?", (notif_id, uid))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[通知] 标记失败: {e}")
        conn.close()
        return False

# ===================== 违规检测和惩罚管理模块 =====================
def record_violation(uid, content, violation_type):
    """记录用户违规并执行相应操作"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 先获取用户当前的违规次数
        c.execute("SELECT violation_count FROM users WHERE id = ?", (uid,))
        result = c.fetchone()
        current_count = result[0] if result else 0
        new_count = current_count + 1
        
        # 更新用户违规计数
        c.execute("UPDATE users SET violation_count = ? WHERE id = ?", (new_count, uid))
        
        # 根据违规次数确定等级和采取的措施
        level = 0
        action_taken = ""
        mute_now = False
        
        if new_count == 1:
            level = 0
            action_taken = "提醒"
            notif_title = "⚠️ 内容违规提醒"
            notif_content = f"您发布的内容包含违规信息，请注意语言规范。这是第一次提醒。\n违规内容：{content[:50]}..."
        elif new_count == 2:
            level = 1
            action_taken = "警告"
            notif_title = "⚠️ 内容违规警告"
            notif_content = f"您再次发布违规内容，已收到警告。继续违规将被限制发言。\n违规内容：{content[:50]}..."
        else:
            level = 2
            action_taken = "禁言"
            notif_title = "⛔ 已被禁言"
            notif_content = f"您已多次发布违规内容，被系统自动禁言。\n违规内容：{content[:50]}..."
            mute_now = True
            # 通知管理员
            try:
                create_notification(config.ADMIN_USERNAME, "🚨 多次违规用户已被自动禁言", 
                                  f"用户 {uid} 已违规 {new_count} 次，已被系统自动禁言。", "admin_alert")
            except:
                pass
        
        # 记录违规
        c.execute("INSERT INTO violations (uid, content, violation_type, level, action_taken) VALUES (?, ?, ?, ?, ?)", 
                  (uid, content, violation_type, level, action_taken))
        conn.commit()
        conn.close()
        
        # 如果需要禁言，执行禁言操作
        if mute_now:
            mute_user(uid, "多次发布违规内容", "系统", 0, 0)
        
        # 发送通知给违规用户
        send_notification(uid, notif_title, notif_content, 'violation_notify')
        
        print(f"[违规检测] 用户 {uid} 第 {new_count} 次违规：{action_taken}")
        
        return {
            "count": new_count,
            "level": level,
            "action": action_taken,
            "message": notif_content,
            "is_muted": mute_now
        }
    except Exception as e:
        print(f"[违规检测] 记录失败: {e}")
        conn.close()
        return None


def get_violation_history(uid=None):
    """获取违规记录"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        sql = "SELECT v.id, v.uid, v.content, v.violation_type, v.level, v.action_taken, v.created_at, u.violation_count FROM violations v LEFT JOIN users u ON v.uid = u.id"
        params = []
        
        if uid:
            sql += " WHERE v.uid = ?"
            params.append(uid)
        
        sql += " ORDER BY v.created_at DESC"
        
        c.execute(sql, params)
        results = c.fetchall()
        
        violations = []
        for row in results:
            violations.append({
                'id': row[0],
                'uid': row[1],
                'content': row[2],
                'violation_type': row[3],
                'level': row[4],
                'action_taken': row[5],
                'created_at': row[6],
                'total_violations': row[7]
            })
        
        conn.close()
        return violations
    except Exception as e:
        print(f"[违规记录] 获取失败: {e}")
        conn.close()
        return []


def reset_violation_count(uid, operator):
    """重置用户违规计数"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 获取当前违规计数
        c.execute("SELECT violation_count FROM users WHERE id = ?", (uid,))
        result = c.fetchone()
        old_count = result[0] if result else 0
        
        if old_count == 0:
            conn.close()
            return False, "该用户没有违规记录"
        
        # 重置计数
        c.execute("UPDATE users SET violation_count = 0 WHERE id = ?", (uid,))
        conn.commit()
        
        # 发送通知
        send_notification(uid, "✅ 违规记录已重置", 
                          f"管理员 {operator} 已重置您的违规记录，请珍惜发言机会。", 'system_notify')
        
        print(f"[违规记录] 用户 {uid} 的违规计数已从 {old_count} 重置为 0")
        conn.close()
        return True, "违规记录已重置"
    except Exception as e:
        print(f"[违规记录] 重置失败: {e}")
        conn.close()
        return False, "重置失败"


def issue_penalty(uid, penalty_type, reason, issued_by, duration=None):
    """发布惩罚"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("INSERT INTO penalties (uid, penalty_type, reason, issued_by, duration) VALUES (?, ?, ?, ?, ?)", 
                  (uid, penalty_type, reason, issued_by, duration))
        conn.commit()
        
        # 发送通知
        penalty_names = {
            'mute': '禁言',
            'warning': '警告',
            'ban': '封禁',
            'temporary_ban': '临时封禁'
        }
        notif_title = f"⚖️ 您收到了{penalty_names.get(penalty_type, penalty_type)}"
        notif_content = f"原因：{reason}\n操作人：{issued_by}"
        send_notification(uid, notif_title, notif_content, 'penalty_notify')
        
        print(f"[惩罚] 已对用户 {uid} 发布 {penalty_type}")
        conn.close()
        return True
    except Exception as e:
        print(f"[惩罚] 发布失败: {e}")
        conn.close()
        return False


def lift_penalty(penalty_id, operator):
    """解除惩罚"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 获取惩罚信息
        c.execute("SELECT id, uid, penalty_type FROM penalties WHERE id = ? AND active = 1", (penalty_id,))
        penalty = c.fetchone()
        if not penalty:
            conn.close()
            return False, "惩罚不存在或已解除"
        
        penalty_id_db, uid, penalty_type = penalty
        
        # 更新惩罚状态
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE penalties SET active = 0, lifted_by = ?, lifted_at = ? WHERE id = ?", 
                  (operator, now, penalty_id_db))
        
        # 如果惩罚类型是禁言，同时解禁
        if penalty_type == 'mute':
            unmute_user(uid, operator)
        
        # 发送通知
        penalty_names = {
            'mute': '禁言',
            'warning': '警告',
            'ban': '封禁',
            'temporary_ban': '临时封禁'
        }
        send_notification(uid, f"✅ {penalty_names.get(penalty_type, penalty_type)}已解除", 
                          f"管理员 {operator} 已解除您的惩罚。", 'system_notify')
        
        conn.commit()
        print(f"[惩罚] 已解除用户 {uid} 的惩罚")
        conn.close()
        return True, "惩罚已解除"
    except Exception as e:
        print(f"[惩罚] 解除失败: {e}")
        conn.close()
        return False, "解除失败"


def get_penalty_history(uid=None, active_only=False):
    """获取惩罚记录"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        sql = "SELECT p.id, p.uid, p.penalty_type, p.reason, p.issued_by, p.duration, p.active, p.created_at, p.lifted_by, p.lifted_at FROM penalties p"
        params = []
        
        conditions = []
        if uid:
            conditions.append("p.uid = ?")
            params.append(uid)
        
        if active_only:
            conditions.append("p.active = 1")
        
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY p.created_at DESC"
        
        c.execute(sql, params)
        results = c.fetchall()
        
        penalties = []
        for row in results:
            penalties.append({
                'id': row[0],
                'uid': row[1],
                'penalty_type': row[2],
                'reason': row[3],
                'issued_by': row[4],
                'duration': row[5],
                'active': bool(row[6]),
                'created_at': row[7],
                'lifted_by': row[8],
                'lifted_at': row[9]
            })
        
        conn.close()
        return penalties
    except Exception as e:
        print(f"[惩罚记录] 获取失败: {e}")
        conn.close()
        return []

# ===================== 配置管理模块 =====================
def read_email_pool_config():
    """从 config.py 读取邮箱池配置"""
    try:
        import config
        return config.EMAIL_POOL
    except Exception as e:
        print(f"[配置] 读取失败: {e}")
        return []

def write_config_value(key, value):
    """更新 config.py 中的单个配置项"""
    try:
        # 读取现有的 config.py
        with open('config.py', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 查找并替换配置项
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(key + ' ='):
                # 替换该行
                lines[i] = f'{key} = {repr(value)}\n'
                found = True
                break
        
        # 如果没找到，添加到文件开头（在SECRET_KEY之后）
        if not found:
            insert_pos = 1  # 默认在第2行插入
            for i, line in enumerate(lines):
                if 'SECRET_KEY' in line:
                    insert_pos = i + 1
                    break
            lines.insert(insert_pos, f'{key} = {repr(value)}\n')
        
        # 写回文件
        with open('config.py', 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        print(f"[配置] 已成功更新配置项 {key}")
        return True
    except Exception as e:
        print(f"[配置] 写入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def write_email_pool_config(new_pool):
    """把邮箱池配置写入 config.py"""
    return write_config_value('EMAIL_POOL', new_pool)


# ===================== 邮箱池管理模块 =====================
class EmailPoolManager:
    def __init__(self, app, email_pool):
        self.email_pool = email_pool
        self.current_index = 0
        
    def _get_email_usage(self, email):
        """获取邮箱今日使用次数"""
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('SELECT count FROM email_usage WHERE email=? AND date=?', (email, today))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0
    
    def _increment_email_usage(self, email):
        """增加邮箱今日使用次数"""
        today = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        try:
            # 使用INSERT OR REPLACE避免并发时的UNIQUE constraint错误
            c.execute('INSERT OR REPLACE INTO email_usage (email, date, count, last_used) VALUES (?, ?, COALESCE((SELECT count+1 FROM email_usage WHERE email=? AND date=?), 1), ?)', 
                     (email, today, email, today, now))
            conn.commit()
        except Exception as e:
            print(f"[邮箱池] 更新邮箱使用次数失败: {e}")
        finally:
            conn.close()
    
    def _find_available_email(self):
        """查找可用的邮箱"""
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        for i in range(len(self.email_pool)):
            # 计算起始索引
            idx = (self.current_index + i) % len(self.email_pool)
            email_config = self.email_pool[idx]
            email = email_config['username']
            max_daily = email_config['max_daily']
            
            # 检查使用次数
            c.execute('SELECT count FROM email_usage WHERE email=? AND date=?', (email, today))
            row = c.fetchone()
            count = row[0] if row else 0
            
            if count < max_daily:
                conn.close()
                return idx
        
        conn.close()
        return None
    
    def _send_with_smtp(self, email_config, recipients, subject, body):
        """使用 smtplib 直接发送邮件"""
        try:
            # 创建 SMTP 连接
            smtp_obj = smtplib.SMTP_SSL(email_config['smtp_server'], email_config['smtp_port'])
            smtp_obj.login(email_config['username'], email_config['password'])
            
            # 完全手动构建邮件，避免所有编码问题
            from email.header import Header
            
            # 编码主题
            subject_encoded = Header(subject, 'utf-8').encode()
            
            # 构建邮件内容（纯字符串拼接）
            mail_parts = [
                f'From: {email_config["username"]}',
                f'To: {",".join(recipients)}',
                f'Subject: {subject_encoded}',
                'Content-Type: text/plain; charset=utf-8',
                'Content-Transfer-Encoding: base64',
                ''
            ]
            
            # Base64 编码邮件正文
            import base64
            body_bytes = body.encode('utf-8')
            body_b64 = base64.b64encode(body_bytes).decode('ascii')
            
            # 每行 76 字符分割
            b64_lines = [body_b64[i:i+76] for i in range(0, len(body_b64), 76)]
            mail_parts.extend(b64_lines)
            
            mail_content = '\r\n'.join(mail_parts)
            
            # 发送邮件
            smtp_obj.sendmail(email_config['username'], recipients, mail_content)
            smtp_obj.quit()
            return True
        except Exception as e:
            print(f"[邮箱池] SMTP 发送失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def send_message(self, msg):
        """发送邮件，自动选择可用邮箱（兼容旧版 Message 接口）"""
        # 查找可用邮箱
        email_idx = self._find_available_email()
        if email_idx is None:
            print("[邮箱池] 所有邮箱今日发送量已达上限！")
            return False
        
        # 更新当前索引
        self.current_index = email_idx
        email_config = self.email_pool[email_idx]
        
        # 使用原生 smtplib 发送
        if self._send_with_smtp(email_config, msg.recipients, msg.subject, msg.body):
            self._increment_email_usage(email_config['username'])
            print(f"[邮箱池] 使用 {email_config['name']} 发送邮件成功")
            return True
        else:
            print(f"[邮箱池] 使用 {email_config['name']} 发送失败，尝试切换...")
            # 尝试下一个邮箱
            for i in range(1, len(self.email_pool)):
                next_idx = (email_idx + i) % len(self.email_pool)
                next_config = self.email_pool[next_idx]
                
                # 检查是否可用
                count = self._get_email_usage(next_config['username'])
                if count >= next_config['max_daily']:
                    continue
                
                if self._send_with_smtp(next_config, msg.recipients, msg.subject, msg.body):
                    self._increment_email_usage(next_config['username'])
                    self.current_index = next_idx
                    print(f"[邮箱池] 切换到 {next_config['name']} 发送成功")
                    return True
            
            return False
    
    def send_direct(self, recipients, subject, body):
        """直接发送邮件，使用原生 smtplib（不依赖 Message 对象）"""
        # 查找可用邮箱
        email_idx = self._find_available_email()
        if email_idx is None:
            print("[邮箱池] 所有邮箱今日发送量已达上限！")
            return False
        
        # 更新当前索引
        self.current_index = email_idx
        email_config = self.email_pool[email_idx]
        
        # 使用原生 smtplib 发送
        if self._send_with_smtp(email_config, recipients, subject, body):
            self._increment_email_usage(email_config['username'])
            print(f"[邮箱池] 使用 {email_config['name']} 发送邮件成功")
            return True
        else:
            print(f"[邮箱池] 使用 {email_config['name']} 发送失败，尝试切换...")
            # 尝试下一个邮箱
            for i in range(1, len(self.email_pool)):
                next_idx = (email_idx + i) % len(self.email_pool)
                next_config = self.email_pool[next_idx]
                
                # 检查是否可用
                count = self._get_email_usage(next_config['username'])
                if count >= next_config['max_daily']:
                    continue
                
                if self._send_with_smtp(next_config, recipients, subject, body):
                    self._increment_email_usage(next_config['username'])
                    self.current_index = next_idx
                    print(f"[邮箱池] 切换到 {next_config['name']} 发送成功")
                    return True
            
            return False

# ===================== 输入审核模块 =====================
import re

# 保留字列表（禁止使用的用户名）
RESERVED_USERNAMES = [
    'admin', 'administrator', 'root', 'user', 'guest', 'operator',
    'owner', 'master', 'super', 'system', 'server', 'webmaster',
    'null', 'undefined', 'test', 'demo', 'admin123', 'root123'
]

def validate_user_id(user_id):
    """验证用户ID的合法性

    Returns:
        tuple: (is_valid, error_message)
    """
    if not user_id:
        return False, "账号ID不能为空"
    
    user_id = user_id.strip()
    
    # 长度检查：3-20个字符
    if len(user_id) < 3:
        return False, "账号ID至少需要3个字符"
    if len(user_id) > 20:
        return False, "账号ID不能超过20个字符"
    
    # 格式检查：只允许字母、数字、下划线
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fa5]+$', user_id):
        return False, "账号ID只能包含字母、数字、下划线和中文"
    
    return True, ""

def validate_nickname(nickname):
    """验证昵称的合法性

    Returns:
        tuple: (is_valid, error_message)
    """
    if not nickname:
        return False, "昵称不能为空"
    
    nickname = nickname.strip()
    
    # 长度检查：2-20个字符
    if len(nickname) < 2:
        return False, "昵称至少需要2个字符"
    if len(nickname) > 20:
        return False, "昵称不能超过20个字符"
    
    # 格式检查：只允许字母、数字、下划线、中文
    if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fa5]+$', nickname):
        return False, "昵称只能包含字母、数字、下划线和中文"
    
    # 检查是否包含敏感词
    if check_for_keywords(nickname):
        return False, "昵称包含敏感词，请重新输入"
    
    return True, ""

def validate_password(password):
    """验证密码的合法性
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not password:
        return False, "密码不能为空"
    
    password = password.strip()
    
    # 长度检查：6-32个字符
    if len(password) < 6:
        return False, "密码至少需要6个字符"
    if len(password) > 32:
        return False, "密码不能超过32个字符"
    
    return True, ""

def validate_schedule_date(year, month, day):
    """验证档期日期的合法性
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        year = int(year)
        month = int(month)
        day = int(day)
    except (ValueError, TypeError):
        return False, "日期格式错误"
    
    # 年份范围检查：2020-2100
    if year < 2020 or year > 2100:
        return False, "年份超出允许范围(2020-2100)"
    
    # 月份范围检查：1-12
    if month < 1 or month > 12:
        return False, "月份超出允许范围(1-12)"
    
    # 日期范围检查：1-31（简单检查，更精确的由datetime处理）
    if day < 1 or day > 31:
        return False, "日期超出允许范围(1-31)"
    
    # 检查日期是否有效（防止2月30日等无效日期）
    try:
        schedule_date = datetime(year, month, day)
    except ValueError:
        return False, "日期不合法（如2月30日）"
    
    # 检查日期不能是过去的时间（允许今天）
    today = date.today()
    if schedule_date.date() < today:
        return False, "档期日期不能是过去的日期"
    
    return True, ""

def validate_schedule_time(time_str):
    """验证档期时间的合法性
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not time_str or not time_str.strip():
        return False, "开服时段不能为空"
    
    time_str = time_str.strip()
    
    # 支持"全天"选项
    if time_str == "全天":
        return True, ""
    
    # 支持的格式：HH:MM-HH:MM 或 HH:MM
    # 格式1: 18:00-22:00 或 18:00-00:00（00:00表示次日0点）
    range_pattern = r'^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$'
    # 格式2: 18:00
    single_pattern = r'^(\d{1,2}):(\d{2})$'
    
    match_range = re.match(range_pattern, time_str)
    match_single = re.match(single_pattern, time_str)
    
    if match_range:
        # 验证时间范围格式
        start_hour = int(match_range.group(1))
        start_min = int(match_range.group(2))
        end_hour = int(match_range.group(3))
        end_min = int(match_range.group(4))
        
        # 检查小时范围（结束时间00:00是合法的，表示次日0点）
        if start_hour < 0 or start_hour > 23:
            return False, "开始小时必须在0-23之间"
        if end_hour < 0 or end_hour > 24:
            return False, "结束小时必须在0-24之间"
        if end_hour == 24:
            end_hour = 0  # 24:00 表示次日 00:00
        
        # 检查分钟范围
        if start_min < 0 or start_min > 59 or end_min < 0 or end_min > 59:
            return False, "分钟必须在0-59之间"
        
        # 检查时段长度（不超过12小时）
        start_total = start_hour * 60 + start_min
        end_total = end_hour * 60 + end_min
        duration = end_total - start_total
        if duration < 0:
            duration += 24 * 60  # 跨天情况
        if duration > 720:
            return False, "开服时段不能超过12小时"
        
        return True, ""
    
    elif match_single:
        # 验证单时间格式
        hour = int(match_single.group(1))
        minute = int(match_single.group(2))
        
        if hour < 0 or hour > 23:
            return False, "小时必须在0-23之间"
        
        if minute < 0 or minute > 59:
            return False, "分钟必须在0-59之间"
        
        return True, ""
    
    else:
        return False, "时间格式错误，请使用 HH:MM 或 HH:MM-HH:MM 格式"

def validate_server_id(server_id):
    """验证服务器ID的合法性
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not server_id or not server_id.strip():
        return False, "服务器ID不能为空"
    
    server_id = server_id.strip()
    
    # 长度检查：2-50个字符
    if len(server_id) < 2:
        return False, "服务器ID至少需要2个字符"
    if len(server_id) > 50:
        return False, "服务器ID不能超过50个字符"
    
    # 检查是否包含特殊字符（允许常见字符）
    if re.search(r'[<>"\']', server_id):
        return False, "服务器ID不能包含特殊字符 < > \" '"
    
    # 检查敏感词
    if check_for_keywords(server_id):
        return False, "服务器ID包含敏感词，请重新输入"
    
    return True, ""

def validate_ip_address(ip):
    """验证IP地址的合法性（可选字段）
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not ip or not ip.strip():
        # 空值是允许的（可选字段）
        return True, ""
    
    ip = ip.strip()
    
    # 长度检查
    if len(ip) > 100:
        return False, "IP地址过长"
    
    # 检查是否包含特殊字符
    if re.search(r'[<>"\']', ip):
        return False, "IP地址不能包含特殊字符 < > \" '"
    
    # 格式检查：支持域名和IPv4地址
    # IPv4地址格式：xxx.xxx.xxx.xxx
    ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    # 域名格式：允许字母、数字、点、冒号（端口）、横杠
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*(:\d+)?$'
    
    if not (re.match(ipv4_pattern, ip) or re.match(domain_pattern, ip)):
        return False, "IP地址格式不正确"
    
    return True, ""

def validate_contact_value(contact_value, contact_type):
    """验证联系方式的合法性（必填字段）
    
    Returns:
        tuple: (is_valid, error_message)
    """
    # 联系方式类型必须选择
    if not contact_type or not contact_type.strip():
        return False, "请选择联系方式类型"
    
    # 联系方式内容必须填写
    if not contact_value or not contact_value.strip():
        return False, "请填写联系方式内容"
    
    contact_value = contact_value.strip()
    
    # 长度检查
    if len(contact_value) > 50:
        return False, "联系方式内容不能超过50个字符"
    
    # 检查是否包含特殊字符
    if re.search(r'[<>"\']', contact_value):
        return False, "联系方式不能包含特殊字符 < > \" '"
    
    # 根据类型进行特定验证
    if contact_type == 'qq':
        # QQ号：5-11位数字
        if not re.match(r'^\d{5,11}$', contact_value):
            return False, "QQ号格式错误（5-11位数字）"
    elif contact_type == 'phone':
        # 手机号：11位数字（中国大陆）
        if not re.match(r'^1[3-9]\d{9}$', contact_value):
            return False, "手机号格式错误（11位数字，以1开头）"
    elif contact_type == 'wechat':
        # 微信号：6-20位字母、数字、下划线
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{5,19}$', contact_value):
            return False, "微信号格式错误（6-20位，字母开头）"
    elif contact_type == 'email':
        # 邮箱格式验证
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, contact_value):
            return False, "邮箱格式不正确"
    
    # 检查敏感词
    if check_for_keywords(contact_value):
        return False, "联系方式包含敏感词，请重新输入"
    
    return True, ""

def sanitize_input(content, max_length=None):
    """清理输入内容，移除潜在的危险字符
    
    Args:
        content: 待清理的内容
        max_length: 最大长度限制
    
    Returns:
        清理后的内容
    """
    if not content:
        return ""
    
    content = str(content).strip()
    
    # 移除HTML标签
    content = re.sub(r'<[^>]+>', '', content)
    
    # 移除特殊控制字符
    content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)
    
    # 如果指定了最大长度，则截断
    if max_length and len(content) > max_length:
        content = content[:max_length]
    
    return content

# 工具函数
def hash_password(password):
    """使用 bcrypt 哈希密码（安全的密码哈希算法）"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hashed_password):
    """验证密码是否匹配（支持bcrypt和旧的MD5格式）"""
    try:
        # 首先尝试bcrypt验证
        if hashed_password.startswith('$2b$') or hashed_password.startswith('$2a$'):
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        else:
            # 兼容旧的MD5格式
            return hashlib.md5(password.encode('utf-8')).hexdigest() == hashed_password
    except Exception as e:
        print(f"[密码验证错误] {e}")
        return False

def md5(s):
    """旧版MD5哈希（仅用于兼容旧数据）"""
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def rand_code():
    return str(random.randint(100000, 999999))

def get_client_ip():
    """获取客户端IP地址"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr

# ===================== 安全功能模块 =====================
# 登录失败限制配置
MAX_LOGIN_ATTEMPTS = 5  # 最大尝试次数
LOCK_DURATION_MINUTES = 15  # 锁定时长（分钟）

def is_ip_blocked(ip_address):
    """检查IP是否被拉黑"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''SELECT id FROM ip_blacklist 
                  WHERE ip_address = ? AND (expires_at IS NULL OR expires_at > ?)''', 
              (ip_address, now))
    result = c.fetchone()
    conn.close()
    return result is not None

def record_login_attempt(username, ip_address, success):
    """记录登录尝试"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO login_attempts 
                  (username, ip_address, attempt_time, success) 
                  VALUES (?, ?, ?, ?)''', 
              (username, ip_address, now, 1 if success else 0))
    conn.commit()
    conn.close()

def get_failed_login_count(username, ip_address):
    """获取最近登录失败次数"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # 计算15分钟前的时间
    fifteen_minutes_ago = (datetime.now() - timedelta(minutes=LOCK_DURATION_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''SELECT COUNT(*) FROM login_attempts 
                  WHERE username = ? AND ip_address = ? AND success = 0 AND attempt_time > ?''', 
              (username, ip_address, fifteen_minutes_ago))
    count = c.fetchone()[0]
    conn.close()
    return count

def is_account_locked(username, ip_address):
    """检查账号是否被锁定"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''SELECT lock_until FROM login_attempts 
                  WHERE username = ? AND ip_address = ? AND lock_until IS NOT NULL AND lock_until > ? 
                  ORDER BY attempt_time DESC LIMIT 1''', 
              (username, ip_address, now))
    result = c.fetchone()
    conn.close()
    return result is not None

def lock_account(username, ip_address):
    """锁定账号"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    lock_until = (datetime.now() + timedelta(minutes=LOCK_DURATION_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''INSERT INTO login_attempts 
                  (username, ip_address, attempt_time, success, lock_until) 
                  VALUES (?, ?, ?, ?, ?)''', 
              (username, ip_address, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0, lock_until))
    conn.commit()
    conn.close()

def add_ip_to_blacklist(ip_address, reason, blocked_by, expires_at=None):
    """添加IP到黑名单"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO ip_blacklist 
                      (ip_address, reason, blocked_by, blocked_at, expires_at) 
                      VALUES (?, ?, ?, ?, ?)''', 
                  (ip_address, reason, blocked_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expires_at))
        conn.commit()
        print(f"[安全] IP {ip_address} 已加入黑名单")
    except sqlite3.IntegrityError:
        # IP已在黑名单中，更新原因
        c.execute('''UPDATE ip_blacklist SET reason = ?, blocked_at = ?, expires_at = ? 
                      WHERE ip_address = ?''', 
                  (reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expires_at, ip_address))
        conn.commit()
    conn.close()

def remove_ip_from_blacklist(ip_address):
    """从黑名单移除IP"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('DELETE FROM ip_blacklist WHERE ip_address = ?', (ip_address,))
    conn.commit()
    conn.close()

def log_operation(uid, action, target, detail=""):
    """记录操作日志"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    ip_address = get_client_ip()
    c.execute('''INSERT INTO operation_logs 
                  (uid, ip_address, action, target, detail, created_at) 
                  VALUES (?, ?, ?, ?, ?, ?)''', 
              (uid, ip_address, action, target, detail, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_operation_logs(page=1, page_size=20, uid=None, action=None):
    """获取操作日志"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    offset = (page - 1) * page_size
    
    query = 'SELECT * FROM operation_logs WHERE 1=1'
    params = []
    
    if uid:
        query += ' AND uid = ?'
        params.append(uid)
    if action:
        query += ' AND action LIKE ?'
        params.append(f'%{action}%')
    
    query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([page_size, offset])
    
    c.execute(query, params)
    logs = []
    for row in c.fetchall():
        logs.append({
            'id': row[0],
            'uid': row[1],
            'ip_address': row[2],
            'action': row[3],
            'target': row[4],
            'detail': row[5],
            'created_at': row[6]
        })
    
    # 获取总数
    count_query = 'SELECT COUNT(*) FROM operation_logs WHERE 1=1'
    count_params = []
    if uid:
        count_query += ' AND uid = ?'
        count_params.append(uid)
    if action:
        count_query += ' AND action LIKE ?'
        count_params.append(f'%{action}%')
    c.execute(count_query, count_params)
    total = c.fetchone()[0]
    
    conn.close()
    return {'logs': logs, 'total': total, 'page': page, 'page_size': page_size}

# 从配置读取管理员信息（已废弃，改为通过注册昵称判断）
ADMIN_USERNAME = None
ADMIN_PASSWORD = None
ADMIN_EMAIL = None

# 全局变量声明
email_pool_manager = None
use_pool = False
mail = None

# 初始化应用
app = Flask(__name__)
app.config.from_pyfile('config.py')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 添加CORS配置，允许跨域请求
from flask_cors import CORS
CORS(app, supports_credentials=True)

# 处理文件上传大小超限异常
from werkzeug.exceptions import RequestEntityTooLarge
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    return jsonify({'ok': 0, 'msg': '文件大小超过限制（最大5MB）'}), 413

# 读取配置（已废弃，改为通过注册昵称判断最高管理员）
ADMIN_USERNAME = None
ADMIN_PASSWORD = None
ADMIN_EMAIL = None

# 初始化 APScheduler
scheduler = BackgroundScheduler()
scheduler.start()

# 程序退出时关闭调度器
atexit.register(lambda: scheduler.shutdown())

# ===================== MC服务器状态定时刷新任务 =====================
def refresh_all_server_status():
    """定时刷新所有服务器状态缓存"""
    global server_status_cache
    
    print(f"[MC状态刷新] 开始刷新所有服务器状态缓存...")
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # 获取所有需要查询的档期（有IP、已开启状态查询、未过期）
        now = datetime.now()
        c.execute('''
            SELECT id, ip, year, month, day, 
                   CASE WHEN type = 'long' THEN 1 ELSE 0 END as is_long,
                   end_year, end_month, end_day
            FROM schedules 
            WHERE ip IS NOT NULL AND ip != '' 
            AND (mc_status_check = 1 OR mc_status_check IS NULL)
            AND active_status = 1
            AND approved = 1
        ''')
        
        schedules = c.fetchall()
        conn.close()
        
        refreshed_count = 0
        for schedule in schedules:
            s_id, ip, year, month, day, is_long, end_year, end_month, end_day = schedule
            
            # 检查档期是否已过期
            schedule_date = datetime(year, month, day)
            if schedule_date.date() < now.date():
                continue
            
            # 检查长期档期的关服日期
            if is_long == 1 and end_year and end_month and end_day:
                end_date = datetime(end_year, end_month, end_day)
                if now > end_date:
                    continue
            
            # 执行实际查询
            try:
                parts = ip.split(':')
                server_host = parts[0]
                port = int(parts[1]) if len(parts) > 1 else 25565
                
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                
                start_time = time.time()
                sock.connect((server_host, port))
                latency = int((time.time() - start_time) * 1000)
                
                # 发送握手包
                handshake = create_minecraft_handshake(server_host, port)
                sock.send(handshake)
                
                # 接收响应
                data = sock.recv(1024)
                sock.close()
                
                if data:
                    query_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    result_data = {
                        'ok': 1,
                        'version': '在线',
                        'motd': '服务器在线',
                        'players_online': '0',
                        'players_max': '0',
                        'latency': latency,
                        'query_time': query_time
                    }
                    
                    # 缓存结果
                    cache_key = ip
                    server_status_cache[cache_key] = {
                        'timestamp': time.time(),
                        'data': result_data
                    }
                    refreshed_count += 1
                    print(f"[MC状态刷新] 已刷新: {ip}")
                    
            except Exception as e:
                # 查询失败也缓存失败状态，避免重复查询
                cache_key = ip
                server_status_cache[cache_key] = {
                    'timestamp': time.time(),
                    'data': {
                        'ok': 0,
                        'msg': f'查询失败: {str(e)[:50]}',
                        'latency': -1
                    }
                }
        
        print(f"[MC状态刷新] 完成，共刷新 {refreshed_count}/{len(schedules)} 个服务器状态")
        
    except Exception as e:
        print(f"[MC状态刷新] 刷新失败: {e}")

# 立即执行一次初始化刷新
refresh_all_server_status()

# 每10分钟执行一次刷新任务
scheduler.add_job(
    func=refresh_all_server_status,
    trigger='interval',
    minutes=10,
    id='refresh_all_server_status',
    name='MC服务器状态定时刷新',
    replace_existing=True
)
print("[MC状态刷新] 已启动定时刷新任务（每10分钟）")

# 存储预约ID到任务ID的映射
reservation_job_map = {}

# ===================== 敏感词过滤器 =====================
# 使用内存缓存的敏感词列表
_sensitive_words_cache = []

def load_sensitive_words():
    """从数据库加载敏感词到内存"""
    global _sensitive_words_cache
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT word FROM keywords")
    _sensitive_words_cache = [row[0].lower() for row in c.fetchall()]
    conn.close()
    
    print(f"[敏感词过滤] 已加载 {len(_sensitive_words_cache)} 个敏感词")
    return len(_sensitive_words_cache)

def add_sensitive_word(word):
    """向缓存添加敏感词"""
    global _sensitive_words_cache
    if word.lower() not in _sensitive_words_cache:
        _sensitive_words_cache.append(word.lower())

def remove_sensitive_word(word):
    """从缓存移除敏感词"""
    global _sensitive_words_cache
    word_lower = word.lower()
    if word_lower in _sensitive_words_cache:
        _sensitive_words_cache.remove(word_lower)

# 初始化邮箱池管理器
if len(EMAIL_POOL) > 0 and EMAIL_POOL[0]['username'] != 'your_main_email@example.com':
    # 初始化基本的邮件配置（Flask-Mail 需要）
    init_mail_config(app, EMAIL_POOL[0])
    # 初始化邮箱池管理器
    email_pool_manager = EmailPoolManager(app, EMAIL_POOL)
    use_pool = True
    print("[邮箱池] 邮箱池初始化成功")
else:
    use_pool = False
    mail = Mail(app)
    print("[邮箱池] 使用单个邮箱配置")

# 确保初始化数据库（不再自动创建管理员）
init_db(None, None, None)
print("数据库初始化完成！")

# 数据库迁移：为旧数据库添加缺失的列
def migrate_database():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 检查users表是否有uid列
    c.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in c.fetchall()]
    
    if 'uid' not in columns:
        print("[数据库迁移] 添加uid列...")
        # SQLite不允许直接添加UNIQUE列，先添加普通列
        c.execute("ALTER TABLE users ADD COLUMN uid INTEGER")
        # 为现有用户生成uid
        c.execute("SELECT id FROM users")
        users = c.fetchall()
        max_uid = 100000
        for user in users:
            # 检查是否已有uid
            c.execute("SELECT uid FROM users WHERE id = ?", (user[0],))
            row = c.fetchone()
            if row[0] is None:
                c.execute("UPDATE users SET uid = ? WHERE id = ?", (max_uid, user[0]))
                max_uid += 1
        conn.commit()
        print("[数据库迁移] uid列添加完成")
    
    if 'nickname' not in columns:
        print("[数据库迁移] 添加nickname列...")
        c.execute("ALTER TABLE users ADD COLUMN nickname TEXT")
        # 为现有用户设置昵称（使用id作为默认昵称）
        c.execute("UPDATE users SET nickname = id WHERE nickname IS NULL")
        conn.commit()
        print("[数据库迁移] nickname列添加完成")
    
    # 修复email_usage表的主键问题
    c.execute("PRAGMA table_info(email_usage)")
    email_usage_columns = [row[1] for row in c.fetchall()]
    # 检查主键是否包含date字段
    c.execute("PRAGMA index_list(email_usage)")
    indexes = c.fetchall()
    has_composite_pk = False
    for idx in indexes:
        if idx[1] == 'sqlite_autoindex_email_usage_1':
            # 检查主键包含的列数
            c.execute("PRAGMA index_info(sqlite_autoindex_email_usage_1)")
            pk_columns = c.fetchall()
            if len(pk_columns) > 1:
                has_composite_pk = True
            break
    
    if not has_composite_pk:
        print("[数据库迁移] 修复email_usage表主键...")
        # 需要重新创建表，因为SQLite不支持直接修改主键
        c.execute("CREATE TABLE IF NOT EXISTS email_usage_new (email TEXT, date TEXT, count INTEGER DEFAULT 0, last_used TEXT, PRIMARY KEY (email, date))")
        c.execute("INSERT OR IGNORE INTO email_usage_new SELECT email, date, count, last_used FROM email_usage")
        c.execute("DROP TABLE email_usage")
        c.execute("ALTER TABLE email_usage_new RENAME TO email_usage")
        conn.commit()
        print("[数据库迁移] email_usage表主键修复完成")
    
    conn.close()

migrate_database()
print("[数据库迁移] 检查完成")

# 加载敏感词
load_sensitive_words()

# 发送邮件
def send_mail(to, content):
    msg = Message('MC档期网站 - 邮箱验证码',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[to])
    msg.body = content
    if use_pool and email_pool_manager:
        return email_pool_manager.send_message(msg)
    else:
        mail.send(msg)

# 发送OP提交档期通知邮件
def send_schedule_notification(uid, year, month, day, time, server_id, ip, contact_type, contact_value):
    try:
        # 检查通知设置
        inbox_enabled = get_notification_setting('schedule_apply', 'inbox')
        email_enabled = get_notification_setting('schedule_apply', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 档期申请通知已全部禁用")
            return True
        
        # 构建联系方式显示文本
        contact_text = ""
        if contact_type and contact_value:
            contact_type_names = {
                "qq": "QQ",
                "phone": "电话",
                "wechat": "微信",
                "other": "其他"
            }
            type_name = contact_type_names.get(contact_type, contact_type)
            contact_text = f"{type_name}: {contact_value}"
        
        # 构建通知内容
        notif_content = f"""档主: {uid} 提交了新的档期申请！

📅 日期: {year}年{month}月{day}日
⏰ 时间: {time}
🎮 服务器ID: {server_id}
"""
        if ip:
            notif_content += f"🌐 IP地址: {ip}\n"
        if contact_text:
            notif_content += f"📞 {contact_text}\n"
        
        notif_content += f"""
请登录管理后台进行审核：{app.config.get('SITE_DOMAIN', 'http://127.0.0.1:5000')}/admin
"""
        
        # 从数据库获取所有管理员
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''SELECT u.id, u.email FROM users u 
                     JOIN user_role r ON u.id = r.uid 
                     WHERE r.role IN (?, ?)''', 
                  (ROLE_ADMIN, ROLE_SUPER_ADMIN))
        admins = c.fetchall()
        conn.close()
        
        # 发送站内通知
        if inbox_enabled:
            for admin in admins:
                create_inbox_notification(admin[0], "📅 新档期申请待审核", notif_content, 'schedule_apply')
        
        # 发送邮件通知
        if email_enabled:
            admin_emails = [admin[1] for admin in admins if admin[1] and admin[1] != '']
            if admin_emails:
                email_content = f"""【MC档期排期站 - 新档期申请】

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
                msg = Message('【提醒】新档期申请待审核',
                              sender=app.config['MAIL_USERNAME'],
                              recipients=admin_emails)
                msg.body = email_content
                if use_pool and email_pool_manager:
                    success = email_pool_manager.send_message(msg)
                    if success:
                        print(f"已发送档期通知邮件到管理员: {', '.join(admin_emails)}")
                else:
                    mail.send(msg)
            print(f"已发送档期通知邮件到管理员: {', '.join(admin_emails)}")
            return True
        return False
    except Exception as e:
        print(f"发送通知邮件失败: {e}")
        return False

# 发送档主申请通知邮件
def send_op_apply_notification(uid, server_ip, contact):
    try:
        inbox_enabled = get_notification_setting('op_apply', 'inbox')
        email_enabled = get_notification_setting('op_apply', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 档主申请通知已全部禁用")
            return True
        
        notif_content = f"""玩家 {uid} 申请成为档主！

"""
        if server_ip:
            notif_content += f"🌐 服务器IP: {server_ip}\n"
        if contact:
            notif_content += f"📞 联系方式: {contact}\n"
        
        notif_content += f"""
请登录管理后台进行审核：{app.config.get('SITE_DOMAIN', 'http://127.0.0.1:5000')}/admin
"""
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''SELECT u.id, u.email FROM users u 
                     JOIN user_role r ON u.id = r.uid 
                     WHERE r.role IN (?, ?)''', 
                  (ROLE_ADMIN, ROLE_SUPER_ADMIN))
        admins = c.fetchall()
        conn.close()
        
        if inbox_enabled:
            for admin in admins:
                create_inbox_notification(admin[0], "👤 新档主申请待审核", notif_content, 'op_apply')
        
        if email_enabled:
            admin_emails = [admin[1] for admin in admins if admin[1] and admin[1] != '']
            if admin_emails:
                email_content = f"""【MC档期排期站 - 新档主申请】

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
                msg = Message('【提醒】新档主申请待审核',
                              sender=app.config['MAIL_USERNAME'],
                              recipients=admin_emails)
                msg.body = email_content
                if use_pool and email_pool_manager:
                    success = email_pool_manager.send_message(msg)
                    if success:
                        print(f"已发送档主申请通知邮件到管理员: {', '.join(admin_emails)}")
                else:
                    mail.send(msg)
                    print(f"已发送档主申请通知邮件到管理员: {', '.join(admin_emails)}")
        return True
    except Exception as e:
        print(f"发送档主申请邮件失败: {e}")
        return False

# 发送档期审核结果通知
def send_schedule_result_email(to_email, uid, approved, year, month, day, time, server_id):
    try:
        inbox_enabled = get_notification_setting('schedule_approve', 'inbox')
        email_enabled = get_notification_setting('schedule_approve', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 档期审核结果通知已全部禁用")
            return True
        
        if approved:
            notif_title = "✅ 您的档期已批准！"
            notif_content = f"""恭喜！您的服务器档期已批准！

档期信息：
日期：{year}年{month}月{day}日
时间：{time}
服务器ID：{server_id}

欢迎加入我们的社区！
"""
            email_subject = "【MC档期排期站】您的档期已批准！"
        else:
            notif_title = "❌ 您的档期申请未通过"
            notif_content = f"""很抱歉，您的服务器档期申请未通过。

档期信息：
日期：{year}年{month}月{day}日
时间：{time}
服务器ID：{server_id}

如有疑问，请联系管理员。
"""
            email_subject = "【MC档期排期站】您的档期申请未通过"
        
        if inbox_enabled:
            create_inbox_notification(uid, notif_title, notif_content, 'schedule_approve')
        
        if email_enabled and to_email:
            email_content = f"""亲爱的 {uid}：

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
            msg = Message(email_subject,
                          sender=app.config['MAIL_USERNAME'],
                          recipients=[to_email])
            msg.body = email_content
            if use_pool and email_pool_manager:
                success = email_pool_manager.send_message(msg)
                if success:
                    print(f"[SUCCESS] 已发送档期审核结果邮件到 {to_email}")
            else:
                mail.send(msg)
                print(f"[SUCCESS] 已发送档期审核结果邮件到 {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] 发送档期审核结果通知失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# 发送档主申请审核结果通知
def send_op_apply_result_email(to_email, uid, approved):
    try:
        inbox_enabled = get_notification_setting('op_approve', 'inbox')
        email_enabled = get_notification_setting('op_approve', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 档主申请审核结果通知已全部禁用")
            return True
        
        if approved:
            notif_title = "🎉 恭喜您成为档主！"
            notif_content = f"""恭喜！您的档主申请已批准！

现在您可以：
- 发布服务器档期
- 管理自己的档期内容

欢迎加入我们的社区！
"""
            email_subject = "【MC档期排期站】恭喜您成为档主！"
        else:
            notif_title = "😔 您的档主申请未通过"
            notif_content = f"""很抱歉，您的档主申请未通过。

如有疑问，请联系管理员。
"""
            email_subject = "【MC档期排期站】您的档主申请未通过"
        
        if inbox_enabled:
            create_inbox_notification(uid, notif_title, notif_content, 'op_approve')
        
        if email_enabled and to_email:
            email_content = f"""亲爱的 {uid}：

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
            msg = Message(email_subject,
                          sender=app.config['MAIL_USERNAME'],
                          recipients=[to_email])
            msg.body = email_content
            if use_pool and email_pool_manager:
                success = email_pool_manager.send_message(msg)
                if success:
                    print(f"[SUCCESS] 已发送档主申请审核结果邮件到 {to_email}")
            else:
                mail.send(msg)
                print(f"[SUCCESS] 已发送档主申请审核结果邮件到 {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] 发送档主申请审核结果通知失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# 发送档期删除通知
def send_schedule_deleted_notification(reservation_users, year, month, day, time, server_id):
    try:
        inbox_enabled = get_notification_setting('schedule_delete', 'inbox')
        email_enabled = get_notification_setting('schedule_delete', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 档期删除通知已全部禁用")
            return True
        
        notif_title = "⚠️ 您预约的档期已取消"
        notif_content = f"""您预约的档期已被取消！

档期信息：
📅 日期：{year}年{month}月{day}日
⏰ 时间：{time}
🎮 服务器：{server_id}

请关注其他档期信息，感谢您的支持！
"""
        
        if inbox_enabled:
            for user in reservation_users:
                uid = user[1] if len(user) > 1 else user[0]
                create_inbox_notification(uid, notif_title, notif_content, 'schedule_delete')
        
        if email_enabled:
            email_recipients = [user[0] for user in reservation_users]
            email_content = f"""亲爱的玩家：

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
            msg = Message("【MC档期排期站】您预约的档期已取消",
                          sender=app.config['MAIL_USERNAME'],
                          recipients=email_recipients)
            msg.body = email_content
            
            if use_pool and email_pool_manager:
                success = email_pool_manager.send_message(msg)
                if success:
                    print(f"[SUCCESS] 已发送档期删除通知邮件到 {len(email_recipients)} 位用户")
            else:
                mail.send(msg)
                print(f"[SUCCESS] 已发送档期删除通知邮件到 {len(email_recipients)} 位用户")
        return True
    except Exception as e:
        print(f"[ERROR] 发送档期删除通知失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# 发送档期修改通知
def send_schedule_updated_notification(reservation_users, year, month, day, time, server_id, changes):
    try:
        inbox_enabled = get_notification_setting('schedule_update', 'inbox')
        email_enabled = get_notification_setting('schedule_update', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 档期修改通知已全部禁用")
            return True
        
        changes_text = "\n".join([f"- {change}" for change in changes]) if changes else ""
        
        notif_title = "🔄 您预约的档期已修改"
        notif_content = f"""您预约的档期信息已更新！

档期信息：
📅 日期：{year}年{month}月{day}日
⏰ 时间：{time}
🎮 服务器：{server_id}

修改内容：
{changes_text}

请确认新的档期时间，感谢您的支持！
"""
        
        if inbox_enabled:
            for user in reservation_users:
                uid = user[1] if len(user) > 1 else user[0]
                create_inbox_notification(uid, notif_title, notif_content, 'schedule_update')
        
        if email_enabled:
            email_recipients = [user[0] for user in reservation_users]
            email_content = f"""亲爱的玩家：

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
            msg = Message("【MC档期排期站】您预约的档期已修改",
                          sender=app.config['MAIL_USERNAME'],
                          recipients=email_recipients)
            msg.body = email_content
            
            if use_pool and email_pool_manager:
                success = email_pool_manager.send_message(msg)
                if success:
                    print(f"[SUCCESS] 已发送档期修改通知邮件到 {len(email_recipients)} 位用户")
            else:
                mail.send(msg)
                print(f"[SUCCESS] 已发送档期修改通知邮件到 {len(email_recipients)} 位用户")
        return True
    except Exception as e:
        print(f"[ERROR] 发送档期修改通知失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# 获取当前系统日期
def get_now_date():
    now = datetime.now()
    return {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "timestamp": now
    }

# 档主操作限制常量
OP_DAILY_ADD_LIMIT = 3      # 普通档主每天最多添加3个档期
OP_DAILY_EDIT_LIMIT = 3     # 普通档主每天最多修改3次档期
TRUSTED_OP_DAILY_ADD_LIMIT = 5      # 信用档主每天最多添加5个档期
TRUSTED_OP_DAILY_EDIT_LIMIT = 5     # 信用档主每天最多修改5次档期

def get_today_str():
    """获取今天的日期字符串（格式：YYYY-MM-DD）"""
    return datetime.now().strftime("%Y-%m-%d")

def get_op_action_count(uid, action_type, date=None):
    """获取档主当天的操作次数"""
    if not date:
        date = get_today_str()
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM op_actions 
                 WHERE uid=? AND action_type=? AND date=?''', 
              (uid, action_type, date))
    count = c.fetchone()[0]
    conn.close()
    return count

def record_op_action(uid, action_type, schedule_id=None):
    """记录档主操作"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''INSERT INTO op_actions 
                 (uid, action_type, schedule_id, date) 
                 VALUES (?, ?, ?, ?)''', 
              (uid, action_type, schedule_id, get_today_str()))
    conn.commit()
    conn.close()

def check_op_add_limit(uid, role=ROLE_OP):
    """检查档主添加档期是否超过限制"""
    count = get_op_action_count(uid, "add_schedule")
    limit = TRUSTED_OP_DAILY_ADD_LIMIT if role == ROLE_TRUSTED_OP else OP_DAILY_ADD_LIMIT
    return count < limit, count, limit

def check_op_edit_limit(uid, role=ROLE_OP):
    """检查档主修改档期是否超过限制"""
    count = get_op_action_count(uid, "edit_schedule")
    limit = TRUSTED_OP_DAILY_EDIT_LIMIT if role == ROLE_TRUSTED_OP else OP_DAILY_EDIT_LIMIT
    return count < limit, count, limit

def check_schedule_edit_today(schedule_id):
    """检查某个档期今天已被修改次数（每个档期每天只能修改1次）"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM op_actions 
                 WHERE schedule_id=? AND action_type="edit_schedule" AND date=?''', 
              (schedule_id, get_today_str()))
    count = c.fetchone()[0]
    conn.close()
    return count

def check_schedule_can_edit(schedule_id, uid):
    """检查档期是否可以编辑（每个档期每天只能修改1次）"""
    count = check_schedule_edit_today(schedule_id)
    return count == 0

def check_op_notify_permission(uid, schedule_id):
    """检查档主是否有通知权限（仅第一次修改有）"""
    # 检查该档期是否已经有过通知记录
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM op_actions 
                 WHERE uid=? AND action_type="edit_notify" AND schedule_id=?''', 
              (uid, schedule_id))
    count = c.fetchone()[0]
    conn.close()
    # 如果没有通知记录，则有通知权限
    return count == 0

# 获取当前登录用户角色
def get_user_role(uid):
    if not uid:
        return ROLE_NORMAL
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ROLE_NORMAL

# ===================== 路由：前台首页 =====================
@app.route('/')
def index():
    now = get_now_date()
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    return render_template('index.html',
                           current_user=current_user,
                           current_role=current_role,
                           now_year=now["year"],
                           now_month=now["month"],
                           now_day=now["day"],
                           role_normal=ROLE_NORMAL,
                           role_op=ROLE_OP,
                           role_trusted_op=ROLE_TRUSTED_OP,
                           role_admin=ROLE_ADMIN,
                           role_super_admin=ROLE_SUPER_ADMIN)

# ===================== 路由：独立Admin后台（仅最高管理员可访问） =====================
@app.route('/admin')
def admin_page():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return redirect(url_for('index'))
    return render_template('admin.html',
                           current_user=current_user,
                           role_normal=ROLE_NORMAL,
                           role_op=ROLE_OP,
                           role_trusted_op=ROLE_TRUSTED_OP,
                           role_admin=ROLE_ADMIN,
                           role_super_admin=ROLE_SUPER_ADMIN)

# ===================== 接口：标签管理（后台用） =====================
@app.route('/admin/tags', methods=['POST'])
def admin_tags():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, name, color, description, created_at FROM tags ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    
    result = [{
        'id': row[0],
        'name': row[1],
        'color': row[2],
        'description': row[3],
        'created_at': row[4]
    } for row in rows]
    
    return jsonify({'ok': 1, 'data': result})

@app.route('/admin/tag/add', methods=['POST'])
def admin_tag_add():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    name = data.get('name', '').strip()
    color = data.get('color', '#42C9D8')
    description = data.get('description', '')
    
    if not name:
        return jsonify({'ok': 0, 'msg': '标签名称不能为空'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO tags (name, color, description) VALUES (?, ?, ?)',
                  (name, color, description))
        conn.commit()
        conn.close()
        return jsonify({'ok': 1, 'msg': '标签添加成功'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'ok': 0, 'msg': '标签名称已存在'})

@app.route('/admin/tag/update', methods=['POST'])
def admin_tag_update():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    tag_id = data.get('id')
    name = data.get('name', '').strip()
    color = data.get('color', '#42C9D8')
    description = data.get('description', '')
    
    if not tag_id or not name:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute('UPDATE tags SET name=?, color=?, description=? WHERE id=?',
                  (name, color, description, tag_id))
        conn.commit()
        conn.close()
        return jsonify({'ok': 1, 'msg': '标签更新成功'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'ok': 0, 'msg': '标签名称已存在'})

@app.route('/admin/tag/delete', methods=['POST'])
def admin_tag_delete():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    tag_id = data.get('id')
    
    if not tag_id:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 删除关联记录
    c.execute('DELETE FROM schedule_tags WHERE tag_id=?', (tag_id,))
    # 删除标签
    c.execute('DELETE FROM tags WHERE id=?', (tag_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': '标签删除成功'})

# ==================== 请求日志中间件 ====================
@app.before_request
def log_request():
    """记录所有请求的详细信息"""
    # 跳过静态文件
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return
    
    # 获取请求信息
    method = request.method
    path = request.path
    ip = request.remote_addr
    content_type = request.content_type or 'None'
    
    # 获取JSON数据
    json_data = None
    if request.is_json:
        try:
            json_data = request.get_json(silent=True)
        except:
            json_data = {'_parse_error': True}
    
    # 记录请求（包含敏感信息的用{}代替）
    logger.info(f"[请求] {method} {path} | IP:{ip} | Type:{content_type[:30]}")
    if json_data and not request.path.startswith('/login'):
        # 对于非登录请求，可以记录JSON数据（但要过滤敏感信息）
        safe_data = {k: v for k, v in (json_data.items() if json_data else []) if k not in ['password', 'pwd', 'old_password', 'new_password']}
        if safe_data:
            logger.info(f"[请求数据] {safe_data}")

# ===================== 站内邮件 API =====================
@app.route('/inbox/list', methods=['POST'])
def inbox_list():
    """获取站内邮件列表"""
    # 调试：打印session内容
    logger.info(f"[调试] session keys: {list(session.keys())}")
    logger.info(f"[调试] session user: {session.get('user')}")
    
    if 'user' not in session:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    page = data.get('page', 1)
    page_size = data.get('page_size', 20)
    unread_only = data.get('unread', False)
    
    uid = session['user']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        offset = (page - 1) * page_size
        
        if unread_only:
            c.execute('''SELECT id, title, content, type, read, created_at 
                        FROM notifications WHERE uid = ? AND read = 0 
                        ORDER BY created_at DESC LIMIT ? OFFSET ?''',
                      (uid, page_size, offset))
        else:
            c.execute('''SELECT id, title, content, type, read, created_at 
                        FROM notifications WHERE uid = ? 
                        ORDER BY created_at DESC LIMIT ? OFFSET ?''',
                      (uid, page_size, offset))
        
        messages = []
        for row in c.fetchall():
            messages.append({
                'id': row[0],
                'title': row[1],
                'content': row[2],
                'type': row[3],
                'read': bool(row[4]),
                'created_at': row[5]
            })
        
        # 获取未读数量
        c.execute('SELECT COUNT(*) FROM notifications WHERE uid = ? AND read = 0', (uid,))
        unread_count = c.fetchone()[0]
        
        return jsonify({'ok': 1, 'messages': messages, 'unread_count': unread_count})
    
    except Exception as e:
        logger.error(f"获取邮件列表失败: {e}")
        return jsonify({'ok': 0, 'msg': '获取邮件列表失败'})
    finally:
        conn.close()

@app.route('/inbox/detail', methods=['POST'])
def inbox_detail():
    """获取邮件详情"""
    if 'user' not in session:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    msg_id = data.get('id')
    
    if not msg_id:
        return jsonify({'ok': 0, 'msg': '缺少邮件ID'})
    
    uid = session['user']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute('''SELECT id, title, content, type, read, created_at 
                    FROM notifications WHERE id = ? AND uid = ?''', (msg_id, uid))
        row = c.fetchone()
        
        if not row:
            return jsonify({'ok': 0, 'msg': '邮件不存在'})
        
        # 标记为已读
        c.execute('UPDATE notifications SET read = 1 WHERE id = ?', (msg_id,))
        conn.commit()
        
        message = {
            'id': row[0],
            'title': row[1],
            'content': row[2],
            'type': row[3],
            'read': True,
            'created_at': row[5]
        }
        
        return jsonify({'ok': 1, 'message': message})
    
    except Exception as e:
        logger.error(f"获取邮件详情失败: {e}")
        return jsonify({'ok': 0, 'msg': '获取邮件详情失败'})
    finally:
        conn.close()

@app.route('/inbox/delete', methods=['POST'])
def inbox_delete():
    """删除邮件"""
    if 'user' not in session:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    msg_id = data.get('id')
    
    if not msg_id:
        return jsonify({'ok': 0, 'msg': '缺少邮件ID'})
    
    uid = session['user']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 验证邮件属于当前用户
        c.execute('SELECT uid FROM notifications WHERE id = ?', (msg_id,))
        row = c.fetchone()
        if not row or row[0] != uid:
            return jsonify({'ok': 0, 'msg': '无权删除该邮件'})
        
        c.execute('DELETE FROM notifications WHERE id = ?', (msg_id,))
        conn.commit()
        
        return jsonify({'ok': 1, 'msg': '删除成功'})
    
    except Exception as e:
        logger.error(f"删除邮件失败: {e}")
        return jsonify({'ok': 0, 'msg': '删除失败'})
    finally:
        conn.close()

@app.route('/inbox/mark_read', methods=['POST'])
def inbox_mark_read():
    """标记邮件为已读"""
    if 'user' not in session:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'ok': 0, 'msg': '缺少邮件ID列表'})
    
    uid = session['user']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 批量更新
        placeholders = ','.join('?' * len(ids))
        c.execute(f'UPDATE notifications SET read = 1 WHERE id IN ({placeholders}) AND uid = ?',
                  tuple(ids) + (uid,))
        conn.commit()
        
        return jsonify({'ok': 1, 'msg': '标记成功'})
    
    except Exception as e:
        logger.error(f"标记邮件已读失败: {e}")
        return jsonify({'ok': 0, 'msg': '标记失败'})
    finally:
        conn.close()

@app.route('/admin/notification_settings', methods=['GET'])
def get_admin_notification_settings():
    """获取所有通知设置"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    settings = get_all_notification_settings()
    return jsonify({'ok': 1, 'settings': settings})


@app.route('/admin/notification_settings', methods=['POST'])
def save_admin_notification_settings():
    """保存通知设置"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    settings = data.get('settings', {})
    
    for key, value in settings.items():
        if key in NOTIFICATION_SETTINGS:
            save_notification_setting(key, 'inbox', value.get('inbox', True))
            save_notification_setting(key, 'email', value.get('email', False))
    
    return jsonify({'ok': 1, 'msg': '设置保存成功'})


@app.route('/inbox/send', methods=['POST'])
def inbox_send():
    """发送站内邮件给指定用户"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    email = data.get('email', '').strip()
    msg_type = data.get('type', 'system')
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    
    if not email or not title or not content:
        return jsonify({'ok': 0, 'msg': '请填写完整信息'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute('SELECT id FROM users WHERE email = ?', (email,))
        user = c.fetchone()
        if not user:
            conn.close()
            return jsonify({'ok': 0, 'msg': '用户不存在'})
        
        target_uid = user[0]
        create_notification(target_uid, title, content, msg_type)
        conn.close()
        return jsonify({'ok': 1, 'msg': '发送成功'})
    except Exception as e:
        conn.close()
        print(f"[站内邮件] 发送失败: {e}")
        return jsonify({'ok': 0, 'msg': '发送失败'})

@app.route('/admin/inbox/broadcast', methods=['POST'])
def admin_inbox_broadcast():
    """广播通知给指定角色用户"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    target_role = data.get('target_role', None)
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    
    if not title or not content:
        return jsonify({'ok': 0, 'msg': '请填写标题和内容'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        if target_role is None or target_role == '' or target_role == 'all':
            c.execute('SELECT id FROM users')
        else:
            role_value = int(target_role)
            c.execute('SELECT u.id FROM users u JOIN user_role r ON u.id = r.uid WHERE r.role = ?', (role_value,))
        
        users = c.fetchall()
        sent_count = 0
        for user in users:
            if send_notification(user[0], title, content, 'broadcast_notify'):
                sent_count += 1
        
        conn.close()
        return jsonify({'ok': 1, 'msg': f'已发送给 {sent_count} 个用户'})
    except Exception as e:
        conn.close()
        print(f"[通知] 广播失败: {e}")
        return jsonify({'ok': 0, 'msg': '发送失败'})

# ===================== 档期开关 API =====================
@app.route('/schedule/toggle', methods=['POST'])
def schedule_toggle():
    """管理员切换档期开关状态"""
    uid = session.get("user")
    role = get_user_role(uid)
    
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    schedule_id = data.get('schedule_id')
    
    if not schedule_id:
        return jsonify({'ok': 0, 'msg': '请指定档期ID'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT active_status FROM schedules WHERE id = ?', (schedule_id,))
        row = c.fetchone()
        
        if not row:
            return jsonify({'ok': 0, 'msg': '档期不存在'})
        
        current_status = row[0]
        new_status = 0 if current_status == 1 else 1
        
        c.execute('UPDATE schedules SET active_status = ? WHERE id = ?', (new_status, schedule_id))
        conn.commit()
        
        status_text = '开启' if new_status == 1 else '关闭'
        print(f"管理员 {uid} 将档期 {schedule_id} 切换为 {status_text} 状态")
        
        return jsonify({'ok': 1, 'msg': f'档期已{status_text}', 'active_status': new_status})
    
    except Exception as e:
        logger.error(f"切换档期状态失败: {e}")
        return jsonify({'ok': 0, 'msg': '操作失败'})
    finally:
        conn.close()

# ===================== MC服务器状态查询 API =====================
@app.route('/mc_server/status', methods=['POST'])
def mc_server_status():
    """查询MC服务器状态（使用现代协议，带缓存）"""
    data = request.json or {}
    host = data.get('host', '')
    end_date = data.get('end_date', '')
    
    if not host:
        return jsonify({'ok': 0, 'msg': '请输入服务器地址'})
    
    import socket
    import time
    import struct
    import json
    
    # 检查缓存
    cache_key = host
    current_time = time.time()
    
    if cache_key in server_status_cache:
        cached_data = server_status_cache[cache_key]
        if current_time - cached_data['timestamp'] < SERVER_STATUS_CACHE_DURATION:
            # 缓存未过期，返回缓存数据
            result = cached_data['data'].copy()
            # 添加缓存剩余时间（秒）
            result['cache_remaining'] = int(SERVER_STATUS_CACHE_DURATION - (current_time - cached_data['timestamp']))
            return jsonify(result)
    
    # 缓存过期或不存在，执行实际查询
    query_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 检查是否已过期
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            now_dt = datetime.now()
            if now_dt > end_dt:
                return jsonify({'ok': 0, 'msg': '档期已结束，停止检测', 'expired': True, 'query_time': query_time, 'cache_remaining': 0})
        except ValueError:
            pass
    
    parts = host.split(':')
    if len(parts) == 1:
        server_host = parts[0]
        port = 25565
    else:
        server_host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            return jsonify({'ok': 0, 'msg': '端口号必须是数字'})
    
    def write_varint(value):
        output = bytearray()
        while True:
            temp = value & 0x7F
            value >>= 7
            if value != 0:
                temp |= 0x80
            output.append(temp)
            if value == 0:
                break
        return output
    
    def read_varint(data, offset):
        result = 0
        shift = 0
        while True:
            if offset >= len(data):
                return None, offset
            byte = data[offset]
            offset += 1
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
        return result, offset
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        start_time = time.time()
        result = sock.connect_ex((server_host, port))
        latency = int((time.time() - start_time) * 1000)
        
        if result != 0:
            sock.close()
            return jsonify({'ok': 0, 'msg': '服务器离线或无法连接'})
        
        try:
            protocol_version = 754
            server_address = server_host.encode('utf-8')
            
            packet_data = bytearray()
            packet_data.extend(write_varint(7 + len(server_address)))
            packet_data.extend(write_varint(0))
            packet_data.extend(write_varint(protocol_version))
            packet_data.extend(write_varint(len(server_address)))
            packet_data.extend(server_address)
            packet_data.extend(struct.pack('>H', port))
            packet_data.extend(write_varint(1))
            
            sock.sendall(packet_data)
            
            status_packet = bytearray([1, 0])
            sock.sendall(status_packet)
            
            response = bytearray()
            timeout = time.time() + 3
            while time.time() < timeout:
                try:
                    sock.settimeout(1)
                    chunk = sock.recv(4096)
                    if chunk:
                        response.extend(chunk)
                        if len(response) > 4:
                            length, _ = read_varint(response, 0)
                            if length is not None and len(response) >= length + 5:
                                break
                except socket.timeout:
                    break
            
            if len(response) > 0:
                try:
                    length, offset = read_varint(response, 0)
                    if length is None:
                        raise ValueError("Invalid length")
                    
                    packet_id, offset = read_varint(response, offset)
                    if packet_id != 0:
                        raise ValueError("Invalid packet ID")
                    
                    json_length, offset = read_varint(response, offset)
                    if json_length is None:
                        raise ValueError("Invalid JSON length")
                    
                    if offset + json_length > len(response):
                        raise ValueError("JSON data too short")
                    
                    json_data = response[offset:offset+json_length].decode('utf-8')
                    status = json.loads(json_data)
                    
                    version = status.get('version', {}).get('name', '未知')
                    motd = status.get('description', '')
                    if isinstance(motd, dict):
                        motd = motd.get('text', '')
                    players_online = str(status.get('players', {}).get('online', 0))
                    players_max = str(status.get('players', {}).get('max', 0))
                    
                    sock.close()
                    result_data = {
                        'ok': 1,
                        'version': version,
                        'motd': motd[:100] if motd else '服务器在线',
                        'players_online': players_online,
                        'players_max': players_max,
                        'latency': latency,
                        'query_time': query_time,
                        'cache_remaining': SERVER_STATUS_CACHE_DURATION
                    }
                    # 缓存结果
                    server_status_cache[cache_key] = {
                        'timestamp': current_time,
                        'data': result_data
                    }
                    return jsonify(result_data)
                except Exception as e:
                    logger.debug(f"现代协议解析失败: {e}")
            
            sock.close()
            
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock2.settimeout(3)
            try:
                sock2.connect((server_host, port))
                handshake = bytearray([0xFE, 0x01])
                sock2.sendall(handshake)
                
                response = sock2.recv(2048)
                if response and len(response) > 3:
                    info = response[3:].decode('utf-8', errors='ignore')
                    if info:
                        parts = info.split('\x00')
                        if len(parts) >= 6:
                            version = parts[2] if parts[2] else '未知'
                            motd = parts[3] if parts[3] else '服务器在线'
                            players_online = parts[4] if parts[4] else '0'
                            players_max = parts[5] if parts[5] else '0'
                            sock2.close()
                            result_data = {
                                'ok': 1,
                                'version': version,
                                'motd': motd[:100],
                                'players_online': players_online,
                                'players_max': players_max,
                                'latency': latency,
                                'query_time': query_time,
                                'cache_remaining': SERVER_STATUS_CACHE_DURATION
                            }
                            # 缓存结果
                            server_status_cache[cache_key] = {
                                'timestamp': current_time,
                                'data': result_data
                            }
                            return jsonify(result_data)
            except Exception as e:
                logger.debug(f"旧版协议解析失败: {e}")
            finally:
                sock2.close()
            
            result_data = {
                'ok': 1,
                'version': '未知',
                'motd': '服务器在线',
                'players_online': '0',
                'players_max': '0',
                'latency': latency,
                'query_time': query_time,
                'cache_remaining': SERVER_STATUS_CACHE_DURATION
            }
            # 缓存结果
            server_status_cache[cache_key] = {
                'timestamp': current_time,
                'data': result_data
            }
            return jsonify(result_data)
            
        except socket.timeout:
            sock.close()
            return jsonify({'ok': 0, 'msg': '连接超时', 'query_time': query_time, 'cache_remaining': SERVER_STATUS_CACHE_DURATION})
        except socket.gaierror:
            sock.close()
            return jsonify({'ok': 0, 'msg': '无法解析服务器地址', 'query_time': query_time, 'cache_remaining': SERVER_STATUS_CACHE_DURATION})
        except Exception as e:
            sock.close()
            logger.error(f"MC服务器查询失败: {e}")
            return jsonify({'ok': 0, 'msg': f'查询失败: {str(e)}', 'query_time': query_time, 'cache_remaining': SERVER_STATUS_CACHE_DURATION})
    
    except Exception as e:
        logger.error(f"MC服务器状态查询异常: {e}")
        return jsonify({'ok': 0, 'msg': '查询异常', 'query_time': '', 'cache_remaining': 0})

@app.route('/mc_server/players', methods=['POST'])
def mc_server_players():
    """查询MC服务器在线玩家"""
    data = request.json or {}
    host = data.get('host', '')
    
    if not host:
        return jsonify({'ok': 0, 'msg': '请输入服务器地址'})
    
    parts = host.split(':')
    if len(parts) == 1:
        server_host = parts[0]
        port = 25565
    else:
        server_host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            return jsonify({'ok': 0, 'msg': '端口号必须是数字'})
    
    try:
        import socket
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        try:
            result = sock.connect_ex((server_host, port))
            if result != 0:
                return jsonify({'ok': 0, 'msg': '服务器离线或无法连接'})
            
            try:
                handshake = bytearray([0xFE, 0x01])
                sock.sendall(handshake)
                
                response = sock.recv(1024)
                if response and len(response) > 3:
                    info = response[3:].decode('utf-8', errors='ignore')
                    if info:
                        parts = info.split('\x00')
                        if len(parts) >= 6:
                            players_online = int(parts[4]) if parts[4].isdigit() else 0
                            players_max = int(parts[5]) if parts[5].isdigit() else 0
                            sock.close()
                            return jsonify({
                                'ok': 1,
                                'players': [],
                                'players_count': players_online,
                                'players_max': players_max
                            })
                
                sock.close()
                return jsonify({
                    'ok': 1,
                    'players': [],
                    'players_count': 0,
                    'players_max': 0
                })
            finally:
                sock.close()
                
        except socket.timeout:
            return jsonify({'ok': 0, 'msg': '连接超时'})
        except socket.gaierror:
            return jsonify({'ok': 0, 'msg': '无法解析服务器地址'})
        except Exception as e:
            logger.error(f"MC服务器玩家查询失败: {e}")
            return jsonify({'ok': 0, 'msg': f'查询失败: {str(e)}'})
    
    except Exception as e:
        logger.error(f"MC服务器玩家查询异常: {e}")
        return jsonify({'ok': 0, 'msg': '查询异常'})

def get_site_title():
    """获取网站标题"""
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT value FROM system_config WHERE key = 'site_title'")
        row = c.fetchone()
        conn.close()
        if row:
            return row[0]
        return "MC整合包档期排期站"
    except Exception:
        return "MC整合包档期排期站"

# ===================== 获取网站配置（前台用） =====================
@app.route('/get_site_config', methods=['POST'])
def get_site_config():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT key, value FROM system_config WHERE key IN ('site_title', 'site_announcement', 'footer_text', 'maintenance_mode', 'maintenance_message', 'background_image')")
    rows = c.fetchall()
    conn.close()
    
    configs = {}
    for row in rows:
        configs[row[0]] = row[1]
    
    return jsonify({'ok': 1, 'configs': configs})

# ===================== 获取统计数据 =====================
@app.route('/get_stats', methods=['POST'])
def get_stats():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取显示注册人数的开关配置
    c.execute("SELECT value FROM system_config WHERE key = 'show_user_count'")
    result = c.fetchone()
    show_user_count = result[0] == '1' if result else False
    
    if not show_user_count:
        conn.close()
        return jsonify({
            'ok': 0,
            'show': False,
            'message': '网站信息统计已关闭'
        })
    
    # 获取总注册人数
    c.execute("SELECT COUNT(*) FROM users")
    total_user = c.fetchone()[0]
    
    # 获取普通成员数量（role = 0）
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = 0")
    normal_user = c.fetchone()[0]
    
    # 获取档主数量（role = 1）
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = 1")
    op_user = c.fetchone()[0]
    
    # 获取管理员数量（role = 3 和 role = 4）
    c.execute("SELECT COUNT(*) FROM user_role WHERE role IN (3, 4)")
    admin_user = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'ok': 1,
        'show': True,
        'total_user': total_user,
        'normal_user': normal_user,
        'op_user': op_user,
        'admin_user': admin_user
    })

# ===================== 获取年度档期列表（枝桠视图用） =====================
@app.route('/get_year_schedules', methods=['POST'])
def get_year_schedules():
    year = request.json.get('year', datetime.now().year)
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 查询所有已批准的档期
    c.execute('''SELECT id, year, month, day, time, server_id, ip, contact_type, 
                contact_value, created_by, approved FROM schedules 
                WHERE approved = 1 ORDER BY month, day, time''')
    rows = c.fetchall()
    
    schedules = []
    for row in rows:
        # 判断状态
        try:
            event_year = int(row[1]) if row[1] else int(row[2])
            event_month = int(row[2])
            event_day = int(row[3])
            event_date = datetime(event_year, event_month, event_day)
            now = datetime.now()
            today = datetime(now.year, now.month, now.day)
            
            event_time_str = row[4].split('-')[0].strip()
            if ':' in event_time_str:
                parts = event_time_str.split(':')
                h = int(parts[0])
                m = int(parts[1])
                event_datetime = datetime(event_year, event_month, event_day, h, m)
            else:
                event_datetime = event_date
            
            if event_datetime < now:
                status = 'past'
            elif event_date == today:
                status = 'live'
            else:
                status = 'future'
        except:
            status = 'future'
        
        schedules.append({
            'id': row[0], 
            'year': row[1] if row[1] else row[2], 
            'month': row[2], 
            'day': row[3],
            'time': row[4], 
            'server_id': row[5], 
            'ip': row[6],
            'contact_type': row[7], 
            'contact_value': row[8],
            'created_by': row[9], 
            'approved': row[10], 
            'status': status
        })
    
    # 获取每个档期的预约数量
    c.execute('SELECT schedule_id, COUNT(*) FROM reservations GROUP BY schedule_id')
    reservation_counts = {r[0]: r[1] for r in c.fetchall()}
    for s in schedules:
        s['reservation_count'] = reservation_counts.get(s['id'], 0)
    
    conn.close()
    return jsonify(schedules)

@app.route('/get_reservation_ranking', methods=['POST'])
def get_reservation_ranking():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取显示预约排行榜的开关配置
    c.execute("SELECT value FROM system_config WHERE key = 'show_ranking'")
    result = c.fetchone()
    show_ranking = result[0] == '1' if result else False
    
    if not show_ranking:
        conn.close()
        return jsonify({
            'ok': 0,
            'show': False,
            'message': '预约排行榜已关闭'
        })
    
    # 获取年度排行榜（当前年份）
    current_year = datetime.now().year
    c.execute('''SELECT s.id, s.year, s.month, s.day, s.time, s.server_id, 
                COUNT(r.id) as reservation_count
                FROM schedules s
                LEFT JOIN reservations r ON s.id = r.schedule_id
                WHERE s.year = ? AND s.approved = 1
                GROUP BY s.id
                ORDER BY reservation_count DESC
                LIMIT 10''', (current_year,))
    year_rows = c.fetchall()
    
    year_ranking = []
    for row in year_rows:
        if row[6] > 0:  # 只显示有预约的档期
            year_ranking.append({
                'schedule_id': row[0],
                'year': row[1],
                'month': row[2],
                'day': row[3],
                'time': row[4],
                'server_id': row[5],
                'count': row[6]
            })
    
    # 获取月度排行榜（当前月份）
    current_month = datetime.now().month
    c.execute('''SELECT s.id, s.year, s.month, s.day, s.time, s.server_id, 
                COUNT(r.id) as reservation_count
                FROM schedules s
                LEFT JOIN reservations r ON s.id = r.schedule_id
                WHERE s.year = ? AND s.month = ? AND s.approved = 1
                GROUP BY s.id
                ORDER BY reservation_count DESC
                LIMIT 10''', (current_year, current_month))
    month_rows = c.fetchall()
    
    month_ranking = []
    for row in month_rows:
        if row[6] > 0:  # 只显示有预约的档期
            month_ranking.append({
                'schedule_id': row[0],
                'year': row[1],
                'month': row[2],
                'day': row[3],
                'time': row[4],
                'server_id': row[5],
                'count': row[6]
            })
    
    conn.close()
    
    return jsonify({
        'ok': 1,
        'show': True,
        'year_ranking': year_ranking,
        'month_ranking': month_ranking,
        'current_year': current_year,
        'current_month': current_month
    })

# ===================== 获取所有标签（前台用） =====================
@app.route('/get_tags', methods=['POST'])
def get_tags():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, name, color FROM tags ORDER BY name')
    rows = c.fetchall()
    conn.close()
    
    result = [{
        'id': row[0],
        'name': row[1],
        'color': row[2]
    } for row in rows]
    
    return jsonify({'ok': 1, 'data': result})

# ===================== 接口：邮箱池管理（后台用） =====================
@app.route('/admin/email_pool', methods=['POST'])
def admin_email_pool():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    # 获取邮箱池信息
    result = []
    if use_pool and email_pool_manager:
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        for email_config in EMAIL_POOL:
            # 获取今日使用量
            c.execute("SELECT count FROM email_usage WHERE email=? AND date=?", 
                     (email_config['username'], today))
            row = c.fetchone()
            today_used = row[0] if row else 0
            
            result.append({
                'name': email_config.get('name', ''),
                'username': email_config['username'],
                'smtp_server': email_config['smtp_server'],
                'smtp_port': email_config['smtp_port'],
                'max_daily': email_config.get('max_daily', 0),
                'today_used': today_used
            })
        
        conn.close()
    
    return jsonify({
        'ok': 1,
        'emails': result
    })

@app.route('/admin/test_email', methods=['POST'])
def admin_test_email():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    recipient = data.get('recipient', '')
    email_addr = data.get('email', '')
    index = data.get('index')
    
    if not recipient:
        return jsonify({'ok': 0, 'msg': '请输入收件人邮箱'})
    
    # 选择要测试的邮箱
    target_config = None
    if index is not None and 0 <= index < len(EMAIL_POOL):
        target_config = EMAIL_POOL[index]
    elif email_addr:
        for config in EMAIL_POOL:
            if config['username'] == email_addr:
                target_config = config
                break
    
    if not target_config:
        return jsonify({'ok': 0, 'msg': '邮箱配置不存在'})
    
    # 发送测试邮件
    try:
        if not email_pool_manager:
            return jsonify({'ok': 0, 'msg': '邮箱池未初始化'})
        
        success = email_pool_manager._send_with_smtp(
            target_config,
            [recipient],
            "【测试】邮箱池测试邮件",
            f"""这是一封来自邮箱池的测试邮件！

测试邮箱：{target_config['username']}
测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

如果你收到这封邮件，说明邮箱配置工作正常！
"""
        )
        
        if success:
            # 记录发送次数
            email_pool_manager._increment_email_usage(target_config['username'])
            return jsonify({'ok': 1, 'msg': '发送成功'})
        else:
            return jsonify({'ok': 0, 'msg': '发送失败'})
    except Exception as e:
        print(f"测试邮件发送失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'发送失败: {str(e)}'})

@app.route('/admin/email_pool/add', methods=['POST'])
def admin_email_pool_add():
    """添加邮箱"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    name = data.get('name', '')
    username = data.get('username', '')
    password = data.get('password', '')
    smtp_server = data.get('smtp_server', '')
    smtp_port = int(data.get('smtp_port', 465))
    max_daily = int(data.get('max_daily', 500))
    
    if not username or not password or not smtp_server:
        return jsonify({'ok': 0, 'msg': '请填写完整信息'})
    
    # 读取现有配置
    pool = read_email_pool_config()
    
    # 添加新邮箱
    pool.append({
        'name': name,
        'username': username,
        'password': password,
        'smtp_server': smtp_server,
        'smtp_port': smtp_port,
        'max_daily': max_daily
    })
    
    # 写入配置
    if write_email_pool_config(pool):
        return jsonify({'ok': 1, 'msg': '添加成功，请重启服务器生效'})
    else:
        return jsonify({'ok': 0, 'msg': '添加失败'})

@app.route('/admin/email_pool/update', methods=['POST'])
def admin_email_pool_update():
    """更新邮箱"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    index = int(data.get('index', -1))
    name = data.get('name', '')
    username = data.get('username', '')
    password = data.get('password', '')
    smtp_server = data.get('smtp_server', '')
    smtp_port = int(data.get('smtp_port', 465))
    max_daily = int(data.get('max_daily', 500))
    
    if index < 0 or not username or not password or not smtp_server:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    # 读取现有配置
    pool = read_email_pool_config()
    
    if index >= len(pool):
        return jsonify({'ok': 0, 'msg': '邮箱不存在'})
    
    # 更新邮箱
    pool[index] = {
        'name': name,
        'username': username,
        'password': password,
        'smtp_server': smtp_server,
        'smtp_port': smtp_port,
        'max_daily': max_daily
    }
    
    # 写入配置
    if write_email_pool_config(pool):
        return jsonify({'ok': 1, 'msg': '更新成功，请重启服务器生效'})
    else:
        return jsonify({'ok': 0, 'msg': '更新失败'})

@app.route('/admin/email_pool/delete', methods=['POST'])
def admin_email_pool_delete():
    """删除邮箱"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    index = int(data.get('index', -1))
    
    if index < 0:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    # 读取现有配置
    pool = read_email_pool_config()
    
    if index >= len(pool):
        return jsonify({'ok': 0, 'msg': '邮箱不存在'})
    
    # 删除邮箱
    pool.pop(index)
    
    # 写入配置
    if write_email_pool_config(pool):
        return jsonify({'ok': 1, 'msg': '删除成功，请重启服务器生效'})
    else:
        return jsonify({'ok': 0, 'msg': '删除失败'})

@app.route('/admin/email_pool/move', methods=['POST'])
def admin_email_pool_move():
    """移动邮箱位置"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    index = int(data.get('index', -1))
    direction = data.get('direction', '')  # 'up' 或 'down'
    
    if index < 0 or direction not in ['up', 'down']:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    # 读取现有配置
    pool = read_email_pool_config()
    
    if index >= len(pool):
        return jsonify({'ok': 0, 'msg': '邮箱不存在'})
    
    new_index = index
    if direction == 'up' and index > 0:
        new_index = index - 1
    elif direction == 'down' and index < len(pool) - 1:
        new_index = index + 1
    
    # 交换位置
    pool[index], pool[new_index] = pool[new_index], pool[index]
    
    # 写入配置
    if write_email_pool_config(pool):
        return jsonify({'ok': 1, 'msg': '移动成功，请重启服务器生效'})
    else:
        return jsonify({'ok': 0, 'msg': '移动失败'})

# ===================== 接口：网站维护模式管理 =====================
@app.route('/admin/maintenance', methods=['POST'])
def admin_maintenance():
    """获取/设置网站维护模式"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 如果是GET请求（其实这里是POST），返回当前状态
    # 如果是POST带action=set，则是设置
    data = request.json or {}
    action = data.get('action', 'get')
    
    if action == 'set':
        mode = data.get('mode', '0')
        message = data.get('message', '网站正在维护中，请稍后再试...')
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", ("maintenance_mode", mode))
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", ("maintenance_message", message))
        conn.commit()
        conn.close()
        return jsonify({'ok': 1, 'msg': '维护模式已更新'})
    else:
        # 获取当前状态
        c.execute("SELECT value FROM system_config WHERE key = 'maintenance_mode'")
        row = c.fetchone()
        mode = row[0] if row else '0'
        c.execute("SELECT value FROM system_config WHERE key = 'maintenance_message'")
        row = c.fetchone()
        message = row[0] if row else '网站正在维护中，请稍后再试...'
        conn.close()
        return jsonify({'ok': 1, 'mode': mode, 'message': message})


# ===================== 接口：用户数据统计（后台用） =====================
@app.route('/get_user_stat', methods=['POST'])
def get_user_stat():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_NORMAL,))
    normal_cnt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_OP,))
    op_cnt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_TRUSTED_OP,))
    trusted_op_cnt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_ADMIN,))
    admin_cnt = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_SUPER_ADMIN,))
    super_admin_cnt = c.fetchone()[0]
    conn.close()
    return jsonify({
        "total_user": total,
        "normal_user": normal_cnt,
        "op_user": op_cnt,
        "trusted_op_user": trusted_op_cnt,
        "admin_user": admin_cnt,
        "super_admin_user": super_admin_cnt
    })

# ===================== 接口：获取所有用户列表（后台用） =====================
@app.route('/get_all_users', methods=['POST'])
def get_all_users():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        SELECT u.id, u.uid, u.nickname, u.email, ur.role, u.is_muted, u.is_banned, u.violation_count
        FROM users u
        LEFT JOIN user_role ur ON u.id = ur.uid
        ORDER BY u.id
    ''')
    user_list = []
    for row in c.fetchall():
        user_list.append({
            "id": row[0],
            "uid": row[1],
            "nickname": row[2] if row[2] else row[1],
            "email": row[3],
            "role": row[4] if row[4] is not None else ROLE_NORMAL,
            "is_muted": bool(row[5]) if row[5] is not None else False,
            "is_banned": bool(row[6]) if row[6] is not None else False,
            "violation_count": row[7] if row[7] is not None else 0
        })
    conn.close()
    return jsonify(user_list)


# ===================== 接口：禁言管理 =====================
@app.route('/admin/mutes', methods=['POST'])
def admin_get_mutes():
    """获取禁言记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    active_only = request.json.get('active_only', False) if request.is_json else False
    mutes = get_mute_history(active_only=active_only)
    return jsonify({'ok': 1, 'mutes': mutes})


@app.route('/admin/mute', methods=['POST'])
def admin_mute_user():
    """发布惩罚"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    target_uid = data.get('uid', '')
    reason = data.get('reason', '')
    penalty_type = data.get('penalty_type', 'mute')
    mute_hours = int(data.get('mute_hours', 0))
    
    if not target_uid or not reason:
        return jsonify({'ok': 0, 'msg': '请填写用户ID和原因'})
    
    if penalty_type not in ('mute', 'warning', 'ban', 'temporary_ban'):
        return jsonify({'ok': 0, 'msg': '无效的惩罚类型'})
    
    # 检查用户是否存在
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id = ?", (target_uid,))
    if not c.fetchone():
        conn.close()
        return jsonify({'ok': 0, 'msg': '用户不存在'})
    conn.close()
    
    # 计算期限
    duration = None
    if penalty_type in ('mute', 'temporary_ban') and mute_hours > 0:
        duration = f"{mute_hours}小时"
    
    # 如果是禁言类型，调用禁言函数创建禁言记录
    if penalty_type == 'mute':
        mute_type = 0 if mute_hours == 0 else 1  # 0=永久，1=限时
        mute_user(target_uid, reason, current_user, mute_type, mute_hours)
    # 如果是封禁类型，调用封禁函数
    elif penalty_type in ('ban', 'temporary_ban'):
        ban_type = 0 if penalty_type == 'ban' else 1  # 0=永久，1=限时
        ban_days = int(mute_hours / 24) if mute_hours > 0 else 0
        ban_user(target_uid, reason, current_user, ban_type, ban_days)
    elif issue_penalty(target_uid, penalty_type, reason, current_user, duration):
        pass  # 其他惩罚类型继续原有逻辑
    else:
        return jsonify({'ok': 0, 'msg': '惩罚发布失败'})
    
    log_operation(current_user, 'issue_penalty', target_uid, f'类型: {penalty_type}, 原因: {reason}, 期限: {duration}')
    return jsonify({'ok': 1, 'msg': '惩罚发布成功'})


@app.route('/admin/unmute', methods=['POST'])
def admin_unmute_user():
    """解禁用户"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    target_uid = data.get('uid', '')
    
    if not target_uid:
        return jsonify({'ok': 0, 'msg': '请填写用户ID'})
    
    if unmute_user(target_uid, current_user):
        log_operation(current_user, 'unmute_user', target_uid, '解除禁言')
        return jsonify({'ok': 1, 'msg': '解禁成功'})
    else:
        return jsonify({'ok': 0, 'msg': '解禁失败'})

@app.route('/admin/mutes/delete', methods=['POST'])
def admin_delete_mute():
    """删除禁言记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    mute_id = data.get('mute_id')
    
    if not mute_id:
        return jsonify({'ok': 0, 'msg': '请提供禁言记录ID'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取该禁言记录信息
    c.execute('SELECT uid FROM mutes WHERE id = ?', (mute_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '禁言记录不存在'})
    
    uid = row[0]
    
    # 删除禁言记录
    c.execute('DELETE FROM mutes WHERE id = ?', (mute_id,))
    
    # 检查是否还有其他活跃禁言
    c.execute('SELECT COUNT(*) FROM mutes WHERE uid = ? AND (mute_until IS NULL OR mute_until > datetime("now"))', (uid,))
    remaining_active = c.fetchone()[0]
    
    # 如果没有活跃禁言了，更新用户禁言状态
    if remaining_active == 0:
        c.execute('UPDATE users SET is_muted = 0 WHERE id = ?', (uid,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'已删除禁言记录，用户 {uid} 剩余 {remaining_active} 条活跃禁言'})

@app.route('/admin/mutes/batch_delete', methods=['POST'])
def admin_batch_delete_mutes():
    """批量删除禁言记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'ok': 0, 'msg': '请选择要删除的记录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    for mid in ids:
        c.execute('SELECT uid FROM mutes WHERE id = ?', (mid,))
        row = c.fetchone()
        if row:
            uid = row[0]
            c.execute('DELETE FROM mutes WHERE id = ?', (mid,))
            # 检查是否还有其他活跃禁言
            c.execute('SELECT COUNT(*) FROM mutes WHERE uid = ? AND (mute_until IS NULL OR mute_until > datetime("now"))', (uid,))
            remaining_active = c.fetchone()[0]
            if remaining_active == 0:
                c.execute('UPDATE users SET is_muted = 0 WHERE id = ?', (uid,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'已删除 {len(ids)} 条禁言记录'})


# ===================== 接口：用户通知 =====================
@app.route('/user/notifications', methods=['POST'])
def user_get_notifications():
    """获取用户通知"""
    current_user = session.get('user', '')
    if not current_user:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    unread_only = request.json.get('unread_only', False) if request.is_json else False
    notifications = get_user_notifications(current_user, unread_only=unread_only)
    return jsonify({'ok': 1, 'notifications': notifications})


@app.route('/user/notifications/mark_read', methods=['POST'])
def user_mark_notification_read():
    """标记通知已读"""
    current_user = session.get('user', '')
    if not current_user:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    notif_id = data.get('id', None)
    if notif_id is None:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    if mark_notification_read(notif_id, current_user):
        return jsonify({'ok': 1, 'msg': '标记成功'})
    else:
        return jsonify({'ok': 0, 'msg': '标记失败'})


@app.route('/user/notifications/mark_all_read', methods=['POST'])
def user_mark_all_notifications_read():
    """标记所有通知已读"""
    current_user = session.get('user', '')
    if not current_user:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("UPDATE notifications SET read = 1 WHERE uid = ?", (current_user,))
        conn.commit()
        return jsonify({'ok': 1, 'msg': '标记成功'})
    except Exception as e:
        print(f"[通知] 标记失败: {e}")
        return jsonify({'ok': 0, 'msg': '标记失败'})
    finally:
        conn.close()


@app.route('/user/check_mute', methods=['POST'])
def user_check_mute():
    """检查用户是否被禁言"""
    current_user = session.get('user', '')
    if not current_user:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    is_muted, mute_info = is_user_muted(current_user)
    return jsonify({
        'ok': 1,
        'is_muted': is_muted,
        'mute_info': mute_info
    })


# ===================== 接口：违规和惩罚管理 =====================
@app.route('/admin/violations', methods=['POST'])
def admin_get_violations():
    """获取违规记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json if request.is_json else {}
    uid = data.get('uid', None)
    violations = get_violation_history(uid=uid)
    return jsonify({'ok': 1, 'violations': violations})


@app.route('/admin/violations/reset', methods=['POST'])
def admin_reset_violations():
    """重置用户违规记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    uid = data.get('uid', '')
    
    if not uid:
        return jsonify({'ok': 0, 'msg': '请填写用户ID'})
    
    success, message = reset_violation_count(uid, current_user)
    if success:
        return jsonify({'ok': 1, 'msg': message})
    else:
        return jsonify({'ok': 0, 'msg': message})

@app.route('/admin/violations/delete', methods=['POST'])
def admin_delete_violation():
    """删除单条违规记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    violation_id = data.get('violation_id')
    
    if not violation_id:
        return jsonify({'ok': 0, 'msg': '请提供违规记录ID'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取该违规记录的信息
    c.execute('SELECT uid, level FROM violations WHERE id = ?', (violation_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '违规记录不存在'})
    
    uid, level = row
    
    # 删除违规记录
    c.execute('DELETE FROM violations WHERE id = ?', (violation_id,))
    
    # 更新用户的违规计数
    c.execute('SELECT COUNT(*) FROM violations WHERE uid = ?', (uid,))
    remaining_count = c.fetchone()[0]
    c.execute('UPDATE users SET violation_count = ? WHERE id = ?', (remaining_count, uid))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'已删除违规记录，用户 {uid} 剩余 {remaining_count} 条违规'})

@app.route('/admin/violations/batch_delete', methods=['POST'])
def admin_batch_delete_violations():
    """批量删除违规记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'ok': 0, 'msg': '请选择要删除的记录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 统计每个用户的删除数量并更新
    for vid in ids:
        c.execute('SELECT uid FROM violations WHERE id = ?', (vid,))
        row = c.fetchone()
        if row:
            uid = row[0]
            c.execute('DELETE FROM violations WHERE id = ?', (vid,))
            c.execute('SELECT COUNT(*) FROM violations WHERE uid = ?', (uid,))
            remaining = c.fetchone()[0]
            c.execute('UPDATE users SET violation_count = ? WHERE id = ?', (remaining, uid))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'已删除 {len(ids)} 条违规记录'})


# ===================== 接口：友链管理 =====================

@app.route('/admin/friend_links', methods=['POST'])
def admin_get_friend_links():
    """获取友链列表"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, name, url, icon, description, sort_order, enabled, created_at FROM friend_links ORDER BY sort_order ASC, id ASC')
    rows = c.fetchall()
    conn.close()
    
    links = []
    for row in rows:
        links.append({
            'id': row[0],
            'name': row[1],
            'url': row[2],
            'icon': row[3],
            'description': row[4] or '',
            'sort_order': row[5],
            'enabled': row[6],
            'created_at': row[7]
        })
    
    return jsonify({'ok': 1, 'links': links})


@app.route('/admin/friend_link/add', methods=['POST'])
def admin_add_friend_link():
    """添加友链"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    icon = data.get('icon', '').strip()
    description = data.get('description', '').strip()
    sort_order = data.get('sort_order', 0)
    
    if not name or not url:
        return jsonify({'ok': 0, 'msg': '名称和链接不能为空'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # 找最小可用ID（复用删除的ID）
    existing_ids = set(row[0] for row in c.execute('SELECT id FROM friend_links'))
    new_id = 1
    while new_id in existing_ids:
        new_id += 1
    c.execute('INSERT INTO friend_links (id, name, url, icon, description, sort_order, enabled) VALUES (?, ?, ?, ?, ?, ?, 1)',
              (new_id, name, url, icon, description, sort_order))
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'友链添加成功 (ID: {new_id})'})


@app.route('/admin/friend_link/update', methods=['POST'])
def admin_update_friend_link():
    """更新友链"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    link_id = data.get('id')
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    icon = data.get('icon', '').strip()
    description = data.get('description', '').strip()
    sort_order = data.get('sort_order', 0)
    enabled = data.get('enabled', 1)
    
    if not link_id or not name or not url:
        return jsonify({'ok': 0, 'msg': 'ID、名称和链接不能为空'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('UPDATE friend_links SET name=?, url=?, icon=?, description=?, sort_order=?, enabled=? WHERE id=?',
              (name, url, icon, description, sort_order, enabled, link_id))
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': '友链更新成功'})


@app.route('/admin/friend_link/delete', methods=['POST'])
def admin_delete_friend_link():
    """删除友链"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    link_id = data.get('id')
    
    if not link_id:
        return jsonify({'ok': 0, 'msg': '请提供友链ID'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('DELETE FROM friend_links WHERE id = ?', (link_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': '友链删除成功'})

@app.route('/admin/friend_link/batch_delete', methods=['POST'])
def admin_batch_delete_friend_links():
    """批量删除友链"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'ok': 0, 'msg': '请选择要删除的友链'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    for link_id in ids:
        c.execute('DELETE FROM friend_links WHERE id = ?', (link_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'已删除 {len(ids)} 个友链'})


@app.route('/get_friend_links', methods=['GET'])
def get_friend_links():
    """获取启用的友链列表（公开接口）"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 检查友链显示开关
    c.execute("SELECT value FROM system_config WHERE key = 'show_friend_links'")
    result = c.fetchone()
    show_friend_links = result[0] == '1' if result else False
    
    if not show_friend_links:
        conn.close()
        return jsonify({
            'ok': 0,
            'show': False,
            'message': '友链已关闭'
        })
    
    c.execute('SELECT name, url, icon, description FROM friend_links WHERE enabled = 1 ORDER BY sort_order ASC, id ASC')
    rows = c.fetchall()
    conn.close()
    
    links = []
    for row in rows:
        links.append({
            'name': row[0],
            'url': row[1],
            'icon': row[2] or '',
            'description': row[3] or ''
        })
    
    return jsonify({'ok': 1, 'show': True, 'links': links})


@app.route('/admin/penalties', methods=['POST'])
def admin_get_penalties():
    """获取惩罚记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json if request.is_json else {}
    uid = data.get('uid', None)
    active_only = data.get('active_only', False)
    penalties = get_penalty_history(uid=uid, active_only=active_only)
    return jsonify({'ok': 1, 'penalties': penalties})


@app.route('/admin/penalties/lift', methods=['POST'])
def admin_lift_penalty():
    """解除惩罚"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    penalty_id = data.get('id', None)
    
    if penalty_id is None:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    success, message = lift_penalty(penalty_id, current_user)
    if success:
        return jsonify({'ok': 1, 'msg': message})
    else:
        return jsonify({'ok': 0, 'msg': message})


@app.route('/admin/penalties/batch_delete', methods=['POST'])
def admin_batch_delete_penalties():
    """批量删除惩罚记录"""
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'ok': 0, 'msg': '请选择要删除的记录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    for pid in ids:
        c.execute('DELETE FROM penalties WHERE id = ?', (pid,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': f'已删除 {len(ids)} 条惩罚记录'})


# ===================== 邮箱验证码 =====================
@app.route('/send_code', methods=['POST'])
def send_code():
    try:
        print("=== send_code 被调用了！")
        data = request.json or {}
        print(f"收到数据: {data}")
        
        email = data.get('email', '').strip()
        if not email:
            return jsonify({'ok': 0, 'msg': '邮箱不能为空'})

        # 检查发送间隔（5分钟内不能重复发送）
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("SELECT expire FROM codes WHERE email = ?", (email,))
        row = c.fetchone()
        if row:
            # 计算距离上次发送的时间差
            expire_time_dt = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            time_diff = (expire_time_dt - datetime.now()).total_seconds()
            # 如果验证码还没过期（5分钟有效期），拒绝发送
            if time_diff > 0:
                conn.close()
                return jsonify({'ok': 0, 'msg': '请稍后再发送验证码（5分钟内只能发送一次）'})
        conn.close()

        code = rand_code()
        expire_time = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
        print(f"生成验证码: {code}")

        msg = Message(
            subject='MC档期网站 - 邮箱验证码',
            sender=app.config['MAIL_USERNAME'],
            recipients=[email])
        msg.body = f'你的注册验证码：{code}\n验证码5分钟内有效，请勿泄露。'
        if use_pool and email_pool_manager:
            success = email_pool_manager.send_message(msg)
            if not success:
                raise Exception("邮箱池发送失败")
        else:
            mail.send(msg)

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("REPLACE INTO codes (email, code, expire) VALUES (?, ?, ?)", (email, code, expire_time))
        conn.commit()
        conn.close()

        print("验证码已保存，返回成功")
        return jsonify({'ok': 1, 'msg': '验证码已发送'})
    except Exception as e:
        import traceback
        print("=== send_code 出现错误 ===")
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'邮件发送失败: {str(e)}'})

# 生成唯一的数字用户ID
def generate_uid(conn=None):
    """生成唯一的6位数字用户ID"""
    use_existing_conn = conn is not None
    if not use_existing_conn:
        conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取最大的uid
    c.execute("SELECT MAX(uid) FROM users")
    row = c.fetchone()
    max_uid = row[0] if row[0] else 100000
    
    # 尝试生成下一个ID，如果冲突则递增
    uid = max_uid + 1
    while True:
        c.execute("SELECT uid FROM users WHERE uid = ?", (uid,))
        if not c.fetchone():
            break
        uid += 1
    
    if not use_existing_conn:
        conn.close()
    return uid

# ===================== 注册 =====================
@app.route('/register', methods=['POST'])
def register():
    try:
        print("=== register 被调用了！")
        data = request.json or {}
        print(f"收到数据: {data}")
        
        nickname = data.get('nickname', '').strip()  # 用户输入的是昵称
        pwd = data.get('pwd', '').strip()
        email = data.get('email', '').strip()
        input_code = data.get('code', '').strip()

        if not nickname or not pwd or not email or not input_code:
            return jsonify({'ok': 0, 'msg': '请填写完整信息'})

        # ========== 昵称审核 ==========
        is_valid, error_msg = validate_nickname(nickname)
        if not is_valid:
            print(f"[审核] 昵称审核失败: {error_msg}")
            return jsonify({'ok': 0, 'msg': error_msg})
        
        # ========== 密码审核 ==========
        is_valid, error_msg = validate_password(pwd)
        if not is_valid:
            print(f"[审核] 密码审核失败: {error_msg}")
            return jsonify({'ok': 0, 'msg': error_msg})
        
        # ========== 邮箱格式审核 ==========
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'ok': 0, 'msg': '邮箱格式不正确'})
        
        # 清理输入数据
        nickname = sanitize_input(nickname, 20)
        pwd = sanitize_input(pwd, 32)
        email = sanitize_input(email, 100)

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        c.execute("SELECT code FROM codes WHERE email = ? AND expire > ?", (email, now_str))
        row = c.fetchone()
        if not row or row[0] != input_code:
            conn.close()
            return jsonify({'ok': 0, 'msg': '验证码错误或已过期'})

        # 生成唯一的数字ID（使用现有的数据库连接）
        uid = generate_uid(conn)
        user_id = str(uid)  # 字符串形式用于主键
        
        # 使用bcrypt加密密码
        hashed_password = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
        c.execute("INSERT INTO users (id, uid, nickname, pwd, email, verified) VALUES (?, ?, ?, ?, ?, 1)", 
                  (user_id, uid, nickname, hashed_password, email))
        
        # 根据注册昵称分配角色
        if nickname == SUPER_ADMIN_ID:
            # 使用配置的最高管理员昵称注册，成为最高管理员
            c.execute("INSERT INTO user_role (uid, role) VALUES (?, ?)", (user_id, ROLE_SUPER_ADMIN))
            print(f"[管理员] 用户 {nickname} 使用最高管理员昵称注册，已设置为最高管理员")
        else:
            c.execute("INSERT INTO user_role (uid, role) VALUES (?, ?)", (user_id, ROLE_NORMAL))
        
        conn.commit()
        
        # 发送欢迎通知
        send_notification(user_id, "🎉 欢迎加入MC档期排期站！", 
                         f"""亲爱的 {nickname}：

欢迎加入MC档期排期站！

🎮 您现在可以：
• 浏览所有服务器档期信息
• 预约您感兴趣的服务器
• 申请成为档主，发布自己的服务器档期

💡 温馨提示：
• 请完善您的个人资料
• 遵守社区规则，文明交流
• 如有问题，请联系管理员

祝您游戏愉快！
""", 'welcome_notify')
        
        conn.close()
        
        print(f"注册成功，用户ID: {uid}, 昵称: {nickname}")
        return jsonify({'ok': 1, 'msg': '注册成功！', 'uid': uid, 'nickname': nickname, 'email': email})
    except sqlite3.IntegrityError:
        return jsonify({'ok': 0, 'msg': '邮箱已被注册'})
    except Exception as e:
        import traceback
        print("=== register 出现错误 ===")
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'注册失败: {str(e)}'})

# ===================== 发送重置密码验证码 =====================
@app.route('/send_reset_code', methods=['POST'])
def send_reset_code():
    try:
        print("=== send_reset_code 被调用了！")
        data = request.json or {}
        print(f"收到数据: {data}")
        email = data.get("email", "").strip()

        print(f"收到重置密码请求: {email}")

        if not email:
            return jsonify({'ok': 0, 'msg': '邮箱不能为空'})

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        # 检查邮箱是否存在
        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        if not c.fetchone():
            conn.close()
            print(f"邮箱未注册: {email}")
            return jsonify({'ok': 0, 'msg': '该邮箱未注册'})

        # 检查发送间隔（5分钟内不能重复发送）
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        c.execute("SELECT expire FROM codes WHERE email = ?", (email,))
        row = c.fetchone()
        if row:
            expire_time_dt = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            time_diff = (expire_time_dt - now).total_seconds()
            # 如果验证码还没过期（5分钟有效期），拒绝发送
            if time_diff > 0:
                conn.close()
                print(f"发送过于频繁: {email}")
                return jsonify({'ok': 0, 'msg': '请稍后再发送验证码（5分钟内只能发送一次）'})

        # 生成验证码
        code = random.randint(100000, 999999)
        code_str = str(code)
        expire = (now + datetime.timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')

        c.execute("REPLACE INTO codes (email, code, expire) VALUES (?, ?, ?)", (email, code_str, expire))
        conn.commit()
        conn.close()

        try:
            print(f"正在发送邮件到: {email}, 验证码: {code_str}")
            msg = Message(
                subject='MC档期排期站 - 密码重置验证码',
                sender=app.config['MAIL_USERNAME'],
                recipients=[email])
            msg.body = f"你的MC档期站密码重置验证码是：{code_str}，5分钟内有效"
            if use_pool and email_pool_manager:
                success = email_pool_manager.send_message(msg)
                if not success:
                    raise Exception("邮箱池发送失败")
            else:
                mail.send(msg)
            print(f"邮件发送成功: {email}")
            return jsonify({'ok': 1, 'msg': '验证码已发送到邮箱'})
        except Exception as e:
            print(f"邮件发送失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'ok': 0, 'msg': f'邮件发送失败: {str(e)}'})
    except Exception as e:
        import traceback
        print("=== 出现错误 ===")
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'服务器错误: {str(e)}'})

# ===================== 重置密码 =====================
@app.route('/reset_password', methods=['POST'])
def reset_password():
    try:
        print("=== reset_password 被调用了！")
        data = request.json or {}
        print(f"收到数据: {data}")
        
        email = data.get("email", "").strip()
        code = data.get("code", "").strip()
        new_password = data.get("new_password", "").strip()

        if not email or not code or not new_password:
            return jsonify({'ok': 0, 'msg': '请填写完整信息'})

        if len(new_password) < 6:
            return jsonify({'ok': 0, 'msg': '密码长度至少需要6位'})

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        # 验证验证码
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        c.execute("SELECT code FROM codes WHERE email = ? AND expire > ?", (email, now_str))
        row = c.fetchone()
        if not row or row[0] != code:
            conn.close()
            return jsonify({'ok': 0, 'msg': '验证码错误或已过期'})

        # 更新密码（使用bcrypt）
        new_hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        c.execute("UPDATE users SET pwd = ? WHERE email = ?", (new_hashed_password, email))
        c.execute("DELETE FROM codes WHERE email = ?", (email,))
        conn.commit()
        conn.close()
        
        print(f"密码重置成功: {email}")
        return jsonify({'ok': 1, 'msg': '密码重置成功，请登录'})
    except Exception as e:
        import traceback
        print("=== reset_password 出现错误 ===")
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'服务器错误: {str(e)}'})

# ===================== 登录 =====================
@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    login_input = data.get('id', '').strip()  # 用户输入的可以是数字ID或邮箱
    pwd = data.get('pwd', '').strip()

    if not login_input or not pwd:
        return jsonify({'ok': 0, 'msg': '请填写账号密码'})

    # 获取客户端IP
    ip_address = get_client_ip()
    
    # 检查IP是否被拉黑
    if is_ip_blocked(ip_address):
        return jsonify({'ok': 0, 'msg': '您的IP已被限制访问'})

    pwd_md5 = md5(pwd)
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 只支持邮箱登录
    if '@' in login_input:
        c.execute("SELECT id, pwd, verified, nickname FROM users WHERE email = ?", (login_input,))
    else:
        conn.close()
        return jsonify({'ok': 0, 'msg': '请使用邮箱登录'})
    
    row = c.fetchone()
    conn.close()

    if not row:
        # 记录失败尝试
        record_login_attempt(login_input, ip_address, False)
        return jsonify({'ok': 0, 'msg': '账号不存在或密码错误'})
    
    user_id, db_pwd, verified, nickname = row
    
    # 检查账号是否被锁定（使用实际的user_id）
    if is_account_locked(user_id, ip_address):
        return jsonify({'ok': 0, 'msg': f'账号已被锁定，请{LOCK_DURATION_MINUTES}分钟后再试'})

    # 支持bcrypt和MD5两种密码格式
    password_valid = False
    if db_pwd.startswith('$2b$') or db_pwd.startswith('$2a$'):
        # bcrypt格式
        password_valid = bcrypt.checkpw(pwd.encode(), db_pwd.encode())
    else:
        # 旧的MD5格式
        password_valid = (db_pwd == pwd_md5)

    if not password_valid:
        # 记录失败尝试
        record_login_attempt(login_input, ip_address, False)
        
        # 检查失败次数
        failed_count = get_failed_login_count(user_id, ip_address)
        if failed_count >= MAX_LOGIN_ATTEMPTS:
            lock_account(user_id, ip_address)
            return jsonify({'ok': 0, 'msg': f'密码错误次数过多，账号已被锁定{LOCK_DURATION_MINUTES}分钟'})
        
        remaining = MAX_LOGIN_ATTEMPTS - failed_count
        return jsonify({'ok': 0, 'msg': f'密码错误，还剩{remaining}次尝试机会'})
    
    if verified != 1:
        return jsonify({'ok': 0, 'msg': '请先完成邮箱验证'})
    
    # 检查用户是否被封禁
    if is_user_banned(user_id):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁'})

    # 登录成功，记录成功尝试
    record_login_attempt(login_input, ip_address, True)
    
    # 设置会话过期时间为1小时
    session.permanent = True
    app.permanent_session_lifetime = timedelta(hours=1)
    session['user'] = user_id
    
    log_operation(user_id, 'login', user_id, '用户登录成功')
    
    return jsonify({'ok': 1, 'msg': '登录成功', 'nickname': nickname})

# ===================== 退出登录（强制清空会话） =====================
@app.route('/logout', methods=['POST'])
def logout():
    uid = session.get('user')
    if uid:
        log_operation(uid, 'logout', uid, '用户退出登录')
    session.clear()
    session.permanent = False
    return jsonify({'ok': 1})

# ===================== 检查Session状态 =====================
@app.route('/check_session', methods=['POST'])
def check_session():
    """检查用户是否已登录"""
    if 'user' in session:
        return jsonify({'ok': 1, 'user': session['user']})
    else:
        return jsonify({'ok': 0, 'msg': '未登录'})

# ===================== 用户修改密码 =====================
@app.route('/user/change_password', methods=['POST'])
def change_password():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()
    
    if not old_password or not new_password:
        return jsonify({'ok': 0, 'msg': '请填写原密码和新密码'})
    
    if len(new_password) < 6:
        return jsonify({'ok': 0, 'msg': '新密码至少需要6个字符'})
    
    # 验证原密码
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT pwd FROM users WHERE id = ?", (uid,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '原密码不正确'})
    
    db_pwd = row[0]
    # 支持bcrypt和MD5两种密码格式验证
    password_valid = False
    if db_pwd.startswith('$2b$') or db_pwd.startswith('$2a$'):
        # bcrypt格式
        password_valid = bcrypt.checkpw(old_password.encode(), db_pwd.encode())
    else:
        # 旧的MD5格式
        password_valid = (db_pwd == md5(old_password))
    
    if not password_valid:
        conn.close()
        return jsonify({'ok': 0, 'msg': '原密码不正确'})
    
    # 使用bcrypt更新密码
    new_hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    c.execute("UPDATE users SET pwd = ? WHERE id = ?", (new_hashed_password, uid))
    conn.commit()
    conn.close()
    
    log_operation(uid, 'change_password', uid, '用户修改密码')
    print(f"[安全] 用户 {uid} 修改了密码")
    
    return jsonify({'ok': 1, 'msg': '密码修改成功，请重新登录'})

# ===================== 安全日志API =====================
@app.route('/admin/security/logs', methods=['POST'])
def get_security_logs():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    page = int(data.get('page', 1))
    page_size = int(data.get('page_size', 20))
    filter_uid = data.get('uid', '')
    filter_action = data.get('action', '')
    
    result = get_operation_logs(page, page_size, filter_uid, filter_action)
    return jsonify({'ok': 1, 'data': result})

# ===================== 获取IP黑名单 =====================
@app.route('/admin/security/blacklist', methods=['POST'])
def get_blacklist():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT * FROM ip_blacklist ORDER BY blocked_at DESC')
    blacklist = []
    for row in c.fetchall():
        blacklist.append({
            'id': row[0],
            'ip_address': row[1],
            'reason': row[2],
            'blocked_by': row[3],
            'blocked_at': row[4],
            'expires_at': row[5]
        })
    conn.close()
    
    return jsonify({'ok': 1, 'data': blacklist})

# ===================== 添加IP到黑名单 =====================
@app.route('/admin/security/blacklist/add', methods=['POST'])
def add_blacklist():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ip_address = data.get('ip_address', '').strip()
    reason = data.get('reason', '恶意行为').strip()
    duration_days = int(data.get('duration_days', 0))  # 0表示永久
    
    if not ip_address:
        return jsonify({'ok': 0, 'msg': '请输入IP地址'})
    
    expires_at = None
    if duration_days > 0:
        expires_at = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")
    
    add_ip_to_blacklist(ip_address, reason, uid, expires_at)
    log_operation(uid, 'add_ip_blacklist', ip_address, f'原因: {reason}, 有效期: {"永久" if duration_days == 0 else f"{duration_days}天"}')
    
    return jsonify({'ok': 1, 'msg': 'IP已加入黑名单'})

# ===================== 从黑名单移除IP =====================
@app.route('/admin/security/blacklist/remove', methods=['POST'])
def remove_blacklist():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ip_address = data.get('ip_address', '').strip()
    
    if not ip_address:
        return jsonify({'ok': 0, 'msg': '请输入IP地址'})
    
    remove_ip_from_blacklist(ip_address)
    log_operation(uid, 'remove_ip_blacklist', ip_address, '从黑名单移除')
    
    return jsonify({'ok': 1, 'msg': 'IP已从黑名单移除'})

# ===================== 获取登录尝试记录 =====================
@app.route('/admin/security/login_attempts', methods=['POST'])
def get_login_attempts():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    page = int(data.get('page', 1))
    page_size = int(data.get('page_size', 20))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    offset = (page - 1) * page_size
    
    c.execute('SELECT * FROM login_attempts ORDER BY attempt_time DESC LIMIT ? OFFSET ?', (page_size, offset))
    attempts = []
    for row in c.fetchall():
        attempts.append({
            'id': row[0],
            'username': row[1],
            'ip_address': row[2],
            'attempt_time': row[3],
            'success': row[4],
            'lock_until': row[5]
        })
    
    c.execute('SELECT COUNT(*) FROM login_attempts')
    total = c.fetchone()[0]
    conn.close()
    
    return jsonify({'ok': 1, 'data': {'attempts': attempts, 'total': total, 'page': page, 'page_size': page_size}})

# ===================== 获取档期 =====================
@app.route('/get_schedule', methods=['POST'])
def get_schedule():
    data = request.json or {}
    print(f"收到的查询参数: {data}")
    
    try:
        year = int(data.get('year'))
        month = int(data.get('month'))
    except (TypeError, ValueError) as e:
        print(f"日期转换错误: {e}")
        return jsonify([])
        
    now = get_now_date()
    now_dt = now["timestamp"]

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT id, day, type, end_year, end_month, end_day, time, server_id, ip, contact_type, contact_value, created_by, created_at, active_status, mc_status_check
                 FROM schedules WHERE year=? AND month=? AND approved=1 AND active_status=1''', (year, month))
    rows = c.fetchall()
    print(f"查询到 {len(rows)} 条档期记录")

    res = []
    for item in rows:
        s_id, day, s_type, end_year, end_month, end_day, s_time, srv_id, ip, contact_type, contact_value, created_by, created_at, active_status, mc_status_check = item
        schedule_dt = datetime(year, month, day)
        if schedule_dt.date() > now_dt.date():
            status = "future"
        elif schedule_dt.date() == now_dt.date():
            status = "live"
        else:
            status = "past"
        
        # 查询预约人数
        c.execute('''SELECT COUNT(*) FROM reservations WHERE schedule_id = ?''', (s_id,))
        reservation_count = c.fetchone()[0]
        
        res.append({
            "id": s_id,
            "year": year,
            "month": month,
            "day": day,
            "type": s_type,
            "end_year": end_year,
            "end_month": end_month,
            "end_day": end_day,
            "time": s_time,
            "server_id": srv_id,
            "ip": ip,
            "contact_type": contact_type,
            "contact_value": contact_value,
            "created_by": created_by,
            "created_at": created_at,
            "status": status,
            "reservation_count": reservation_count,
            "mc_status_check": mc_status_check
        })
    
    conn.close()
    print(f"返回数据: {res}")
    return jsonify(res)

# ===================== 新增档期【核心修复：日期转整型】 =====================
@app.route('/add_schedule', methods=['POST'])
def add_schedule():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁，无法添加档期！'})
    
    role = get_user_role(uid)
    if role not in (ROLE_OP, ROLE_TRUSTED_OP, ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足，无法新增档期'})

    # 档主操作限制检查（管理员和信用档主不受限制）
    if role in (ROLE_OP, ROLE_TRUSTED_OP):
        can_add, count, limit = check_op_add_limit(uid, role)
        if not can_add:
            return jsonify({'ok': 0, 'msg': f'今日添加档期次数已达上限（{count}/{limit}次）'})

    data = request.json or {}
    print(f"收到的新增档期数据: {data}")
    
    try:
        # 强制转为int，解决字符串日期查询不到的问题
        year = int(data.get("year"))
        month = int(data.get("month"))
        day = int(data.get("day"))
        s_type = data.get("type", "short")
        end_year = data.get("end_year")
        end_month = data.get("end_month")
        end_day = data.get("end_day")
        s_time = data.get("time", "")
        srv_id = data.get("server_id", "").strip()
        ip = data.get("ip", "").strip()
        contact_type = data.get("contact_type", "").strip()
        contact_value = data.get("contact_value", "").strip()
        tags = data.get("tags", [])  # 获取标签列表
    except (TypeError, ValueError) as e:
        print(f"数据转换错误: {e}")
        return jsonify({'ok': 0, 'msg': '数据格式错误'})
    
    # 验证关服日期（如果有）
    if end_year and end_month and end_day:
        try:
            end_year = int(end_year)
            end_month = int(end_month)
            end_day = int(end_day)
            
            # 验证关服日期不能早于开服日期
            from datetime import date
            start_date = date(year, month, day)
            end_date = date(end_year, end_month, end_day)
            if end_date < start_date:
                return jsonify({'ok': 0, 'msg': '关服日期不能早于开服日期'})
            
            # 验证关服日期最长一个月
            max_end_date = start_date.replace(day=1) + timedelta(days=32)
            max_end_date = max_end_date.replace(day=1) - timedelta(days=1)
            if end_date > max_end_date:
                return jsonify({'ok': 0, 'msg': '关服日期最长只能设置为开服日期后一个月'})
        except (TypeError, ValueError) as e:
            print(f"关服日期验证错误: {e}")
            return jsonify({'ok': 0, 'msg': '关服日期格式错误'})
    
    # ========== 档期日期审核 ==========
    is_valid, error_msg = validate_schedule_date(year, month, day)
    if not is_valid:
        print(f"[审核] 档期日期审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== 档期时间审核 ==========
    is_valid, error_msg = validate_schedule_time(s_time)
    if not is_valid:
        print(f"[审核] 档期时间审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== 服务器ID审核 ==========
    is_valid, error_msg = validate_server_id(srv_id)
    if not is_valid:
        print(f"[审核] 服务器ID审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== IP地址审核 ==========
    is_valid, error_msg = validate_ip_address(ip)
    if not is_valid:
        print(f"[审核] IP地址审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== 联系方式审核 ==========
    is_valid, error_msg = validate_contact_value(contact_value, contact_type)
    if not is_valid:
        print(f"[审核] 联系方式审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # 清理输入数据
    s_time = sanitize_input(s_time, 20)
    srv_id = sanitize_input(srv_id, 50)
    ip = sanitize_input(ip, 100)
    contact_type = sanitize_input(contact_type, 20)
    contact_value = sanitize_input(contact_value, 50)

    # 如果是管理员或信用档主，直接批准；如果是普通档主，需要审批
    approved = 1 if role in (ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_TRUSTED_OP) else 0
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''INSERT INTO schedules
                 (year, month, day, type, end_year, end_month, end_day,
                  time, server_id, ip, contact_type, contact_value, approved, created_by)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (year, month, day, s_type, end_year, end_month, end_day,
               s_time, srv_id, ip, contact_type, contact_value, approved, uid))
    conn.commit()
    new_id = c.lastrowid
    print(f"已保存档期ID: {new_id}, 日期: {year}-{month}-{day}, 创建者: {uid}, 状态: {approved}")
    
    # 保存标签关联
    if tags and isinstance(tags, list):
        for tag_id in tags:
            try:
                c.execute('INSERT INTO schedule_tags (schedule_id, tag_id) VALUES (?, ?)', (new_id, tag_id))
            except sqlite3.IntegrityError:
                pass  # 忽略重复插入
        conn.commit()
        print(f"已保存档期 {new_id} 的标签: {tags}")
    
    conn.close()
    
    # 记录档主操作
    if role in (ROLE_OP, ROLE_TRUSTED_OP):
        record_op_action(uid, "add_schedule", new_id)
    
    # 如果是普通档主提交，发送邮件通知管理员
    if role == ROLE_OP:
        send_schedule_notification(uid, year, month, day, s_time, srv_id, ip, contact_type, contact_value)
        return jsonify({'ok': 1, 'msg': '新增档期成功，请等待管理员审核，已发送邮件通知'})
    elif role == ROLE_TRUSTED_OP:
        return jsonify({'ok': 1, 'msg': '新增档期成功（已自动通过）'})
    return jsonify({'ok': 1, 'msg': '新增档期成功'})

# ===================== 修改档期 =====================
@app.route('/edit_schedule', methods=['POST'])
def edit_schedule():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁，无法修改档期！'})
    
    role = get_user_role(uid)
    if role not in (ROLE_OP, ROLE_TRUSTED_OP, ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足，无法修改档期'})

    # 档主操作限制检查（管理员和信用档主不受限制）
    if role in (ROLE_OP, ROLE_TRUSTED_OP):
        can_edit, count, limit = check_op_edit_limit(uid, role)
        if not can_edit:
            return jsonify({'ok': 0, 'msg': f'今日修改档期次数已达上限（{count}/{limit}次）'})

    data = request.json or {}
    print(f"收到的修改档期数据: {data}")
    
    try:
        s_id = int(data.get("id"))
        year = int(data.get("year"))
        month = int(data.get("month"))
        day = int(data.get("day"))
        s_type = data.get("type", "short")
        end_year = data.get("end_year")
        end_month = data.get("end_month")
        end_day = data.get("end_day")
        s_time = data.get("time", "")
        srv_id = data.get("server_id", "").strip()
        ip = data.get("ip", "").strip()
        contact_type = data.get("contact_type", "").strip()
        contact_value = data.get("contact_value", "").strip()
        mc_status_check = data.get("mc_status_check", 0)
    except (TypeError, ValueError) as e:
        print(f"数据转换错误: {e}")
        return jsonify({'ok': 0, 'msg': '数据格式错误'})
    
    # 验证关服日期（如果有）
    if end_year and end_month and end_day:
        try:
            end_year = int(end_year)
            end_month = int(end_month)
            end_day = int(end_day)
            
            from datetime import date
            start_date = date(year, month, day)
            end_date = date(end_year, end_month, end_day)
            if end_date < start_date:
                return jsonify({'ok': 0, 'msg': '关服日期不能早于开服日期'})
            
            max_end_date = start_date.replace(day=1) + timedelta(days=32)
            max_end_date = max_end_date.replace(day=1) - timedelta(days=1)
            if end_date > max_end_date:
                return jsonify({'ok': 0, 'msg': '关服日期最长只能设置为开服日期后一个月'})
        except (TypeError, ValueError) as e:
            print(f"关服日期验证错误: {e}")
            return jsonify({'ok': 0, 'msg': '关服日期格式错误'})
    
    # ========== 每个档期每天只能修改1次（管理员和信用档主不受限制）==========
    if role in (ROLE_OP, ROLE_TRUSTED_OP):
        if not check_schedule_can_edit(s_id, uid):
            edit_count = check_schedule_edit_today(s_id)
            return jsonify({'ok': 0, 'msg': f'该档期今日已修改过（{edit_count}次），每个档期每天只能修改1次'})
    
    # ========== 档期日期审核 ==========
    is_valid, error_msg = validate_schedule_date(year, month, day)
    if not is_valid:
        print(f"[审核] 档期日期审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== 档期时间审核 ==========
    is_valid, error_msg = validate_schedule_time(s_time)
    if not is_valid:
        print(f"[审核] 档期时间审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== 服务器ID审核 ==========
    is_valid, error_msg = validate_server_id(srv_id)
    if not is_valid:
        print(f"[审核] 服务器ID审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== IP地址审核 ==========
    is_valid, error_msg = validate_ip_address(ip)
    if not is_valid:
        print(f"[审核] IP地址审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # ========== 联系方式审核 ==========
    is_valid, error_msg = validate_contact_value(contact_value, contact_type)
    if not is_valid:
        print(f"[审核] 联系方式审核失败: {error_msg}")
        return jsonify({'ok': 0, 'msg': error_msg})
    
    # 清理输入数据
    s_time = sanitize_input(s_time, 20)
    srv_id = sanitize_input(srv_id, 50)
    ip = sanitize_input(ip, 100)
    contact_type = sanitize_input(contact_type, 20)
    contact_value = sanitize_input(contact_value, 50)

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 检查权限：如果是普通档主或信用档主，只能修改自己的档期
    if role in (ROLE_OP, ROLE_TRUSTED_OP):
        c.execute('''SELECT created_by FROM schedules WHERE id=?''', (s_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '档期不存在'})
        created_by = row[0]
        if created_by != uid:
            conn.close()
            return jsonify({'ok': 0, 'msg': '权限不足，只能修改自己创建的档期'})
    
    # 获取原档期信息（用于比较变化）
    c.execute('''SELECT year, month, day, time, server_id, ip, contact_type, contact_value 
                 FROM schedules WHERE id=?''', (s_id,))
    old_row = c.fetchone()
    if not old_row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '档期不存在'})
    
    old_year, old_month, old_day, old_time, old_server_id, old_ip, old_contact_type, old_contact_value = old_row
    
    # 获取是否通知预约玩家
    notify_users = data.get("notify_users", False)
    
    # 获取所有预约用户的邮箱
    c.execute('''SELECT u.email, r.user_id FROM reservations r 
                 JOIN users u ON r.user_id = u.id 
                 WHERE r.schedule_id = ?''', (s_id,))
    reservation_users = c.fetchall()
    
    # 比较变化
    changes = []
    if year != old_year or month != old_month or day != old_day:
        changes.append(f"日期从 {old_year}年{old_month}月{old_day}日 改为 {year}年{month}月{day}日")
    if s_time != old_time:
        changes.append(f"时间从 {old_time} 改为 {s_time}")
    if srv_id != old_server_id:
        changes.append(f"服务器ID从 {old_server_id} 改为 {srv_id}")
    if ip != old_ip:
        changes.append(f"IP地址已修改")
    if contact_type != old_contact_type or contact_value != old_contact_value:
        changes.append(f"联系方式已修改")
    
    c.execute('''UPDATE schedules 
                 SET year=?, month=?, day=?, type=?, end_year=?, end_month=?, end_day=?,
                     time=?, server_id=?, ip=?, contact_type=?, contact_value=?, mc_status_check=?
                 WHERE id=?''', 
              (year, month, day, s_type, end_year, end_month, end_day,
               s_time, srv_id, ip, contact_type, contact_value, mc_status_check, s_id))
    conn.commit()
    conn.close()
    
    # 更新该档期所有预约的定时任务
    update_reservation_jobs(s_id)
    
    # 如果选择通知且有预约用户且有变化，发送通知邮件
    # 档主仅第一次修改有通知权限
    can_notify = True
    if role in (ROLE_OP, ROLE_TRUSTED_OP) and notify_users:
        can_notify = check_op_notify_permission(uid, s_id)
        if not can_notify:
            print(f"[通知权限] 档主 {uid} 修改档期 {s_id} 时无通知权限")
    
    if notify_users and reservation_users and changes and can_notify:
        send_schedule_updated_notification(reservation_users, year, month, day, s_time, srv_id, changes)
        # 记录通知操作（仅档主）
        if role in (ROLE_OP, ROLE_TRUSTED_OP):
            record_op_action(uid, "edit_notify", s_id)
    
    # 记录修改操作（仅档主）
    if role in (ROLE_OP, ROLE_TRUSTED_OP):
        record_op_action(uid, "edit_schedule", s_id)
    
    return jsonify({'ok': 1, 'msg': '修改档期成功'})

# ===================== 切换服务器状态查询开关（管理员专用） =====================
@app.route('/toggle_mc_status_check', methods=['POST'])
def toggle_mc_status_check():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足，只有管理员可以修改此设置'})

    data = request.json or {}
    schedule_id = data.get("schedule_id")
    mc_status_check = data.get("mc_status_check", 0)

    if not schedule_id:
        return jsonify({'ok': 0, 'msg': '档期ID不能为空'})

    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''UPDATE schedules SET mc_status_check = ? WHERE id = ?''', 
                   (mc_status_check, schedule_id))
        conn.commit()
        conn.close()
        return jsonify({'ok': 1, 'msg': '设置已更新'})
    except Exception as e:
        print(f"切换服务器状态查询失败: {e}")
        return jsonify({'ok': 0, 'msg': '操作失败'})

# ===================== 获取单个档期详情（用于编辑） =====================
@app.route('/get_schedule_detail', methods=['POST'])
def get_schedule_detail():
    data = request.json or {}
    s_id = data.get("id")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT id, year, month, day, type, end_year, end_month, end_day, 
                        time, server_id, ip, contact_type, contact_value, mc_status_check, created_by
                 FROM schedules WHERE id=?''', (s_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '档期不存在'})
    
    # 获取预约数量
    c.execute('SELECT COUNT(*) FROM reservations WHERE schedule_id = ?', (s_id,))
    reservation_count = c.fetchone()[0]
    
    # 获取通知状态（是否有档主已发送过通知）
    c.execute('''SELECT COUNT(*) FROM op_actions 
                 WHERE schedule_id = ? AND action_type = "edit_notify"''', (s_id,))
    notify_sent = c.fetchone()[0] > 0
    
    conn.close()
    
    return jsonify({
        'ok': 1,
        'schedule': {
            'id': row[0],
            'year': row[1],
            'month': row[2],
            'day': row[3],
            'type': row[4],
            'end_year': row[5],
            'end_month': row[6],
            'end_day': row[7],
            'time': row[8],
            'server_id': row[9],
            'ip': row[10],
            'contact_type': row[11],
            'contact_value': row[12],
            'mc_status_check': row[13],
            'created_by': row[14]
        },
        'reservation_count': reservation_count,
        'notify_sent': notify_sent
    })

# ===================== 删除档期 =====================
@app.route('/del_schedule', methods=['POST'])
def del_schedule():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁，无法删除档期！'})
    
    role = get_user_role(uid)
    if role not in (ROLE_OP, ROLE_TRUSTED_OP, ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})

    s_id = request.json.get("id")
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 检查权限：如果是普通档主，只能删除自己的档期
    if role == ROLE_OP:
        c.execute('''SELECT created_by FROM schedules WHERE id=?''', (s_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '档期不存在'})
        created_by = row[0]
        if created_by != uid:
            conn.close()
            return jsonify({'ok': 0, 'msg': '权限不足，只能删除自己创建的档期'})
    
    # 获取档期信息用于通知
    c.execute('''SELECT year, month, day, time, server_id FROM schedules WHERE id=?''', (s_id,))
    schedule_row = c.fetchone()
    if not schedule_row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '档期不存在'})
    
    year, month, day, time, server_id = schedule_row
    
    # 获取所有预约用户的邮箱
    c.execute('''SELECT u.email, r.user_id FROM reservations r 
                 JOIN users u ON r.user_id = u.id 
                 WHERE r.schedule_id = ?''', (s_id,))
    reservation_users = c.fetchall()
    
    # 先删除相关预约的定时任务
    delete_reservation_jobs(s_id)
    
    # 删除档期标签关联
    c.execute("DELETE FROM schedule_tags WHERE schedule_id=?", (s_id,))
    
    # 删除档期
    c.execute("DELETE FROM schedules WHERE id=?", (s_id,))
    
    # 删除相关预约记录
    c.execute("DELETE FROM reservations WHERE schedule_id=?", (s_id,))
    
    conn.commit()
    conn.close()
    
    # 发送通知邮件给预约用户
    if reservation_users:
        send_schedule_deleted_notification(reservation_users, year, month, day, time, server_id)
    
    return jsonify({'ok': 1})

# ===================== 修改用户权限 =====================
@app.route('/set_user_role', methods=['POST'])
def set_user_role():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅管理员可操作'})
    
    data = request.json or {}
    target_uid = data.get("target_uid")
    target_role = data.get("target_role")
    
    if not target_uid or target_role is None:
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    try:
        target_role = int(target_role)
    except ValueError:
        return jsonify({'ok': 0, 'msg': '权限值无效'})
    
    if target_role < ROLE_NORMAL or target_role > ROLE_SUPER_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限值超出范围'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT role FROM user_role WHERE uid = ?", (target_uid,))
    row = c.fetchone()
    
    if row:
        c.execute("UPDATE user_role SET role = ? WHERE uid = ?", (target_role, target_uid))
    else:
        c.execute("INSERT INTO user_role (uid, role) VALUES (?, ?)", (target_uid, target_role))
    
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': '权限修改成功'})

# ===================== 删除用户 =====================
@app.route('/delete_user', methods=['POST'])
def delete_user():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅管理员可操作'})

    data = request.json or {}
    target_uid = data.get("target_uid")

    if not target_uid:
        return jsonify({'ok': 0, 'msg': '缺少参数'})
    
    if target_uid == uid:
        return jsonify({'ok': 0, 'msg': '不能删除自己的账号'})

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("DELETE FROM reservations WHERE user_id=?", (target_uid,))
        c.execute("DELETE FROM op_applications WHERE uid=?", (target_uid,))
        c.execute("DELETE FROM penalties WHERE uid=?", (target_uid,))
        c.execute("DELETE FROM op_actions WHERE uid=?", (target_uid,))
        c.execute("DELETE FROM notifications WHERE uid=?", (target_uid,))
        c.execute("DELETE FROM login_attempts WHERE username=?", (target_uid,))
        c.execute("DELETE FROM violations WHERE uid=?", (target_uid,))
        c.execute("DELETE FROM schedules WHERE created_by=?", (target_uid,))
        c.execute("DELETE FROM user_role WHERE uid=?", (target_uid,))
        c.execute("DELETE FROM users WHERE id=?", (target_uid,))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'ok': 0, 'msg': '删除失败: ' + str(e)})
    conn.close()
    
    log_operation(uid, 'delete_user', target_uid, '删除用户')
    return jsonify({'ok': 1})

# ===================== 修改用户密码 =====================
@app.route('/reset_user_password', methods=['POST'])
def reset_user_password():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅管理员可操作'})

    data = request.json or {}
    target_uid = data.get("target_uid")
    new_password = data.get("new_password")

    if not target_uid or not new_password:
        return jsonify({'ok': 0, 'msg': '缺少参数'})

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    new_hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    c.execute("UPDATE users SET pwd=? WHERE id=?", (new_hashed_password, target_uid))
    conn.commit()
    conn.close()
    return jsonify({'ok': 1})

# ===================== 获取待审核档期 =====================
@app.route('/get_pending_schedules', methods=['POST'])
def get_pending_schedules():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅最高管理员可操作'})

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT id, year, month, day, time, server_id, ip, contact_type, contact_value, created_by
                 FROM schedules WHERE approved=0''')
    rows = c.fetchall()
    conn.close()

    res = []
    for item in rows:
        s_id, year, month, day, s_time, srv_id, ip, contact_type, contact_value, created_by = item
        res.append({
            "id": s_id,
            "year": year,
            "month": month,
            "day": day,
            "time": s_time,
            "server_id": srv_id,
            "ip": ip,
            "contact_type": contact_type,
            "contact_value": contact_value,
            "created_by": created_by
        })
    return jsonify(res)

# ===================== 批准档期 =====================
@app.route('/approve_schedule', methods=['POST'])
def approve_schedule():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅最高管理员可操作'})

    data = request.json or {}
    s_id = data.get("id")
    
    print(f"[DEBUG] 接收到批准档期请求，s_id: {s_id}")

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        # 先获取档期信息
        c.execute("SELECT year, month, day, time, server_id, created_by FROM schedules WHERE id=?", (s_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '档期不存在'})
        
        year, month, day, time, server_id, created_by = row
        print(f"[DEBUG] 找到档期：日期 {year}-{month}-{day}，创建者 {created_by}")
        
        # 更新批准状态
        c.execute("UPDATE schedules SET approved=1 WHERE id=?", (s_id,))
        conn.commit()
        print(f"[DEBUG] 档期状态已更新为已批准")
        
        # 获取创建者的邮箱
        to_email = None
        if created_by:
            c.execute("SELECT email FROM users WHERE id=?", (created_by,))
            email_row = c.fetchone()
            if email_row:
                to_email = email_row[0]
                print(f"[DEBUG] 找到创建者邮箱：{to_email}")
        
        conn.close()
        
        # 发送邮件通知
        if to_email:
            print(f"[DEBUG] 开始发送审核通过邮件")
            send_schedule_result_email(to_email, created_by, True, year, month, day, time, server_id)
        else:
            print(f"[WARNING] 没有找到创建者的邮箱，无法发送邮件")
        
        return jsonify({'ok': 1, 'msg': '档期已批准'})
    except Exception as e:
        conn.close()
        print(f"批准档期出错: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'操作失败: {str(e)}'})

# ===================== 拒绝档期 =====================
@app.route('/reject_schedule', methods=['POST'])
def reject_schedule():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅最高管理员可操作'})

    data = request.json or {}
    s_id = data.get("id")
    
    print(f"[DEBUG] 接收到拒绝档期请求，s_id: {s_id}")

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        # 先获取档期信息
        c.execute("SELECT year, month, day, time, server_id, created_by FROM schedules WHERE id=?", (s_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '档期不存在'})
        
        year, month, day, time, server_id, created_by = row
        print(f"[DEBUG] 找到档期：日期 {year}-{month}-{day}，创建者 {created_by}")
        
        # 获取创建者的邮箱
        to_email = None
        if created_by:
            c.execute("SELECT email FROM users WHERE id=?", (created_by,))
            email_row = c.fetchone()
            if email_row:
                to_email = email_row[0]
                print(f"[DEBUG] 找到创建者邮箱：{to_email}")
        
        # 删除档期
        c.execute("DELETE FROM schedules WHERE id=?", (s_id,))
        conn.commit()
        print(f"[DEBUG] 档期已删除")
        conn.close()
        
        # 发送邮件通知
        if to_email:
            print(f"[DEBUG] 开始发送拒绝邮件")
            send_schedule_result_email(to_email, created_by, False, year, month, day, time, server_id)
        else:
            print(f"[WARNING] 没有找到创建者的邮箱，无法发送邮件")
        
        return jsonify({'ok': 1, 'msg': '档期已拒绝'})
    except Exception as e:
        conn.close()
        print(f"拒绝档期出错: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': f'操作失败: {str(e)}'})

# ===================== 系统配置与统计 =====================

@app.route('/get_user_stats', methods=['POST'])
def get_user_stats():
    """获取用户统计数据"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 检查是否开启显示
    c.execute("SELECT value FROM system_config WHERE key = ?", ("show_user_count",))
    result = c.fetchone()
    show_count = result[0] == "1" if result else False
    
    if not show_count:
        conn.close()
        return jsonify({'ok': 0, 'msg': '统计功能已关闭'})
    
    # 获取总用户数
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    
    # 获取各角色人数
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_NORMAL,))
    normal_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_OP,))
    op_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM user_role WHERE role = ?", (ROLE_ADMIN,))
    admin_count = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'ok': 1,
        'total': total,
        'normal': normal_count,
        'op': op_count,
        'admin': admin_count
    })

@app.route('/admin/get_system_config', methods=['POST'])
def admin_get_system_config():
    """管理员获取系统配置"""
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '未登录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
    row = c.fetchone()
    if not row or row[0] not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        conn.close()
        return jsonify({'ok': 0, 'msg': '无权限'})
    
    c.execute("SELECT key, value FROM system_config")
    configs = {}
    for row in c.fetchall():
        configs[row[0]] = row[1]
    
    conn.close()
    return jsonify({'ok': 1, 'configs': configs})

@app.route('/admin/set_system_config', methods=['POST'])
def admin_set_system_config():
    """管理员设置系统配置"""
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '未登录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
    row = c.fetchone()
    if not row or row[0] not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        conn.close()
        return jsonify({'ok': 0, 'msg': '无权限'})
    
    data = request.json or {}
    key = data.get('key')
    value = data.get('value')
    
    if key is None or value is None:
        conn.close()
        return jsonify({'ok': 0, 'msg': '参数错误'})
    
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': '设置已保存'})

@app.route('/admin/save_bg_image_url', methods=['POST'])
def admin_save_bg_image_url():
    """管理员保存背景图片URL"""
    try:
        uid = session.get("user")
        if not uid:
            return jsonify({'ok': 0, 'msg': '未登录'})
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
        row = c.fetchone()
        if not row or row[0] not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            conn.close()
            return jsonify({'ok': 0, 'msg': '无权限'})
        
        data = request.json or {}
        url = data.get('url', '').strip()
        
        if not url:
            conn.close()
            return jsonify({'ok': 0, 'msg': '请输入图片URL'})
        
        if not url.startswith('http://') and not url.startswith('https://'):
            conn.close()
            return jsonify({'ok': 0, 'msg': '请输入有效的URL（以http://或https://开头）'})
        
        # 支持所有常见图片格式
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", ('background_image', url))
        conn.commit()
        conn.close()
        
        return jsonify({'ok': 1, 'msg': '设置成功', 'url': url})
    except Exception as e:
        try:
            conn.close()
        except:
            pass
        return jsonify({'ok': 0, 'msg': '设置失败: ' + str(e)})

@app.route('/admin/upload_bg_image_base64', methods=['POST'])
def admin_upload_bg_image_base64():
    """管理员上传背景图片（Base64方式）"""
    try:
        uid = session.get("user")
        if not uid:
            return jsonify({'ok': 0, 'msg': '未登录'})
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
        row = c.fetchone()
        if not row or row[0] not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            conn.close()
            return jsonify({'ok': 0, 'msg': '无权限'})
        
        data = request.json or {}
        image_data = data.get('image')
        filename = data.get('filename', 'background.jpg')
        
        if not image_data:
            conn.close()
            return jsonify({'ok': 0, 'msg': '未选择文件'})
        
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if '.' not in filename:
            conn.close()
            return jsonify({'ok': 0, 'msg': '文件名格式不正确'})
        
        ext = filename.rsplit('.', 1)[1].lower()
        if ext not in allowed_extensions:
            conn.close()
            return jsonify({'ok': 0, 'msg': '不支持的文件格式，支持：png, jpg, jpeg, gif, webp'})
        
        if not image_data.startswith('data:image/'):
            conn.close()
            return jsonify({'ok': 0, 'msg': '图片格式不正确'})
        
        import base64
        image_bytes = base64.b64decode(image_data.split(',')[1])
        
        upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'bg')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        output_filename = 'background.' + ext
        file_path = os.path.join(upload_folder, output_filename)
        
        with open(file_path, 'wb') as f:
            f.write(image_bytes)
        
        if not os.path.exists(file_path):
            conn.close()
            return jsonify({'ok': 0, 'msg': '文件保存失败，请检查目录权限'})
        
        bg_url = '/static/bg/' + output_filename
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", ('background_image', bg_url))
        conn.commit()
        conn.close()
        
        return jsonify({'ok': 1, 'msg': '上传成功', 'url': bg_url})
    except Exception as e:
        try:
            conn.close()
        except:
            pass
        return jsonify({'ok': 0, 'msg': '上传失败: ' + str(e)})

@app.route('/admin/upload_bg_image', methods=['POST'])
def admin_upload_bg_image():
    """管理员上传背景图片（FormData方式）"""
    try:
        uid = session.get("user")
        if not uid:
            return jsonify({'ok': 0, 'msg': '未登录'})
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
        row = c.fetchone()
        if not row or row[0] not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            conn.close()
            return jsonify({'ok': 0, 'msg': '无权限'})
        
        if 'file' not in request.files:
            conn.close()
            return jsonify({'ok': 0, 'msg': '未选择文件'})
        
        file = request.files['file']
        if file.filename == '':
            conn.close()
            return jsonify({'ok': 0, 'msg': '未选择文件'})
        
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if '.' not in file.filename:
            conn.close()
            return jsonify({'ok': 0, 'msg': '文件名格式不正确'})
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext not in allowed_extensions:
            conn.close()
            return jsonify({'ok': 0, 'msg': '不支持的文件格式，支持：png, jpg, jpeg, gif, webp'})
        
        upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'bg')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        filename = 'background.' + ext
        file_path = os.path.join(upload_folder, filename)
        
        file.save(file_path)
        
        if not os.path.exists(file_path):
            conn.close()
            return jsonify({'ok': 0, 'msg': '文件保存失败，请检查目录权限'})
        
        bg_url = '/static/bg/' + filename
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", ('background_image', bg_url))
        conn.commit()
        conn.close()
        
        return jsonify({'ok': 1, 'msg': '上传成功', 'url': bg_url})
    except Exception as e:
        try:
            conn.close()
        except:
            pass
        return jsonify({'ok': 0, 'msg': '上传失败: ' + str(e)})

@app.route('/admin/clear_bg_image', methods=['POST'])
def admin_clear_bg_image():
    """管理员清除背景图片"""
    try:
        uid = session.get("user")
        if not uid:
            return jsonify({'ok': 0, 'msg': '未登录'})
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT role FROM user_role WHERE uid = ?", (uid,))
        row = c.fetchone()
        if not row or row[0] not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
            conn.close()
            return jsonify({'ok': 0, 'msg': '无权限'})
        
        c.execute("SELECT value FROM system_config WHERE key = ?", ('background_image',))
        bg_url = c.fetchone()
        
        c.execute("DELETE FROM system_config WHERE key = ?", ('background_image',))
        conn.commit()
        conn.close()
        
        upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'bg')
        if bg_url and bg_url[0]:
            filename = os.path.basename(bg_url[0])
            file_path = os.path.join(upload_folder, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        
        return jsonify({'ok': 1, 'msg': '已清除'})
    except Exception as e:
        try:
            conn.close()
        except:
            pass
        return jsonify({'ok': 0, 'msg': '清除失败: ' + str(e)})

# ===================== 检查档主申请状态 =====================
@app.route('/check_op_apply', methods=['POST'])
def check_op_apply():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '未登录'})
    
    # 先检查用户角色
    role = get_user_role(uid)
    if role >= ROLE_OP:
        return jsonify({'ok': 1, 'status': 2})  # 已经是档主了
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT status FROM op_applications WHERE uid=? ORDER BY id DESC LIMIT 1''', (uid,))
    row = c.fetchone()
    conn.close()
    
    if row:
        status = row[0]
        if status == 0:
            return jsonify({'ok': 1, 'status': 0})  # 待审核
        elif status == 1:
            return jsonify({'ok': 1, 'status': 2})  # 已批准，也是档主
        else:  # status == 2 已拒绝
            return jsonify({'ok': 1, 'status': 3})  # 已拒绝，可以重新申请
    else:
        return jsonify({'ok': 1, 'status': 3})  # 未申请过

# ===================== 提交档主申请 =====================
@app.route('/apply_op', methods=['POST'])
def apply_op():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '未登录'})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁，无法申请成为档主！'})
    
    role = get_user_role(uid)
    if role >= ROLE_OP:
        return jsonify({'ok': 0, 'msg': '您已经是档主了'})
    
    # 检查是否已有未审核的申请
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT id FROM op_applications WHERE uid=? AND status=0''', (uid,))
    row = c.fetchone()
    if row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '您已有申请正在审核中，请耐心等待'})
    
    data = request.json or {}
    server_ip = data.get("server_ip", "").strip()
    contact = data.get("contact", "").strip()
    
    if not server_ip:
        conn.close()
        return jsonify({'ok': 0, 'msg': '请填写服务器IP地址'})
    
    try:
        c.execute('''INSERT INTO op_applications
                     (uid, server_ip, qq_group, status, created_at)
                     VALUES (?, ?, ?, 0, ?)''', 
                  (uid, server_ip, contact, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()
        print(f"保存申请失败: {e}")
        return jsonify({'ok': 0, 'msg': '提交失败'})
    
    # 发送邮件通知管理员
    send_op_apply_notification(uid, server_ip, contact)
    
    return jsonify({'ok': 1, 'msg': '申请提交成功，管理员将在24-48小时内审核，请保持邮箱畅通'})

# ===================== 获取待审核的档主申请（管理员） =====================
@app.route('/get_pending_op_applications', methods=['POST'])
def get_pending_op_applications():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅最高管理员可操作'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT id, uid, server_ip, qq_group, created_at
                 FROM op_applications WHERE status=0 ORDER BY id DESC''')
    rows = c.fetchall()
    conn.close()
    
    res = []
    for item in rows:
        app_id, app_uid, server_ip, qq_group, created_at = item
        res.append({
            "id": app_id,
            "uid": app_uid,
            "server_ip": server_ip,
            "qq_group": qq_group,
            "created_at": created_at
        })
    return jsonify(res)

# ===================== 审核档主申请（管理员） =====================
@app.route('/approve_op_application', methods=['POST'])
def approve_op_application():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '仅最高管理员可操作'})
    
    data = request.json or {}
    application_id = int(data.get("application_id"))
    approve = int(data.get("approve"))  # 1 批准，2 拒绝
    
    print(f"[DEBUG] 接收到审核档主申请请求，申请ID: {application_id}, 操作: {'批准' if approve == 1 else '拒绝'}")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 获取申请信息
        c.execute('''SELECT uid FROM op_applications WHERE id=?''', (application_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '申请不存在'})
        
        app_uid = row[0]
        print(f"[DEBUG] 找到申请，申请人: {app_uid}")
        
        # 获取申请人的邮箱
        c.execute('''SELECT email FROM users WHERE id=?''', (app_uid,))
        email_row = c.fetchone()
        to_email = email_row[0] if email_row else None
        if to_email:
            print(f"[DEBUG] 找到申请人邮箱: {to_email}")
        
        # 更新申请状态
        c.execute('''UPDATE op_applications SET status=? WHERE id=?''', (approve, application_id))
        
        if approve == 1:
            print(f"[DEBUG] 批准申请，设置用户角色为档主")
            # 设置用户角色为档主
            c.execute('''SELECT uid FROM user_role WHERE uid=?''', (app_uid,))
            exists = c.fetchone()
            if exists:
                c.execute('''UPDATE user_role SET role=? WHERE uid=?''', (ROLE_OP, app_uid))
            else:
                c.execute('''INSERT INTO user_role (uid, role) VALUES (?, ?)''', (app_uid, ROLE_OP))
        
        conn.commit()
        conn.close()
        
        # 发送邮件通知
        if to_email:
            print(f"[DEBUG] 开始发送档主申请审核结果邮件")
            send_op_apply_result_email(to_email, app_uid, approve == 1)
        else:
            print(f"[WARNING] 没有找到申请人的邮箱，无法发送邮件")
        
        return jsonify({'ok': 1})
    except Exception as e:
        conn.close()
        print(f"审核失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': 0, 'msg': str(e)})

# ===================== 预约功能API =====================

# 获取用户的预约列表
@app.route('/get_my_reservations', methods=['POST'])
def get_my_reservations():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute('''SELECT r.id, r.schedule_id, r.created_at, r.reminder_sent,
                        s.year, s.month, s.day, s.time, s.server_id, s.ip
                 FROM reservations r
                 JOIN schedules s ON r.schedule_id = s.id
                 WHERE r.user_id = ?
                 ORDER BY s.year, s.month, s.day''', (uid,))
    rows = c.fetchall()
    conn.close()
    
    res = []
    for item in rows:
        res.append({
            "id": item[0],
            "schedule_id": item[1],
            "created_at": item[2],
            "reminder_sent": item[3],
            "year": item[4],
            "month": item[5],
            "day": item[6],
            "time": item[7],
            "server_id": item[8],
            "ip": item[9]
        })
    return jsonify({'ok': 1, 'reservations': res})

# 获取档期的预约列表（仅管理员查看）
@app.route('/get_schedule_reservations', methods=['POST'])
def get_schedule_reservations():
    uid = session.get("user")
    role = get_user_role(uid)
    
    data = request.json or {}
    schedule_id = data.get("schedule_id")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取档期的创建者
    c.execute('SELECT created_by FROM schedules WHERE id = ?', (schedule_id,))
    schedule_row = c.fetchone()
    
    if not schedule_row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '档期不存在'})
    
    created_by = schedule_row[0]
    
    # 权限检查：管理员和最高管理员可以查看所有，档主和信用档主只能查看自己创建的档期
    if role in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        pass
    elif role in (ROLE_OP, ROLE_TRUSTED_OP):
        if created_by != uid:
            conn.close()
            return jsonify({'ok': 0, 'msg': '权限不足，只能查看自己创建的档期预约列表'})
    else:
        conn.close()
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    c.execute('''SELECT r.id, r.user_id, u.uid, u.nickname, r.created_at, u.email
                 FROM reservations r
                 JOIN users u ON r.user_id = u.id
                 WHERE r.schedule_id = ?
                 ORDER BY r.created_at''', (schedule_id,))
    rows = c.fetchall()
    conn.close()
    
    res = []
    for item in rows:
        reservation = {
            "id": item[0],
            "user_id": item[1],
            "uid": item[2],
            "nickname": item[3] if item[3] else item[2],
            "created_at": item[4]
        }
        # 只有管理员可以看到邮箱
        if role == ROLE_ADMIN or role == ROLE_SUPER_ADMIN:
            reservation["email"] = item[5]
        res.append(reservation)
    return jsonify({'ok': 1, 'reservations': res})

# 预约档期
@app.route('/create_reservation', methods=['POST'])
def create_reservation():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁，无法预约档期！'})
    
    data = request.json or {}
    schedule_id = data.get("schedule_id")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 检查档期是否存在且已批准
        c.execute('''SELECT id, year, month, day, time, server_id, ip, contact_type, contact_value, approved 
                    FROM schedules WHERE id=?''', (schedule_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '档期不存在'})
        
        sched_id, year, month, day, time_str, server_id, ip, contact_type, contact_value, approved = row
        
        if approved != 1:
            conn.close()
            return jsonify({'ok': 0, 'msg': '档期未批准，无法预约'})
        
        # 检查是否已经预约过
        c.execute('''SELECT id FROM reservations WHERE user_id=? AND schedule_id=?''', (uid, schedule_id))
        if c.fetchone():
            conn.close()
            return jsonify({'ok': 0, 'msg': '您已经预约过这个档期了'})
        
        # 获取用户邮箱
        c.execute('''SELECT email FROM users WHERE id=?''', (uid,))
        user_email = c.fetchone()[0]
        
        # 创建预约
        c.execute('''INSERT INTO reservations (user_id, schedule_id) VALUES (?, ?)''', (uid, schedule_id))
        reservation_id = c.lastrowid
        conn.commit()
        
        # 发送预约成功通知
        send_notification(uid, "✅ 预约成功", 
                         f"""恭喜您成功预约了档期！

📅 档期信息：
• 日期：{year}年{month}月{day}日
• 时间：{time_str}
• 服务器ID：{server_id}
• 服务器IP：{ip}

💡 温馨提示：
• 开服前我们会通过邮件提醒您
• 请准时参加，不要错过
• 如需取消预约，请前往个人中心

祝您游戏愉快！
""", 'reservation_success')
        
        conn.close()
        
        # 解析开服时间
        start_time_str = time_str.split('-')[0].strip() if '-' in time_str else time_str
        try:
            schedule_datetime = datetime(year, month, day)
            if ':' in start_time_str:
                hour, minute = map(int, start_time_str.split(':'))
                schedule_datetime = schedule_datetime.replace(hour=hour, minute=minute)
            
            # 检查是否是未来时间
            if schedule_datetime > datetime.now():
                # 创建定时任务
                job_id = f"reservation_{reservation_id}"
                schedule_info = {
                    'year': year,
                    'month': month,
                    'day': day,
                    'time': time_str,
                    'server_id': server_id,
                    'ip': ip,
                    'contact_type': contact_type,
                    'contact_value': contact_value
                }
                
                scheduler.add_job(
                    send_reservation_reminder,
                    'date',
                    run_date=schedule_datetime,
                    args=[user_email, uid, schedule_info],
                    id=job_id
                )
                reservation_job_map[reservation_id] = job_id
                print(f"[预约提醒] 已为预约 {reservation_id} 设定提醒: {schedule_datetime}")
        except Exception as e:
            print(f"创建定时任务失败: {e}")
        
        return jsonify({'ok': 1, 'msg': '预约成功！我们会在开服时间通过邮件提醒您'})
    except Exception as e:
        conn.close()
        print(f"预约失败: {e}")
        return jsonify({'ok': 0, 'msg': '预约失败'})

# 取消预约
@app.route('/cancel_reservation', methods=['POST'])
def cancel_reservation():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({'ok': 0, 'msg': '您的账号已被封禁，无法取消预约！'})
    
    data = request.json or {}
    reservation_id = data.get("reservation_id")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 检查是否是自己的预约
        c.execute('''SELECT id FROM reservations WHERE id=? AND user_id=?''', (reservation_id, uid))
        if not c.fetchone():
            conn.close()
            return jsonify({'ok': 0, 'msg': '预约不存在或无权限'})
        
        # 删除预约
        c.execute('''DELETE FROM reservations WHERE id=?''', (reservation_id,))
        conn.commit()
        
        # 发送取消预约通知
        send_notification(uid, "📌 预约已取消", 
                         f"""您的预约已成功取消。

💡 温馨提示：
• 如需重新预约，请前往档期列表
• 建议您提前关注档期信息，不要错过

感谢您的使用！
""", 'reservation_cancel')
        
        conn.close()
        
        # 取消定时任务
        job_id = reservation_job_map.get(reservation_id)
        if job_id:
            try:
                scheduler.remove_job(job_id)
                del reservation_job_map[reservation_id]
                print(f"[预约提醒] 已取消预约 {reservation_id} 的提醒任务")
            except Exception as e:
                print(f"取消定时任务失败: {e}")
        
        return jsonify({'ok': 1, 'msg': '已取消预约'})
    except Exception as e:
        conn.close()
        print(f"取消预约失败: {e}")
        return jsonify({'ok': 0, 'msg': '取消预约失败'})

# 检查用户是否已预约某个档期
@app.route('/check_reservation', methods=['POST'])
def check_reservation():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    schedule_id = data.get("schedule_id")
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''SELECT id FROM reservations WHERE user_id=? AND schedule_id=?''', (uid, schedule_id))
    row = c.fetchone()
    conn.close()
    
    return jsonify({'ok': 1, 'reserved': row is not None})

# ===================== 发送提醒通知 =====================
def send_reservation_reminder(to_email, user_id, schedule_info):
    try:
        inbox_enabled = get_notification_setting('reservation_reminder', 'inbox')
        email_enabled = get_notification_setting('reservation_reminder', 'email')
        
        if not inbox_enabled and not email_enabled:
            print(f"[通知] 预约提醒通知已全部禁用")
            return True
        
        notif_content = f"""您预约的服务器即将开服！

🎮 服务器：{schedule_info['server_id']}
📅 日期：{schedule_info['year']}年{schedule_info['month']}月{schedule_info['day']}日
🕐 时段：{schedule_info['time']}"""
        
        if schedule_info.get('ip'):
            notif_content += f"\n🌐 IP地址：{schedule_info['ip']}"
        
        if schedule_info.get('contact_type') and schedule_info.get('contact_value'):
            contact_label = {
                'qq': 'QQ号',
                'wechat': '微信号',
                'phone': '手机号',
                'email': '邮箱'
            }.get(schedule_info['contact_type'], '联系方式')
            notif_content += f"\n📞 {contact_label}：{schedule_info['contact_value']}"
        
        notif_content += "\n\n祝您游戏愉快！"
        
        if inbox_enabled:
            create_inbox_notification(user_id, "🔔 服务器开服提醒", notif_content, 'reservation_reminder')
        
        if email_enabled and to_email:
            email_content = f"""亲爱的 {user_id}：

{notif_content}

---
此邮件由系统自动发送，请勿回复。
"""
            if use_pool and email_pool_manager:
                success = email_pool_manager.send_direct([to_email], "【MC档期排期站】服务器开服提醒", email_content)
                if success:
                    print(f"[SUCCESS] 已发送预约提醒邮件到 {to_email}")
            else:
                msg = Message("【MC档期排期站】服务器开服提醒",
                             sender=app.config['MAIL_USERNAME'],
                             recipients=[to_email])
                msg.body = email_content
                mail.send(msg)
                print(f"[SUCCESS] 已发送预约提醒邮件到 {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] 发送预约提醒通知失败: {e}")
        import traceback
        traceback.print_exc()
        return False

# 更新档期相关预约的定时任务
def update_reservation_jobs(schedule_id):
    """更新某个档期所有预约的定时任务"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 获取档期信息
        c.execute('''SELECT id, year, month, day, time, server_id, ip, contact_type, contact_value
                    FROM schedules WHERE id=?''', (schedule_id,))
        schedule_row = c.fetchone()
        if not schedule_row:
            conn.close()
            return
        
        sched_id, year, month, day, time_str, server_id, ip, contact_type, contact_value = schedule_row
        
        # 获取该档期的所有预约
        c.execute('''SELECT r.id, r.user_id, u.email
                     FROM reservations r
                     JOIN users u ON r.user_id = u.id
                     WHERE r.schedule_id=?''', (schedule_id,))
        reservations = c.fetchall()
        
        # 解析新的开服时间
        start_time_str = time_str.split('-')[0].strip() if '-' in time_str else time_str
        try:
            new_schedule_datetime = datetime(year, month, day)
            if ':' in start_time_str:
                hour, minute = map(int, start_time_str.split(':'))
                new_schedule_datetime = new_schedule_datetime.replace(hour=hour, minute=minute)
            
            # 更新每个预约的定时任务
            for res_id, user_id, email in reservations:
                job_id = f"reservation_{res_id}"
                schedule_info = {
                    'year': year,
                    'month': month,
                    'day': day,
                    'time': time_str,
                    'server_id': server_id,
                    'ip': ip,
                    'contact_type': contact_type,
                    'contact_value': contact_value
                }
                
                # 删除旧任务（如果存在）
                try:
                    scheduler.remove_job(job_id)
                except:
                    pass
                
                # 只对未来的时间创建新任务
                if new_schedule_datetime > datetime.now():
                    scheduler.add_job(
                        send_reservation_reminder,
                        'date',
                        run_date=new_schedule_datetime,
                        args=[email, user_id, schedule_info],
                        id=job_id
                    )
                    reservation_job_map[res_id] = job_id
                    print(f"[预约提醒] 已更新预约 {res_id} 的提醒: {new_schedule_datetime}")
                else:
                    # 如果时间已过，从映射中删除
                    if res_id in reservation_job_map:
                        del reservation_job_map[res_id]
        except Exception as e:
            print(f"更新预约任务失败: {e}")
    except Exception as e:
        print(f"获取档期预约信息失败: {e}")
    finally:
        conn.close()

# 删除档期相关预约的定时任务
def delete_reservation_jobs(schedule_id):
    """删除某个档期所有预约的定时任务"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        # 获取该档期的所有预约
        c.execute('''SELECT id FROM reservations WHERE schedule_id=?''', (schedule_id,))
        reservations = c.fetchall()
        
        # 删除每个预约的定时任务
        for (res_id,) in reservations:
            job_id = reservation_job_map.get(res_id)
            if job_id:
                try:
                    scheduler.remove_job(job_id)
                    del reservation_job_map[res_id]
                    print(f"[预约提醒] 已删除预约 {res_id} 的提醒任务")
                except Exception as e:
                    print(f"删除定时任务失败: {e}")
    except Exception as e:
        print(f"删除档期预约任务失败: {e}")
    finally:
        conn.close()

# 启动时恢复已有预约的定时任务
def restore_reservation_jobs():
    """启动时从数据库恢复预约提醒任务"""
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute('''SELECT r.id, r.user_id, r.schedule_id,
                            s.year, s.month, s.day, s.time, s.server_id, s.ip,
                            s.contact_type, s.contact_value,
                            u.email
                     FROM reservations r
                     JOIN schedules s ON r.schedule_id = s.id
                     JOIN users u ON r.user_id = u.id''')
        rows = c.fetchall()
        
        for row in rows:
            res_id, user_id, sched_id, year, month, day, time_str, server_id, ip, contact_type, contact_value, email = row
            
            # 解析开服时间
            start_time_str = time_str.split('-')[0].strip() if '-' in time_str else time_str
            try:
                schedule_datetime = datetime(year, month, day)
                if ':' in start_time_str:
                    hour, minute = map(int, start_time_str.split(':'))
                    schedule_datetime = schedule_datetime.replace(hour=hour, minute=minute)
                
                # 只对未来的时间创建任务
                if schedule_datetime > datetime.now():
                    job_id = f"reservation_{res_id}"
                    schedule_info = {
                        'year': year,
                        'month': month,
                        'day': day,
                        'time': time_str,
                        'server_id': server_id,
                        'ip': ip,
                        'contact_type': contact_type,
                        'contact_value': contact_value
                    }
                    
                    scheduler.add_job(
                        send_reservation_reminder,
                        'date',
                        run_date=schedule_datetime,
                        args=[email, user_id, schedule_info],
                        id=job_id
                    )
                    reservation_job_map[res_id] = job_id
                    print(f"[预约提醒] 已恢复预约 {res_id} 的提醒: {schedule_datetime}")
            except Exception as e:
                print(f"恢复预约 {res_id} 任务失败: {e}")
                continue
    except Exception as e:
        print(f"恢复预约任务出错: {e}")
    finally:
        conn.close()

# 调试邮箱池的路由 - 测试单个邮箱
@app.route('/debug-email-single')
def debug_email_single():
    """测试单个邮箱发送"""
    import datetime
    from flask import request
    
    recipient = request.args.get('to', 'test@example.com')
    email_idx = int(request.args.get('email', 0))
    
    debug_info = []
    debug_info.append(f"测试邮箱池")
    debug_info.append(f"use_pool: {use_pool}")
    debug_info.append(f"recipient: {recipient}")
    debug_info.append(f"email index: {email_idx}")
    
    if email_pool_manager and 0 <= email_idx < len(email_pool_manager.email_pool):
        email_config = email_pool_manager.email_pool[email_idx]
        debug_info.append(f"Testing: {email_config['name']} ({email_config['username']})")
        
        try:
            success = email_pool_manager._send_with_smtp(
                email_config,
                [recipient],
                f"【测试】来自 {email_config['name']}",
                f"这是一封测试邮件！\n\n发送时间: {datetime.now()}"
            )
            debug_info.append(f"发送结果: {success}")
            if success:
                debug_info.append("\n✅ 发送成功！请查收邮箱（包括垃圾邮件）")
            else:
                debug_info.append("\n❌ 发送失败！")
        except Exception as e:
            debug_info.append(f"错误: {e}")
            import traceback
            debug_info.append(traceback.format_exc())
    
    return "<pre>" + "\n".join(debug_info) + "</pre>"

# 调试邮箱池的路由 - 主页面
@app.route('/debug-email')
def debug_email():
    """调试邮箱池主页面"""
    import datetime
    debug_info = []
    
    debug_info.append("=" * 60)
    debug_info.append("邮箱池调试页面")
    debug_info.append("=" * 60)
    debug_info.append(f"use_pool: {use_pool}")
    debug_info.append(f"email_pool_manager: {email_pool_manager is not None}")
    
    if email_pool_manager:
        debug_info.append(f"\n邮箱池配置 ({len(email_pool_manager.email_pool)} 个):")
        for i, email in enumerate(email_pool_manager.email_pool):
            debug_info.append(f"  [{i}] {email['name']}: {email['username']}")
        
        debug_info.append("\n测试链接:")
        for i, email in enumerate(email_pool_manager.email_pool):
            debug_info.append(f"  测试 {email['name']}: /debug-email-single?email={i}&to=你的QQ邮箱@qq.com")
        
        debug_info.append("\n可用邮箱检查:")
        try:
            idx = email_pool_manager._find_available_email()
            debug_info.append(f"  当前可用邮箱索引: {idx}")
            if idx is not None:
                debug_info.append(f"  邮箱: {email_pool_manager.email_pool[idx]['name']}")
        except Exception as e:
            debug_info.append(f"  错误: {e}")
    
    debug_info.append("\n" + "=" * 60)
    debug_info.append("使用说明:")
    debug_info.append("  1. 将链接中的 '你的QQ邮箱@qq.com' 替换为你的实际邮箱")
    debug_info.append("  2. 访问测试链接")
    debug_info.append("  3. 检查QQ邮箱（包括垃圾邮件、订阅邮件文件夹）")
    debug_info.append("=" * 60)
    
    return "<pre>" + "\n".join(debug_info) + "</pre>"

# ==================== 主评论区接口 ====================

# 获取主评论区评论
@app.route("/forum/get_comments", methods=["POST"])
def forum_get_comments():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''SELECT fc.id, fc.uid, u.nickname, u.uid as user_uid, fc.content, fc.created_at 
                 FROM forum_comments fc
                 LEFT JOIN users u ON fc.uid = u.id
                 ORDER BY fc.created_at DESC LIMIT 100''')
    rows = c.fetchall()
    conn.close()
    
    comments = []
    for row in rows:
        comments.append({
            "id": row[0],
            "uid": row[1],
            "nickname": row[2] if row[2] else row[3] if row[3] else row[1],
            "content": row[4],
            "created_at": row[5]
        })
    return jsonify({"ok": 1, "comments": comments})

# 发表主评论区评论
@app.route("/forum/create_comment", methods=["POST"])
def forum_create_comment():
    uid = session.get("user")
    if not uid:
        return jsonify({"ok": 0, "msg": "请先登录！"})
    
    # 检查用户是否被禁言
    is_muted, mute_info = is_user_muted(uid)
    if is_muted:
        return jsonify({"ok": 0, "msg": f"您已被禁言，无法发表评论！原因: {mute_info["reason"]}"})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({"ok": 0, "msg": "您的账号已被封禁，无法发表评论！"})
    
    data = request.json or {}
    content = data.get("content", "").strip()
    
    if not content:
        return jsonify({"ok": 0, "msg": "评论内容不能为空！"})

    # 执行内容审核
    moderation_result = perform_content_moderation(content)
    if moderation_result["action"] == "block":
        # 记录违规
        violation_type = moderation_result.get("type", "content_security")
        violation_info = record_violation(uid, content, violation_type)
        
        # 构建更清楚的提示消息
        if violation_info:
            count = violation_info["count"]
            action = violation_info["action"]
            
            if count == 1:
                msg = f"⚠️ 内容违规！这是第1次提醒。请注意语言规范！"
            elif count == 2:
                msg = f"⚠️ 内容违规！这是第2次警告。继续违规将被禁言！"
            else:
                msg = f"⛔ 内容违规！您已被系统自动禁言！请联系管理员申诉。"
        else:
            msg = f"评论内容不符合规范: {moderation_result["reason"]}"
            
        return jsonify({"ok": 0, "msg": msg})
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''INSERT INTO forum_comments (uid, content, created_at)
                 VALUES (?, ?, ?)''',
              (uid, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    comment_id = c.lastrowid
    conn.close()
    
    return jsonify({"ok": 1, "comment_id": comment_id, "msg": "评论发表成功！"})

# 删除主评论区评论（管理员/档主）
@app.route("/forum/delete_comment", methods=["POST"])
def forum_delete_comment():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_OP, ROLE_TRUSTED_OP, ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({"ok": 0, "msg": "权限不足，无法删除评论"})
    
    data = request.json or {}
    comment_id = data.get("comment_id")
    
    if not comment_id:
        return jsonify({"ok": 0, "msg": "缺少评论ID"})
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    
    if role == ROLE_OP:
        # 档主只能删除自己的评论
        c.execute("SELECT uid FROM forum_comments WHERE id=?", (comment_id,))
        row = c.fetchone()
        if not row or row[0] != uid:
            conn.close()
            return jsonify({"ok": 0, "msg": "权限不足，只能删除自己的评论"})
            
    c.execute("DELETE FROM forum_comments WHERE id=?", (comment_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'ok': 1, 'msg': "评论删除成功"})


# ==================== 后台关键词管理接口 ====================

# 获取所有关键词
@app.route('/admin/keywords/get', methods=['POST'])
def admin_get_keywords():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, word FROM keywords ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    
    keywords = []
    for row in rows:
        keywords.append({
            "id": row[0],
            "word": row[1]
        })
    return jsonify({'ok': 1, 'keywords': keywords})

# 添加关键词
@app.route('/admin/keywords/add', methods=['POST'])
def admin_add_keyword():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    word = data.get('word', '').strip().lower()
    
    if not word:
        return jsonify({'ok': 0, 'msg': '关键词不能为空'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO keywords (word) VALUES (?)", (word,))
        conn.commit()
        conn.close()
        
        # 更新敏感词缓存
        add_sensitive_word(word)
        print(f"[敏感词过滤] 已添加关键词: {word}")
        
        return jsonify({'ok': 1, 'msg': '关键词添加成功'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'ok': 0, 'msg': '关键词已存在'})
    except Exception as e:
        conn.close()
        return jsonify({'ok': 0, 'msg': f'添加失败: {str(e)}'})

# 批量导入关键词（从TXT文件）
@app.route('/admin/keywords/import', methods=['POST'])
def admin_import_keywords():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    # 支持两种方式：上传文件 或 直接传入文本内容
    if 'file' in request.files:
        # 通过文件上传
        file = request.files['file']
        if file.filename == '':
            return jsonify({'ok': 0, 'msg': '请选择文件'})
        
        if not file.filename.endswith('.txt'):
            return jsonify({'ok': 0, 'msg': '只支持TXT文件'})
        
        try:
            content = file.read().decode('utf-8')
        except:
            return jsonify({'ok': 0, 'msg': '文件编码错误，请使用UTF-8编码'})
    else:
        # 通过文本内容传入
        data = request.json or {}
        content = data.get('content', '')
        if not content:
            return jsonify({'ok': 0, 'msg': '内容不能为空'})
    
    # 解析关键词（每行一个）
    lines = content.split('\n')
    words = set()
    for line in lines:
        word = line.strip()
        if word and not word.startswith('#'):  # 跳过空行和注释
            words.add(word.lower())
    
    if not words:
        return jsonify({'ok': 0, 'msg': '未找到有效关键词'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取已存在的关键词
    c.execute("SELECT word FROM keywords")
    existing_words = set(row[0] for row in c.fetchall())
    
    added_count = 0
    skipped_count = 0
    
    for word in words:
        if word not in existing_words:
            try:
                c.execute("INSERT INTO keywords (word) VALUES (?)", (word,))
                added_count += 1
            except:
                skipped_count += 1
        else:
            skipped_count += 1
    
    conn.commit()
    conn.close()
    
    load_sensitive_words()
    
    print(f"[敏感词过滤] 批量导入完成: 新增 {added_count} 个, 跳过 {skipped_count} 个")
    
    return jsonify({
        'ok': 1,
        'msg': f'导入完成！新增 {added_count} 个关键词，跳过 {skipped_count} 个已存在的关键词',
        'added': added_count,
        'skipped': skipped_count
    })

# 删除关键词
@app.route('/admin/keywords/delete', methods=['POST'])
def admin_delete_keyword():
    current_user = session.get('user', '')
    current_role = get_user_role(current_user) if current_user else ROLE_NORMAL
    if current_role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    keyword_id = data.get('id')
    
    if not keyword_id:
        return jsonify({'ok': 0, 'msg': '缺少关键词ID'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        # 先获取要删除的关键词
        c.execute("SELECT word FROM keywords WHERE id=?", (keyword_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': 0, 'msg': '关键词不存在'})
        
        word_to_delete = row[0]
        
        # 删除数据库记录
        c.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
        conn.commit()
        conn.close()
        
        # 重新加载所有敏感词
        load_sensitive_words()
        
        return jsonify({'ok': 1, 'msg': '关键词删除成功'})
    except Exception as e:
        conn.close()
        return jsonify({'ok': 0, 'msg': f'删除失败: {str(e)}'})


# ==================== 关键词过滤辅助函数 ====================
def check_for_keywords(content):
    """检查内容是否包含敏感词"""
    if not content or not content.strip():
        return False
    
    content_lower = content.lower()
    
    # 首先检查内存中的缓存
    for keyword in _sensitive_words_cache:
        if keyword in content_lower:
            print(f"[敏感词过滤] 检测到敏感词: {keyword}")
            return True
    
    return False




# 删除档期评论区评论（管理员/档主）
@app.route("/schedule_forum/delete_comment", methods=["POST"])
def schedule_forum_delete_comment():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_OP, ROLE_TRUSTED_OP, ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({"ok": 0, "msg": "权限不足，无法删除评论"})
    
    data = request.json or {}
    comment_id = data.get("comment_id")
    
    if not comment_id:
        return jsonify({"ok": 0, "msg": "缺少评论ID"})
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    
    if role == ROLE_OP:
        # 档主只能删除自己的评论
        c.execute("SELECT uid FROM schedule_comments WHERE id=?", (comment_id,))
        row = c.fetchone()
        if not row or row[0] != uid:
            conn.close()
            return jsonify({"ok": 0, "msg": "权限不足，只能删除自己的评论"})
            
    c.execute("DELETE FROM schedule_comments WHERE id=?", (comment_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"ok": 1, "msg": "评论删除成功"})


# ==================== 档期评论区接口 ====================

# 获取档期评论区评论
@app.route("/schedule_forum/get_comments", methods=["POST"])
def schedule_forum_get_comments():
    data = request.json or {}
    schedule_id = data.get("schedule_id")
    
    if not schedule_id:
        return jsonify({"ok": 0, "msg": "参数错误！"})
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''SELECT sc.id, sc.uid, u.nickname, u.uid as user_uid, sc.content, sc.created_at 
                 FROM schedule_comments sc
                 LEFT JOIN users u ON sc.uid = u.id
                 WHERE sc.schedule_id = ?
                 ORDER BY sc.created_at DESC LIMIT 50''', (schedule_id,))
    rows = c.fetchall()
    conn.close()
    
    comments = []
    for row in rows:
        comments.append({
            "id": row[0],
            "uid": row[1],
            "nickname": row[2] if row[2] else row[3] if row[3] else row[1],
            "content": row[4],
            "created_at": row[5]
        })
    return jsonify({"ok": 1, "comments": comments})

# 发表档期评论区评论
@app.route("/schedule_forum/create_comment", methods=["POST"])
def schedule_forum_create_comment():
    uid = session.get("user")
    if not uid:
        return jsonify({"ok": 0, "msg": "请先登录！"})
    
    # 检查用户是否被禁言
    is_muted, mute_info = is_user_muted(uid)
    if is_muted:
        return jsonify({"ok": 0, "msg": f"您已被禁言，无法发表评论！原因: {mute_info["reason"]}"})
    
    # 检查用户是否被封禁
    if is_user_banned(uid):
        return jsonify({"ok": 0, "msg": "您的账号已被封禁，无法发表评论！"})
    
    data = request.json or {}
    schedule_id = data.get("schedule_id")
    content = data.get("content", "").strip()
    
    if not schedule_id or not content:
        return jsonify({"ok": 0, "msg": "评论内容或档期ID不能为空！"})

    # 执行内容审核
    moderation_result = perform_content_moderation(content)
    if moderation_result["action"] == "block":
        # 记录违规
        violation_type = moderation_result.get("type", "content_security")
        violation_info = record_violation(uid, content, violation_type)
        
        # 构建更清楚的提示消息
        if violation_info:
            count = violation_info["count"]
            action = violation_info["action"]
            
            if count == 1:
                msg = f"⚠️ 内容违规！这是第1次提醒。请注意语言规范！"
            elif count == 2:
                msg = f"⚠️ 内容违规！这是第2次警告。继续违规将被禁言！"
            else:
                msg = f"⛔ 内容违规！您已被系统自动禁言！请联系管理员申诉。"
        else:
            msg = f"评论内容不符合规范: {moderation_result["reason"]}"
            
        return jsonify({"ok": 0, "msg": msg})
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''INSERT INTO schedule_comments (schedule_id, uid, content, created_at)
                 VALUES (?, ?, ?, ?)''',
              (schedule_id, uid, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    comment_id = c.lastrowid
    conn.close()
    
    return jsonify({"ok": 1, "comment_id": comment_id, "msg": "评论发表成功！"})

# ==================== 安全管理接口 ====================

# 获取操作日志
@app.route('/admin/get_security_logs', methods=['POST'])
def admin_get_security_logs():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    filter_uid = data.get('uid', '').strip()
    filter_action = data.get('action', '').strip()
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    query = 'SELECT id, uid, ip_address, action, target, details, created_at FROM security_logs WHERE 1=1'
    params = []
    
    if filter_uid:
        query += ' AND uid LIKE ?'
        params.append(f'%{filter_uid}%')
    
    if filter_action:
        query += ' AND action LIKE ?'
        params.append(f'%{filter_action}%')
    
    query += ' ORDER BY created_at DESC LIMIT 100'
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    logs = []
    for row in rows:
        logs.append({
            'id': row[0],
            'uid': row[1],
            'ip_address': row[2],
            'action': row[3],
            'target': row[4],
            'details': row[5],
            'created_at': row[6]
        })
    
    return jsonify({'ok': 1, 'logs': logs})

# 获取IP黑名单
@app.route('/admin/get_ip_blacklist', methods=['POST'])
def admin_get_ip_blacklist():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, ip_address, reason, created_by, created_at, expires_at FROM ip_blacklist ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    
    blacklist = []
    for row in rows:
        blacklist.append({
            'id': row[0],
            'ip_address': row[1],
            'reason': row[2],
            'created_by': row[3],
            'created_at': row[4],
            'expires_at': row[5]
        })
    
    return jsonify({'ok': 1, 'blacklist': blacklist})

# 添加IP到黑名单
@app.route('/admin/add_ip_blacklist', methods=['POST'])
def admin_add_ip_blacklist():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    ip = data.get('ip', '').strip()
    reason = data.get('reason', '恶意行为').strip()
    duration = int(data.get('duration', 0))  # 天数，0为永久
    
    if not ip:
        return jsonify({'ok': 0, 'msg': '请输入IP地址'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 检查是否已在黑名单中
    c.execute('SELECT id FROM ip_blacklist WHERE ip_address = ?', (ip,))
    if c.fetchone():
        conn.close()
        return jsonify({'ok': 0, 'msg': '该IP已在黑名单中'})
    
    expires_at = None
    if duration > 0:
        expires_at = (datetime.now() + timedelta(days=duration)).strftime("%Y-%m-%d %H:%M:%S")
    
    c.execute('''INSERT INTO ip_blacklist (ip_address, reason, created_by, created_at, expires_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (ip, reason, uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), expires_at))
    conn.commit()
    conn.close()
    
    log_operation(uid, 'add_ip_blacklist', ip, f'封禁原因: {reason}, 时长: {"永久" if duration == 0 else f"{duration}天"}')
    
    return jsonify({'ok': 1, 'msg': 'IP已添加到黑名单'})

# 从黑名单移除IP
@app.route('/admin/remove_ip_blacklist', methods=['POST'])
def admin_remove_ip_blacklist():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    blacklist_id = data.get('id')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # 获取IP地址用于日志记录
    c.execute('SELECT ip_address FROM ip_blacklist WHERE id = ?', (blacklist_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'ok': 0, 'msg': '记录不存在'})
    
    ip = row[0]
    
    c.execute('DELETE FROM ip_blacklist WHERE id = ?', (blacklist_id,))
    conn.commit()
    conn.close()
    
    log_operation(uid, 'remove_ip_blacklist', ip, '解除IP封禁')
    
    return jsonify({'ok': 1, 'msg': 'IP已从黑名单移除'})

# 获取登录尝试记录
@app.route('/admin/get_login_attempts', methods=['POST'])
def admin_get_login_attempts():
    uid = session.get("user")
    role = get_user_role(uid)
    if role not in (ROLE_ADMIN, ROLE_SUPER_ADMIN):
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id, username, ip_address, success, created_at, lock_until FROM login_attempts ORDER BY created_at DESC LIMIT 100')
    rows = c.fetchall()
    conn.close()
    
    attempts = []
    for row in rows:
        attempts.append({
            'id': row[0],
            'username': row[1],
            'ip_address': row[2],
            'success': row[3] == 1,
            'created_at': row[4],
            'lock_until': row[5]
        })
    
    return jsonify({'ok': 1, 'attempts': attempts})

# 获取当前用户信息（包含昵称）
@app.route('/user/info', methods=['POST'])
def get_user_info():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT uid, nickname, email FROM users WHERE id = ?', (uid,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({'ok': 0, 'msg': '用户不存在'})
    
    return jsonify({
        'ok': 1,
        'user_id': uid,
        'uid': row[0],
        'nickname': row[1],
        'email': row[2]
    })

# 用户修改昵称
@app.route('/user/update_nickname', methods=['POST'])
def update_nickname():
    uid = session.get("user")
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    data = request.json or {}
    new_nickname = data.get('nickname', '').strip()
    
    if not new_nickname:
        return jsonify({'ok': 0, 'msg': '请输入新昵称'})
    
    if len(new_nickname) < 2 or len(new_nickname) > 20:
        return jsonify({'ok': 0, 'msg': '昵称需在2-20个字符之间'})
    
    # 审核昵称
    is_valid, error_msg = validate_nickname(new_nickname)
    if not is_valid:
        return jsonify({'ok': 0, 'msg': error_msg})
    
    new_nickname = sanitize_input(new_nickname, 20)
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('UPDATE users SET nickname = ? WHERE id = ?', (new_nickname, uid))
    conn.commit()
    conn.close()
    
    log_operation(uid, 'update_nickname', uid, f'用户修改昵称为: {new_nickname}')
    return jsonify({'ok': 1, 'msg': '昵称修改成功'})

# 根据用户ID获取昵称（用于展示）
@app.route('/user/get_nickname', methods=['POST'])
def get_nickname():
    data = request.json or {}
    user_id = data.get('user_id', '').strip()
    
    if not user_id:
        return jsonify({'ok': 0, 'msg': '缺少参数'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT nickname FROM users WHERE id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({'ok': 0, 'msg': '用户不存在'})
    
    return jsonify({'ok': 1, 'nickname': row[0]})

# ===================== 数据管理API =====================

# 数据库备份
@app.route('/admin/data/backup', methods=['POST'])
def backup_database():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    try:
        # 创建备份目录
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # 生成备份文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'database_{timestamp}.db')
        
        # 复制数据库文件
        shutil.copy('database.db', backup_path)
        
        log_operation(uid, 'backup_database', '', f'数据库备份成功: {backup_path}')
        return jsonify({'ok': 1, 'msg': f'备份成功！备份文件: {backup_path}', 'file': backup_path})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'备份失败: {str(e)}'})

# 数据库恢复
@app.route('/admin/data/restore', methods=['POST'])
def restore_database():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_SUPER_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足（需要最高管理员）'})
    
    data = request.json or {}
    backup_file = data.get('file', '').strip()
    
    if not backup_file:
        return jsonify({'ok': 0, 'msg': '请选择备份文件'})
    
    backup_path = os.path.join('backups', backup_file)
    if not os.path.exists(backup_path):
        return jsonify({'ok': 0, 'msg': '备份文件不存在'})
    
    try:
        # 先创建当前数据库的备份作为安全措施
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy('database.db', f'backups/restore_backup_{timestamp}.db')
        
        # 恢复数据库
        shutil.copy(backup_path, 'database.db')
        
        log_operation(uid, 'restore_database', '', f'数据库恢复成功: {backup_file}')
        return jsonify({'ok': 1, 'msg': f'恢复成功！已从 {backup_file} 恢复数据库'})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'恢复失败: {str(e)}'})

# 获取备份文件列表
@app.route('/admin/data/backup_list', methods=['POST'])
def get_backup_list():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    backup_dir = 'backups'
    if not os.path.exists(backup_dir):
        return jsonify({'ok': 1, 'list': []})
    
    try:
        files = []
        for f in os.listdir(backup_dir):
            if f.startswith('database_') and f.endswith('.db'):
                filepath = os.path.join(backup_dir, f)
                stat = os.stat(filepath)
                files.append({
                    'name': f,
                    'size': stat.st_size,
                    'time': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
        files.sort(key=lambda x: x['time'], reverse=True)
        return jsonify({'ok': 1, 'list': files})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'获取备份列表失败: {str(e)}'})

# 删除备份文件
@app.route('/admin/data/delete_backup', methods=['POST'])
def delete_backup():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.json or {}
    filename = data.get('filename', '').strip()
    
    if not filename:
        return jsonify({'ok': 0, 'msg': '请指定文件名'})
    
    backup_path = os.path.join('backups', filename)
    if not os.path.exists(backup_path):
        return jsonify({'ok': 0, 'msg': '文件不存在'})
    
    try:
        os.remove(backup_path)
        log_operation(uid, 'delete_backup', '', f'删除备份文件: {filename}')
        return jsonify({'ok': 1, 'msg': f'删除成功'})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'删除失败: {str(e)}'})

# 导出用户数据为CSV
@app.route('/admin/data/export_users', methods=['POST'])
def export_users():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('SELECT id, uid, nickname, email, verified, role, created_at FROM users')
        rows = c.fetchall()
        conn.close()
        
        # 创建CSV内容
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['用户ID', '数字ID', '昵称', '邮箱', '是否验证', '角色', '注册时间'])
        
        role_map = {0: '普通用户', 1: '档主', 2: '信用档主', 3: '管理员', 4: '最高管理员'}
        
        for row in rows:
            writer.writerow([
                row[0], row[1], row[2], row[3], 
                '已验证' if row[4] else '未验证',
                role_map.get(row[5], '未知'),
                row[6]
            ])
        
        # 返回下载
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'users_{timestamp}.csv'
        
        log_operation(uid, 'export_users', '', f'导出用户数据: {filename}')
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            download_name=filename,
            as_attachment=True
        )
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'导出失败: {str(e)}'})

# 导出档期数据为CSV
@app.route('/admin/data/export_schedules', methods=['POST'])
def export_schedules():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''SELECT id, date, time_start, time_end, server_name, 
                          server_ip, max_players, description, tags, op_id, 
                          status, created_at FROM schedules''')
        rows = c.fetchall()
        conn.close()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['档期ID', '日期', '开始时间', '结束时间', '服务器名称', 
                        '服务器IP', '最大人数', '描述', '标签', '档主ID', '状态', '创建时间'])
        
        status_map = {0: '待审核', 1: '已通过', 2: '已取消', 3: '已结束'}
        
        for row in rows:
            writer.writerow([
                row[0], row[1], row[2], row[3], row[4], row[5],
                row[6], row[7], row[8], row[9],
                status_map.get(row[10], '未知'),
                row[11]
            ])
        
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'schedules_{timestamp}.csv'
        
        log_operation(uid, 'export_schedules', '', f'导出档期数据: {filename}')
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            download_name=filename,
            as_attachment=True
        )
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'导出失败: {str(e)}'})

# 检查更新
@app.route('/admin/check_update', methods=['POST'])
def check_update():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_SUPER_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足（仅最高管理员可用）'})
    
    try:
        import os
        
        # 从配置获取远程仓库地址和代理配置
        remote_repo_url = app.config.get('REMOTE_REPO_URL', 'https://github.com/WEIWU-001/MC-Schedule.git')
        default_branch = app.config.get('DEFAULT_BRANCH', 'master')
        http_proxy = app.config.get('HTTP_PROXY', '')
        https_proxy = app.config.get('HTTPS_PROXY', '')
        
        # 设置代理环境变量
        if http_proxy:
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy
        if https_proxy:
            os.environ['HTTPS_PROXY'] = https_proxy
            os.environ['https_proxy'] = https_proxy
        
        # 获取当前版本（从git）
        try:
            with os.popen('git rev-parse HEAD') as f:
                current_commit = f.read().strip()
            with os.popen('git branch --show-current') as f:
                current_branch = f.read().strip()
            if not current_branch:
                current_branch = default_branch
        except:
            current_commit = '未知'
            current_branch = default_branch
        
        # 检查远程仓库更新（优化版：使用 ls-remote 避免下载整个仓库）
        try:
            # 检查远程仓库是否已配置
            with os.popen('git remote get-url origin') as f:
                current_remote = f.read().strip()
            
            # 如果远程仓库地址不对，更新它
            if current_remote != remote_repo_url:
                os.system('git remote remove origin >nul 2>&1')
                os.system(f'git remote add origin {remote_repo_url} >nul 2>&1')
            
            # 配置git代理（临时生效）
            if http_proxy or https_proxy:
                proxy_url = https_proxy if https_proxy else http_proxy
                os.system(f'git config --global http.proxy {proxy_url} >nul 2>&1')
                os.system(f'git config --global https.proxy {proxy_url} >nul 2>&1')
            
            # 使用 ls-remote 获取远程分支最新commit（比 fetch 快很多）
            # 添加超时设置（Windows git Bash 语法）
            import threading
            
            result_container = [None]
            error_occurred = [False]
            
            def fetch_remote():
                try:
                    with os.popen(f'git ls-remote --heads origin {current_branch}') as f:
                        result_container[0] = f.read().strip()
                except:
                    error_occurred[0] = True
            
            # 启动后台线程获取远程信息
            fetch_thread = threading.Thread(target=fetch_remote)
            fetch_thread.daemon = True
            fetch_thread.start()
            fetch_thread.join(timeout=10)  # 最多等待10秒
            
            remote_line = result_container[0]
            
            # 如果超时或失败，返回友好提示
            if error_occurred[0] or not remote_line:
                return jsonify({
                    'ok': 0,
                    'msg': '连接GitHub超时，请检查网络或配置代理'
                })
            
            # git ls-remote 返回格式: <commit> <refs/heads/branch>
            remote_commit = remote_line.split()[0]  # 获取commit部分
            
            # 如果远程commit为空，说明无法连接到远程仓库
            if not remote_commit:
                return jsonify({
                    'ok': 0,
                    'msg': '无法获取远程版本，请检查网络连接'
                })
            
            has_update = current_commit != remote_commit
            
            # 获取更新日志（只在有更新时才获取）
            update_log = []
            if has_update:
                with os.popen(f'git log --oneline {current_commit}..origin/{current_branch} -n 10') as f:
                    log_output = f.read().strip()
                update_log = log_output.split('\n') if log_output else []
        except Exception as e:
            return jsonify({'ok': 0, 'msg': f'检查更新失败: {str(e)}'})
        
        return jsonify({
            'ok': 1,
            'data': {
                'current_version': current_commit[:7] if current_commit and current_commit != '未知' else '未知',
                'current_branch': current_branch,
                'has_update': has_update,
                'latest_version': remote_commit[:7] if remote_commit else '未知',
                'update_log': update_log
            }
        })
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'检查更新失败: {str(e)}'})

# 执行更新
@app.route('/admin/do_update', methods=['POST'])
def do_update():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_SUPER_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足（仅最高管理员可用）'})
    
    try:
        import os
        
        # 从配置获取远程仓库地址和代理配置
        remote_repo_url = app.config.get('REMOTE_REPO_URL', 'https://github.com/WEIWU-001/MC-Schedule.git')
        default_branch = app.config.get('DEFAULT_BRANCH', 'master')
        http_proxy = app.config.get('HTTP_PROXY', '')
        https_proxy = app.config.get('HTTPS_PROXY', '')
        
        # 设置代理环境变量
        if http_proxy:
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy
        if https_proxy:
            os.environ['HTTPS_PROXY'] = https_proxy
            os.environ['https_proxy'] = https_proxy
        
        # 配置git代理（临时生效）
        if http_proxy or https_proxy:
            proxy_url = https_proxy if https_proxy else http_proxy
            os.system(f'git config --global http.proxy {proxy_url} >nul 2>&1')
            os.system(f'git config --global https.proxy {proxy_url} >nul 2>&1')
        
        # 更新远程仓库地址并拉取最新代码
        os.system('git remote remove origin >nul 2>&1')
        os.system(f'git remote add origin {remote_repo_url} >nul 2>&1')
        exit_code = os.system(f'git pull origin {default_branch} >git_pull_output.txt 2>&1')
        
        with open('git_pull_output.txt', 'r', encoding='utf-8', errors='ignore') as f:
            output = f.read()
        
        if exit_code == 0:
            # 获取更新后的版本
            with os.popen('git rev-parse HEAD') as f:
                current_commit = f.read().strip()
            
            return jsonify({
                'ok': 1,
                'msg': '更新成功！请重启服务器以应用更改',
                'new_version': current_commit[:7],
                'output': output
            })
        else:
            return jsonify({
                'ok': 0,
                'msg': f'更新失败: {output}'
            })
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'更新失败: {str(e)}'})

# 获取统计数据
@app.route('/admin/data/stats', methods=['POST'])
def get_data_stats():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # 用户统计
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM users WHERE role >= 1')
        total_ops = c.fetchone()[0]
        
        # 档期统计
        c.execute('SELECT COUNT(*) FROM schedules')
        total_schedules = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM schedules WHERE status = 1')
        active_schedules = c.fetchone()[0]
        
        # 预约统计
        c.execute('SELECT COUNT(*) FROM reservations')
        total_reservations = c.fetchone()[0]
        
        # 评论统计
        c.execute('SELECT COUNT(*) FROM comments')
        total_comments = c.fetchone()[0]
        
        # 按日期统计用户增长（最近30天）
        user_growth = []
        for i in range(29, -1, -1):
            date_str = (date.today() - timedelta(days=i)).strftime('%Y-%m-%d')
            c.execute("SELECT COUNT(*) FROM users WHERE created_at LIKE ?", (date_str + '%',))
            count = c.fetchone()[0]
            user_growth.append({'date': date_str, 'count': count})
        
        # 按日期统计档期发布（最近30天）
        schedule_growth = []
        for i in range(29, -1, -1):
            date_str = (date.today() - timedelta(days=i)).strftime('%Y-%m-%d')
            c.execute("SELECT COUNT(*) FROM schedules WHERE created_at LIKE ?", (date_str + '%',))
            count = c.fetchone()[0]
            schedule_growth.append({'date': date_str, 'count': count})
        
        # 按状态统计档期分布
        c.execute('SELECT status, COUNT(*) FROM schedules GROUP BY status')
        schedule_status = []
        status_map = {0: '待审核', 1: '已通过', 2: '已取消', 3: '已结束'}
        for row in c.fetchall():
            schedule_status.append({'status': status_map.get(row[0], '未知'), 'count': row[1]})
        
        conn.close()
        
        return jsonify({
            'ok': 1,
            'data': {
                'total_users': total_users,
                'total_ops': total_ops,
                'total_schedules': total_schedules,
                'active_schedules': active_schedules,
                'total_reservations': total_reservations,
                'total_comments': total_comments,
                'user_growth': user_growth,
                'schedule_growth': schedule_growth,
                'schedule_status': schedule_status
            }
        })
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'获取统计数据失败: {str(e)}'})

# ========== 用户反馈功能 ==========
@app.route('/feedback/submit', methods=['POST'])
def submit_feedback():
    data = request.get_json()
    user_id = session.get('user')
    
    if not data or not data.get('content'):
        return jsonify({'ok': 0, 'msg': '请填写反馈内容'})
    
    content = data.get('content').strip()
    feedback_type = data.get('type', 'suggestion')
    email = data.get('email', '')
    
    if len(content) < 10:
        return jsonify({'ok': 0, 'msg': '反馈内容至少需要10个字符'})
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        if user_id:
            c.execute('SELECT nickname FROM users WHERE id = ?', (user_id,))
            row = c.fetchone()
            nickname = row[0] if row else '匿名用户'
        else:
            nickname = data.get('nickname', '匿名用户')
            user_id = None
        
        c.execute('''INSERT INTO feedback (user_id, nickname, email, type, content)
                      VALUES (?, ?, ?, ?, ?)''', 
                  (user_id, nickname, email, feedback_type, content))
        
        conn.commit()
        conn.close()
        
        return jsonify({'ok': 1, 'msg': '反馈提交成功！感谢您的意见和建议。'})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'提交失败: {str(e)}'})

@app.route('/admin/feedback/list', methods=['POST'])
def get_feedback_list():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        c.execute('SELECT * FROM feedback ORDER BY created_at DESC')
        feedbacks = []
        for row in c.fetchall():
            feedbacks.append({
                'id': row[0],
                'user_id': row[1],
                'nickname': row[2],
                'email': row[3],
                'type': row[4],
                'content': row[5],
                'status': row[6],
                'created_at': row[7]
            })
        
        conn.close()
        
        return jsonify({'ok': 1, 'data': feedbacks})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'获取反馈列表失败: {str(e)}'})

@app.route('/admin/feedback/handle', methods=['POST'])
def handle_feedback():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.get_json()
    feedback_id = data.get('id')
    status = data.get('status', 1)
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        c.execute('UPDATE feedback SET status = ? WHERE id = ?', (status, feedback_id))
        conn.commit()
        conn.close()
        
        log_operation(uid, 'handle_feedback', str(feedback_id), f'反馈ID {feedback_id} 状态更新为 {status}')
        return jsonify({'ok': 1, 'msg': '操作成功'})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'操作失败: {str(e)}'})

@app.route('/admin/feedback/delete', methods=['POST'])
def delete_feedback():
    uid = session.get('user')
    if not uid:
        return jsonify({'ok': 0, 'msg': '请先登录'})
    
    role = get_user_role(uid)
    if role < ROLE_ADMIN:
        return jsonify({'ok': 0, 'msg': '权限不足'})
    
    data = request.get_json()
    feedback_id = data.get('id')
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        c.execute('DELETE FROM feedback WHERE id = ?', (feedback_id,))
        conn.commit()
        conn.close()
        
        log_operation(uid, 'delete_feedback', str(feedback_id), f'删除反馈ID {feedback_id}')
        return jsonify({'ok': 1, 'msg': '删除成功'})
    except Exception as e:
        return jsonify({'ok': 0, 'msg': f'删除失败: {str(e)}'})

# ==================== 全局错误收集器 ====================
@app.after_request
def collect_errors(response):
    """全局请求钩子 - 收集所有错误并记录到日志"""
    # 只记录4xx和5xx错误
    if response.status_code >= 400:
        # 获取请求信息
        method = request.method
        path = request.path
        ip = request.remote_addr
        status = response.status_code
        
        # 尝试获取响应内容
        try:
            response_data = response.get_json()
            if response_data:
                error_msg = response_data.get('msg', str(response_data))
            else:
                error_msg = response.data.decode('utf-8', errors='ignore')[:200] if response.data else 'No content'
        except:
            error_msg = 'Unable to parse response'
        
        # 记录到日志
        logger.error(f"[错误收集] {method} {path} | 状态:{status} | IP:{ip} | 错误:{error_msg}")
        
        # 如果是API请求且有session，也记录uid
        if 'uid' in session:
            logger.error(f"[错误收集] 用户: {session.get('uid', 'unknown')}")
    
    return response

# ==================== 错误处理器 ====================
@app.errorhandler(404)
def error_404(e):
    """404 页面未找到"""
    if request.path.startswith('/') and (request.is_json or (request.content_type and 'application/json' in request.content_type)):
        return jsonify({'ok': 0, 'msg': 'API端点不存在'}), 404
    return render_template('error.html', code=404, message=str(e), site_title=get_site_title()), 404

@app.errorhandler(400)
def error_400(e):
    """400 错误请求"""
    if request.path.startswith('/') and (request.is_json or (request.content_type and 'application/json' in request.content_type)):
        return jsonify({'ok': 0, 'msg': '请求参数错误'}), 400
    return render_template('error.html', code=400, message=str(e), site_title=get_site_title()), 400

@app.errorhandler(403)
def error_403(e):
    """403 访问被拒绝"""
    if request.path.startswith('/') and (request.is_json or (request.content_type and 'application/json' in request.content_type)):
        return jsonify({'ok': 0, 'msg': '访问被拒绝'}), 403
    return render_template('error.html', code=403, message=str(e), site_title=get_site_title()), 403

@app.errorhandler(500)
def error_500(e):
    """500 服务器错误"""
    logger.error(f"500 服务器错误: {e}", exc_info=True)
    if request.path.startswith('/') and (request.is_json or (request.content_type and 'application/json' in request.content_type)):
        return jsonify({'ok': 0, 'msg': '服务器内部错误'}), 500
    return render_template('error.html', code=500, message="服务器发生内部错误", site_title=get_site_title()), 500

@app.errorhandler(429)
def error_429(e):
    """429 请求过于频繁"""
    if request.path.startswith('/') and (request.is_json or (request.content_type and 'application/json' in request.content_type)):
        return jsonify({'ok': 0, 'msg': str(e)}), 429
    return render_template('error.html', code=429, message=str(e), site_title=get_site_title()), 429

if __name__ == '__main__':
    # 恢复已有预约的提醒任务
    restore_reservation_jobs()
    
    print("[提醒服务] 已启动，使用 APScheduler 准时提醒")
    
    app.run(host='0.0.0.0', port=5000, debug=False)