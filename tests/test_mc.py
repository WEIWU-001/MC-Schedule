import socket
import time
import struct
import json

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

def query_mc_server(host, port=25565):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        start_time = time.time()
        result = sock.connect_ex((host, port))
        latency = int((time.time() - start_time) * 1000)
        
        if result != 0:
            sock.close()
            return {'ok': 0, 'msg': '服务器离线或无法连接'}
        
        protocol_version = 754
        server_address = host.encode('utf-8')
        
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
                return {
                    'ok': 1,
                    'version': version,
                    'motd': motd[:100] if motd else '服务器在线',
                    'players_online': players_online,
                    'players_max': players_max,
                    'latency': latency,
                    'query_time': time.strftime('%Y-%m-%d %H:%M:%S')
                }
            except Exception as e:
                print(f"现代协议解析失败: {e}")
        
        sock.close()
        
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock2.settimeout(3)
        try:
            sock2.connect((host, port))
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
                        return {
                            'ok': 1,
                            'version': version,
                            'motd': motd[:100],
                            'players_online': players_online,
                            'players_max': players_max,
                            'latency': latency,
                            'query_time': time.strftime('%Y-%m-%d %H:%M:%S')
                        }
        except Exception as e:
            print(f"旧版协议解析失败: {e}")
        finally:
            sock2.close()
        
        return {
            'ok': 1,
            'version': '未知',
            'motd': '服务器在线',
            'players_online': '0',
            'players_max': '0',
            'latency': latency,
            'query_time': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
    except socket.timeout:
        return {'ok': 0, 'msg': '连接超时'}
    except socket.gaierror:
        return {'ok': 0, 'msg': '无法解析服务器地址'}
    except Exception as e:
        return {'ok': 0, 'msg': f'查询失败: {str(e)}'}

if __name__ == '__main__':
    print("测试 b1.getmc.cn:30005")
    result = query_mc_server('b1.getmc.cn', 30005)
    print(json.dumps(result, ensure_ascii=False))
    print()
    
    print("测试 mc.hypixel.net")
    result = query_mc_server('mc.hypixel.net')
    print(json.dumps(result, ensure_ascii=False))