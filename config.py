# 网站配置 - 使用环境变量存储敏感信息
import os
from dotenv import load_dotenv
import secrets

# 加载 .env 文件
load_dotenv()

# ==================== 安全配置 ====================
# Flask 密钥（用于 session 加密等）
# 使用固定密钥文件确保session跨重启保持有效
SECRET_KEY_FILE = '.secret_key'

def get_secret_key():
    """获取或生成固定的SECRET_KEY"""
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, 'r') as f:
            return f.read().strip()
    # 生成新密钥并保存
    new_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, 'w') as f:
        f.write(new_key)
    return new_key

SECRET_KEY = os.environ.get('SECRET_KEY', get_secret_key())

# ==================== 环境配置 ====================
# PRODUCTION_MODE: True=生产环境, False=开发环境（默认False）
# 可以通过环境变量或 .production_mode 文件设置
PRODUCTION_MODE_FILE = '.production_mode'

def is_production_mode():
    """检测是否为生产环境"""
    # 1. 先检查环境变量
    if os.environ.get('PRODUCTION_MODE', '').lower() == 'true':
        return True
    # 2. 再检查配置文件
    if os.path.exists(PRODUCTION_MODE_FILE):
        with open(PRODUCTION_MODE_FILE, 'r') as f:
            content = f.read().strip().lower()
            return content == 'true' or content == '1'
    return False

PRODUCTION_MODE = is_production_mode()

# 生产环境强制设置（根据 PRODUCTION_MODE 自动配置）
if PRODUCTION_MODE:
    DEBUG = False
    TESTING = False
else:
    DEBUG = True  # 开发环境默认开启调试
    TESTING = False

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
DEFAULT_BRANCH = os.environ.get('DEFAULT_BRANCH', 'main')

UPDATE_SOURCES = [
    {
        'id': 'github',
        'name': 'GitHub 官方',
        'url': 'https://github.com',
        'type': 'mirror',
        'description': 'GitHub官方源，速度较慢但最稳定'
    },
    {
        'id': 'ghproxy',
        'name': 'GHProxy',
        'url': 'https://ghproxy.com/https://github.com',
        'type': 'mirror',
        'description': 'GitHub镜像代理，国内访问较快'
    },
    {
        'id': 'moeyy',
        'name': 'Moeyy GitHub',
        'url': 'https://github.moeyy.xyz',
        'type': 'mirror',
        'description': 'Moeyy的GitHub镜像，支持文件下载'
    },
    {
        'id': 'fastgit',
        'name': 'FastGit',
        'url': 'https://hub.fastgit.xyz',
        'type': 'mirror',
        'description': 'FastGit镜像，国内速度快'
    },
    {
        'id': 'gitclone',
        'name': 'GitClone',
        'url': 'https://gitclone.com/github.com',
        'type': 'mirror',
        'description': 'GitClone镜像，支持多种协议'
    },
    {
        'id': 'gitee',
        'name': 'Gitee',
        'url': '',
        'type': 'direct',
        'description': 'Gitee仓库（需在REMOTE_REPO_URL配置）'
    }
]

GITHUB_MIRRORS = [src['url'] for src in UPDATE_SOURCES if src['type'] == 'mirror' and src['url']]

# ==================== 网络代理配置 ====================
# 如果服务器无法直接访问GitHub，可配置代理
HTTP_PROXY = os.environ.get('HTTP_PROXY', '')
HTTPS_PROXY = os.environ.get('HTTPS_PROXY', '')

# ==================== 文件上传配置 ====================
# 最大上传文件大小（15MB），考虑Base64编码会增加约33%的大小
MAX_CONTENT_LENGTH = 15 * 1024 * 1024
