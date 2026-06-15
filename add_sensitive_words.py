#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接添加敏感词到现有数据库"""

import sqlite3
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

conn = sqlite3.connect('database.db')
c = conn.cursor()

# 从文件加载敏感词
if os.path.exists('sensitive_words.txt'):
    with open('sensitive_words.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    added = 0
    for line in lines:
        word = line.strip()
        if word and not word.startswith('#'):
            try:
                c.execute("INSERT OR IGNORE INTO keywords (word) VALUES (?)", (word,))
                if c.rowcount > 0:
                    added += 1
            except Exception as e:
                print(f"  跳过: {word} - {e}")
    
    conn.commit()
    print(f"成功添加 {added} 个敏感词！")
    
    # 显示所有敏感词
    print("\n当前数据库中的敏感词：")
    c.execute("SELECT id, word FROM keywords ORDER BY id")
    for row in c.fetchall():
        print(f"  {row[0]}. {row[1]}")
else:
    print("未找到 sensitive_words.txt 文件！")

conn.close()

print("\n完成！请重启服务器，然后在后台查看敏感词管理功能。")
