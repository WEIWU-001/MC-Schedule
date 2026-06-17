# 网站配置 - 使用环境变量存储敏感信息
import os
from dotenv import load_dotenv
import secrets

# 加载 .env 文件
load_dotenv()

# ==================== 安全配置 ====================
# Flask 密钥（用于 session 加密等）
# 生成一个安全的随机密钥，长度为64字符
SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ==================== 超级管理员配置 ====================
# 自动创建此账号，如已存在则自动升级权限
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Admin@2024!')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')

# 最高管理员ID配置 - 玩家注册时使用此ID将自动成为最高管理员
SUPER_ADMIN_ID = os.environ.get('SUPER_ADMIN_ID', '惟五')

# ==================== 网站配置 ====================
SITE_DOMAIN = os.environ.get('SITE_DOMAIN', 'http://127.0.0.1:5000')

# ==================== 邮箱池配置 ====================
# 邮箱池配置从环境变量读取，格式：
# EMAIL_1_NAME, EMAIL_1_USERNAME, EMAIL_1_PASSWORD, EMAIL_1_SMTP_SERVER, EMAIL_1_SMTP_PORT, EMAIL_1_MAX_DAILY
# EMAIL_2_NAME, EMAIL_2_USERNAME, EMAIL_2_PASSWORD, EMAIL_2_SMTP_SERVER, EMAIL_2_SMTP_PORT, EMAIL_2_MAX_DAILY

def load_email_pool():
    """从环境变量加载邮箱池配置"""
    email_pool = []
    index = 1
    while True:
        name = os.environ.get(f'EMAIL_{index}_NAME')
        if not name:
            break
        email_pool.append({
            'name': name,
            'username': os.environ.get(f'EMAIL_{index}_USERNAME', ''),
            'password': os.environ.get(f'EMAIL_{index}_PASSWORD', ''),
            'smtp_server': os.environ.get(f'EMAIL_{index}_SMTP_SERVER', ''),
            'smtp_port': int(os.environ.get(f'EMAIL_{index}_SMTP_PORT', '465')),
            'max_daily': int(os.environ.get(f'EMAIL_{index}_MAX_DAILY', '500'))
        })
        index += 1
    
    # 如果没有配置邮箱池，返回空列表
    return email_pool

EMAIL_POOL = load_email_pool()

# ==================== 腾讯云内容审核 (TMS) 配置 ====================
TENCENT_SECRET_ID = os.environ.get('TENCENT_SECRET_ID', '')
TENCENT_SECRET_KEY = os.environ.get('TENCENT_SECRET_KEY', '')
TMS_FREE_LIMIT = int(os.environ.get('TMS_FREE_LIMIT', '3000'))

# ==================== 系统更新配置 ====================
# 远程仓库地址（用于系统更新功能）
REMOTE_REPO_URL = os.environ.get('REMOTE_REPO_URL', 'https://github.com/WEIWU-001/MC-Schedule.git')
# 默认分支
DEFAULT_BRANCH = os.environ.get('DEFAULT_BRANCH', 'main')

# ==================== 文件上传配置 ====================
# 最大上传文件大小（15MB），考虑Base64编码会增加约33%的大小
MAX_CONTENT_LENGTH = 15 * 1024 * 1024
