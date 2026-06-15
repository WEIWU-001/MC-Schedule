import requests
import json

# 测试本地服务器
base_url = "http://127.0.0.1:5000"

# 先登录获取 session
login_data = {
    "username": "weiwu001",
    "password": "K9s&pR7!vG2@mB5#"
}

session = requests.Session()

# 尝试登录
try:
    login_response = session.post(f"{base_url}/admin_login", data=login_data)
    print(f"登录响应: {login_response.status_code}")
    print(f"登录内容: {login_response.text[:500]}")
except Exception as e:
    print(f"登录失败: {e}")
    exit()

# 测试关键词 API
print("\n=== 测试关键词 API ===")
try:
    headers = {"Content-Type": "application/json"}
    response = session.post(f"{base_url}/admin/keywords/get", headers=headers)
    print(f"关键词 API 响应: {response.status_code}")
    print(f"响应内容: {response.text}")
except Exception as e:
    print(f"关键词 API 失败: {e}")

# 测试违规记录 API（这个应该成功）
print("\n=== 测试违规记录 API ===")
try:
    headers = {"Content-Type": "application/json"}
    response = session.post(f"{base_url}/admin/violations", headers=headers)
    print(f"违规记录 API 响应: {response.status_code}")
    print(f"响应内容: {response.text[:500]}")
except Exception as e:
    print(f"违规记录 API 失败: {e}")

# 测试系统配置 API
print("\n=== 测试系统配置 API ===")
try:
    headers = {"Content-Type": "application/json"}
    response = session.post(f"{base_url}/admin/get_system_config", headers=headers)
    print(f"系统配置 API 响应: {response.status_code}")
    print(f"响应内容: {response.text}")
except Exception as e:
    print(f"系统配置 API 失败: {e}")
