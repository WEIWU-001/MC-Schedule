from flask import Flask
from flask_mail import Mail, Message
import sys
import io

# 设置输出编码为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

app = Flask(__name__)

# 主邮箱配置
main_email = {
    'username': 'weiwu@wwdjia.work',
    'password': 'x51TIgoF7zJGLOtZ',
    'smtp_server': 'smtp.qiye.aliyun.com',
    'smtp_port': 465,
    'name': '主邮箱'
}

print(f"\n{'='*60}")
print(f"正在测试 {main_email['name']} ({main_email['username']})...")
print(f"{'='*60}")

try:
    # 配置Flask-Mail
    app.config['MAIL_SERVER'] = main_email['smtp_server']
    app.config['MAIL_PORT'] = main_email['smtp_port']
    app.config['MAIL_USERNAME'] = main_email['username']
    app.config['MAIL_PASSWORD'] = main_email['password']
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_USE_SSL'] = True
    
    mail = Mail(app)
    
    # 使用应用上下文
    with app.app_context():
        # 创建测试邮件
        msg = Message(
            subject='【测试邮件】邮箱池配置验证',
            sender=main_email['username'],
            recipients=[main_email['username']]
        )
        msg.body = f'这是一封测试邮件，用于验证 {main_email["name"]} 配置是否正确。\n\n如果收到此邮件，说明邮箱配置成功！'
        
        # 发送邮件
        mail.send(msg)
        print(f"[OK] {main_email['name']} 测试成功！邮件已发送到 {main_email['username']}")
    
except Exception as e:
    print(f"[FAIL] {main_email['name']} 测试失败！")
    print(f"错误信息: {str(e)}")
    import traceback
    traceback.print_exc()

print(f"{'='*60}\n")
