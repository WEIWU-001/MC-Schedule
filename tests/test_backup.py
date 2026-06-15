from flask import Flask
from flask_mail import Mail, Message
import sys
import io

# 设置输出编码为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

app = Flask(__name__)

# 测试副邮箱配置
backup_email = {
    'username': 'mcqs@wwdjia.top',
    'password': 'fFNpB6jTqyWyV2YY',
    'smtp_server': 'smtp.exmail.qq.com',
    'smtp_port': 465,
    'name': '副邮箱'
}

print(f"\n{'='*60}")
print(f"正在测试 {backup_email['name']} ({backup_email['username']})...")
print(f"{'='*60}")

try:
    # 配置Flask-Mail
    app.config['MAIL_SERVER'] = backup_email['smtp_server']
    app.config['MAIL_PORT'] = backup_email['smtp_port']
    app.config['MAIL_USERNAME'] = backup_email['username']
    app.config['MAIL_PASSWORD'] = backup_email['password']
    app.config['MAIL_USE_TLS'] = False
    app.config['MAIL_USE_SSL'] = True
    
    mail = Mail(app)
    
    # 使用应用上下文
    with app.app_context():
        # 创建测试邮件
        msg = Message(
            subject='【测试邮件】邮箱池配置验证',
            sender=backup_email['username'],
            recipients=[backup_email['username']]
        )
        msg.body = f'这是一封测试邮件，用于验证 {backup_email["name"]} 配置是否正确。\n\n如果收到此邮件，说明邮箱配置成功！'
        
        # 发送邮件
        mail.send(msg)
        print(f"[OK] {backup_email['name']} 测试成功！邮件已发送到 {backup_email['username']}")
    
except Exception as e:
    print(f"[FAIL] {backup_email['name']} 测试失败！")
    print(f"错误信息: {str(e)}")
    import traceback
    traceback.print_exc()

print(f"{'='*60}\n")
