import sqlite3
conn = sqlite3.connect('database.db')
c = conn.cursor()
c.execute("SELECT * FROM system_config WHERE key = 'background_image'")
result = c.fetchone()
print('数据库中的背景图片配置:', result)
conn.close()
