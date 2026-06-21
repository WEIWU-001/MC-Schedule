# -*- coding: utf-8 -*-
"""
MC-Schedule 更新器模块
使用 GitHub/Gitee Releases API 检查和执行更新
"""

import os
import shutil
import zipfile
import tempfile
import logging
import json
import urllib.request
import urllib.error
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """版本信息"""
    current_version: str
    latest_version: str
    has_update: bool
    update_log: List[str]
    used_source: Optional[str]
    release_url: Optional[str] = None
    download_url: Optional[str] = None


@dataclass
class UpdateResult:
    """更新结果"""
    success: bool
    message: str
    new_version: Optional[str] = None
    used_source: Optional[str] = None
    updated_files: Optional[List[str]] = None
    update_method: Optional[str] = None


@dataclass
class SourceStatus:
    """源状态"""
    id: str
    name: str
    available: bool
    latency: int
    error: Optional[str] = None


class Updater:
    """更新器核心类 - 使用 Releases API"""
    
    # 排除的目录和文件
    EXCLUDE_DIRS = {'logs', 'database.db', '__pycache__', '.git', 'node_modules', 'update_temp', '.venv', 'venv', 'env'}
    EXCLUDE_FILES = {'.env', '.production_mode', '.secret_key', '.env.example'}
    
    # API URLs
    GITHUB_API = "https://api.github.com/repos/WEIWU-001/MC-Schedule/releases/latest"
    GITEE_API = "https://gitee.com/api/v5/repos/weiwu001/MC-Schedule/releases/latest"
    
    # 下载 URLs
    GITHUB_DOWNLOAD = "https://github.com/WEIWU-001/MC-Schedule/archive/refs/tags/{version}.zip"
    GITEE_DOWNLOAD = "https://gitee.com/weiwu001/MC-Schedule/repository/archive/{version}.zip"
    
    def __init__(self, project_root: str, timeout: int = 30):
        """
        初始化更新器
        
        Args:
            project_root: 项目根目录
            timeout: 请求超时时间（秒）
        """
        self.project_root = project_root
        self.timeout = timeout
        self.current_version = self._get_current_version()
    
    def _get_current_version(self) -> str:
        """获取当前版本"""
        version_file = os.path.join(self.project_root, 'VERSION')
        if os.path.exists(version_file):
            with open(version_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return 'v0.0.0'
    
    def _fetch_url(self, url: str, headers: dict = None) -> tuple:
        """
        获取URL内容
        
        Returns:
            (success, data_or_error)
        """
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MC-Schedule-Updater/1.0')
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode('utf-8')
                return True, data
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}"
        except urllib.error.URLError as e:
            return False, str(e.reason)
        except Exception as e:
            return False, str(e)
    
    def _download_file(self, url: str, save_path: str) -> tuple:
        """
        下载文件
        
        Returns:
            (success, error_message)
        """
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MC-Schedule-Updater/1.0')
            
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(save_path, 'wb') as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            return True, None
        except Exception as e:
            return False, str(e)
    
    def _compare_versions(self, v1: str, v2: str) -> int:
        """
        比较版本号
        
        Returns:
            -1: v1 < v2
             0: v1 == v2
             1: v1 > v2
        """
        def parse(v):
            parts = v.lstrip('v').split('.')
            return [int(p) for p in parts] if len(parts) == 3 else [0, 0, 0]
        
        p1, p2 = parse(v1), parse(v2)
        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
        return 0
    
    def test_sources(self) -> List[SourceStatus]:
        """测试所有更新源可用性"""
        import time
        
        results = []
        
        # 测试 GitHub
        start = time.time()
        success, _ = self._fetch_url(self.GITHUB_API)
        latency = int((time.time() - start) * 1000)
        results.append(SourceStatus(
            id='github',
            name='GitHub（直连）',
            available=success,
            latency=latency,
            error=None if success else _
        ))
        
        # 测试 Gitee
        start = time.time()
        success, _ = self._fetch_url(self.GITEE_API)
        latency = int((time.time() - start) * 1000)
        results.append(SourceStatus(
            id='gitee',
            name='Gitee（直连）',
            available=success,
            latency=latency,
            error=None if success else _
        ))
        
        return results
    
    def check_update(self, source_id: str = 'auto') -> VersionInfo:
        """
        检查更新
        
        Args:
            source_id: 'auto', 'github', 'gitee'
        
        Returns:
            VersionInfo 对象
        """
        update_log = []
        latest_version = None
        used_source = None
        release_url = None
        download_url = None
        
        # 确定尝试顺序
        if source_id == 'gitee':
            sources = [('gitee', self.GITEE_API)]
        elif source_id == 'github':
            sources = [('github', self.GITHUB_API)]
        else:
            # 自动：先尝试 Gitee（国内更快），再 GitHub
            sources = [('gitee', self.GITEE_API), ('github', self.GITHUB_API)]
        
        for source_name, api_url in sources:
            logger.info(f'尝试从 {source_name} 检查更新...')
            success, data = self._fetch_url(api_url)
            
            if success:
                try:
                    release_info = json.loads(data)
                    latest_version = release_info.get('tag_name', '')
                    
                    # 获取发布说明
                    body = release_info.get('body', '')
                    if body:
                        update_log = [line.strip() for line in body.split('\n') if line.strip()][:10]
                    
                    # 获取下载链接
                    release_url = release_info.get('html_url', '')
                    
                    used_source = source_name
                    logger.info(f'从 {source_name} 获取到最新版本: {latest_version}')
                    break
                except json.JSONDecodeError:
                    logger.warning(f'{source_name} 返回数据解析失败')
                    continue
            else:
                logger.warning(f'{source_name} 检查失败: {data}')
                update_log.append(f'{source_name} 检查失败: {data}')
        
        if not latest_version:
            return VersionInfo(
                current_version=self.current_version,
                latest_version='获取失败',
                has_update=False,
                update_log=['无法获取远程版本信息'],
                used_source=None
            )
        
        has_update = self._compare_versions(self.current_version, latest_version) < 0
        
        return VersionInfo(
            current_version=self.current_version,
            latest_version=latest_version,
            has_update=has_update,
            update_log=update_log,
            used_source=used_source,
            release_url=release_url
        )
    
    def do_update(self, source_id: str = 'auto', create_backup: bool = True) -> UpdateResult:
        """
        执行更新
        
        Args:
            source_id: 'auto', 'github', 'gitee'
            create_backup: 是否创建备份
        
        Returns:
            UpdateResult 对象
        """
        # 先检查更新
        version_info = self.check_update(source_id)
        
        if not version_info.has_update:
            return UpdateResult(
                success=False,
                message=f'已是最新版本 {self.current_version}，无需更新',
                used_source=version_info.used_source
            )
        
        if not version_info.latest_version or version_info.latest_version == '获取失败':
            return UpdateResult(
                success=False,
                message='无法获取最新版本信息，请检查网络连接',
                used_source=version_info.used_source
            )
        
        # 创建备份
        backup_path = None
        if create_backup:
            backup_path = self._create_backup()
            if not backup_path:
                return UpdateResult(
                    success=False,
                    message='创建备份失败，取消更新以保护数据'
                )
        
        # 确定下载源
        if source_id == 'gitee' or (source_id == 'auto' and version_info.used_source == 'gitee'):
            download_url = self.GITEE_DOWNLOAD.format(version=version_info.latest_version)
            used_source = 'Gitee'
        else:
            download_url = self.GITHUB_DOWNLOAD.format(version=version_info.latest_version)
            used_source = 'GitHub'
        
        logger.info(f'开始从 {used_source} 下载更新包: {download_url}')
        
        # 下载 ZIP
        temp_dir = tempfile.mkdtemp(prefix='update_download_')
        zip_path = os.path.join(temp_dir, 'update.zip')
        
        success, error = self._download_file(download_url, zip_path)
        
        if not success:
            # 清理
            shutil.rmtree(temp_dir, ignore_errors=True)
            if backup_path:
                shutil.rmtree(backup_path, ignore_errors=True)
            
            return UpdateResult(
                success=False,
                message=f'下载更新包失败: {error}\n\n建议使用"上传更新包"功能手动更新',
                used_source=used_source
            )
        
        # 验证 ZIP
        if not zipfile.is_zipfile(zip_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return UpdateResult(
                success=False,
                message='下载的文件不是有效的ZIP格式',
                used_source=used_source
            )
        
        # 应用更新
        result = self._apply_zip_update(zip_path, version_info.latest_version)
        
        # 清理
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        if result.success:
            # 清理备份
            if backup_path:
                shutil.rmtree(backup_path, ignore_errors=True)
            
            result.used_source = used_source
            result.new_version = version_info.latest_version
        else:
            # 恢复备份
            if backup_path:
                self._restore_backup(backup_path)
        
        return result
    
    def upload_update(self, zip_file, create_backup: bool = True) -> UpdateResult:
        """
        通过上传ZIP包更新
        
        Args:
            zip_file: 上传的ZIP文件对象
            create_backup: 是否创建备份
        
        Returns:
            UpdateResult 对象
        """
        # 创建备份
        backup_path = None
        if create_backup:
            backup_path = self._create_backup()
            if not backup_path:
                return UpdateResult(
                    success=False,
                    message='创建备份失败，取消更新以保护数据'
                )
        
        try:
            # 保存上传的文件
            temp_dir = tempfile.mkdtemp(prefix='update_upload_')
            zip_path = os.path.join(temp_dir, 'update.zip')
            zip_file.save(zip_path)
            
            # 验证ZIP文件
            if not zipfile.is_zipfile(zip_path):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return UpdateResult(
                    success=False,
                    message='无效的ZIP文件',
                    backup_path=backup_path
                )
            
            # 获取版本信息
            new_version = self._extract_version_from_zip(zip_path)
            
            # 应用更新
            result = self._apply_zip_update(zip_path, new_version)
            
            # 清理临时文件
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            if result.success:
                # 清理备份
                if backup_path:
                    shutil.rmtree(backup_path, ignore_errors=True)
                result.update_method = 'zip_upload'
            else:
                # 恢复备份
                if backup_path:
                    self._restore_backup(backup_path)
            
            return result
            
        except Exception as e:
            logger.error(f'上传更新失败: {e}')
            return UpdateResult(
                success=False,
                message=f'上传更新失败: {str(e)}',
                backup_path=backup_path
            )
    
    def _create_backup(self) -> Optional[str]:
        """创建备份"""
        try:
            backup_dir = os.path.join(self.project_root, 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            import time
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(backup_dir, f'backup_{timestamp}')
            
            shutil.copytree(self.project_root, backup_path, 
                          ignore=shutil.ignore_patterns(*self.EXCLUDE_DIRS, *self.EXCLUDE_FILES))
            
            logger.info(f'备份创建成功: {backup_path}')
            return backup_path
        except Exception as e:
            logger.error(f'创建备份失败: {e}')
            return None
    
    def _restore_backup(self, backup_path: str) -> bool:
        """恢复备份"""
        try:
            for item in os.listdir(backup_path):
                src = os.path.join(backup_path, item)
                dst = os.path.join(self.project_root, item)
                
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            
            logger.info('备份恢复成功')
            return True
        except Exception as e:
            logger.error(f'恢复备份失败: {e}')
            return False
    
    def _extract_version_from_zip(self, zip_path: str) -> str:
        """从ZIP中提取版本号"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # 查找 VERSION 文件
                for name in zf.namelist():
                    if name.endswith('VERSION'):
                        content = zf.read(name).decode('utf-8').strip()
                        return content
        except:
            pass
        return 'unknown'
    
    def _apply_zip_update(self, zip_path: str, new_version: str) -> UpdateResult:
        """应用ZIP更新"""
        try:
            # 解压
            extract_dir = tempfile.mkdtemp(prefix='update_extract_')
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
            
            # 检查是否有嵌套目录（如 MC-Schedule-master/）
            extracted_items = os.listdir(extract_dir)
            if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
                content_dir = os.path.join(extract_dir, extracted_items[0])
            else:
                content_dir = extract_dir
            
            # 更新文件
            updated_files = []
            for root, dirs, files in os.walk(content_dir):
                # 排除目录
                dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]
                
                for filename in files:
                    if filename in self.EXCLUDE_FILES:
                        continue
                    
                    src_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(src_path, content_dir)
                    dst_path = os.path.join(self.project_root, rel_path)
                    
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    
                    # 复制文件
                    shutil.copy2(src_path, dst_path)
                    updated_files.append(rel_path)
            
            # 清理临时文件
            shutil.rmtree(extract_dir, ignore_errors=True)
            
            logger.info(f'更新成功，共更新 {len(updated_files)} 个文件')
            
            return UpdateResult(
                success=True,
                message=f'更新成功！新版本: {new_version}\n请重启服务器以应用更改',
                new_version=new_version,
                updated_files=updated_files,
                update_method='zip_download'
            )
            
        except Exception as e:
            logger.error(f'应用更新失败: {e}')
            return UpdateResult(
                success=False,
                message=f'应用更新失败: {str(e)}'
            )


def get_updater_from_app(app) -> Updater:
    """从 Flask app 获取更新器实例"""
    project_root = os.path.dirname(os.path.abspath(app.root_path))
    return Updater(project_root)
