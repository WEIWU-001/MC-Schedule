# -*- coding: utf-8 -*-
"""
MC-Schedule 更新器模块
使用 GitHub/Gitee Releases API 检查和执行更新
支持版本列表、版本切换、回滚等功能
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
    current_version: str
    latest_version: str
    has_update: bool
    update_log: List[str]
    used_source: Optional[str]
    release_url: Optional[str] = None
    download_url: Optional[str] = None


@dataclass
class Release:
    tag_name: str
    name: str
    body: str
    published_at: str
    prerelease: bool
    html_url: str
    zipball_url: str


@dataclass
class UpdateResult:
    success: bool
    message: str
    new_version: Optional[str] = None
    used_source: Optional[str] = None
    updated_files: Optional[List[str]] = None
    update_method: Optional[str] = None


@dataclass
class SourceStatus:
    id: str
    name: str
    available: bool
    latency: int
    error: Optional[str] = None


class Updater:
    """更新器核心类 - 使用 Releases API"""
    
    EXCLUDE_DIRS = {'logs', '__pycache__', '.git', 'node_modules', 'update_temp', '.venv', 'venv', 'env', 'backups'}
    EXCLUDE_FILES = {'.env', '.production_mode', '.secret_key', '.env.example', 'database.db'}
    
    GITHUB_API_LATEST = "https://api.github.com/repos/WEIWU-001/MC-Schedule/releases/latest"
    GITEE_API_LATEST = "https://gitee.com/api/v5/repos/weiwu001/MC-Schedule/releases/latest"
    
    GITHUB_API_RELEASES = "https://api.github.com/repos/WEIWU-001/MC-Schedule/releases"
    GITEE_API_RELEASES = "https://gitee.com/api/v5/repos/weiwu001/MC-Schedule/releases"
    
    GITHUB_ZIPBALL = "https://api.github.com/repos/WEIWU-001/MC-Schedule/zipball/{tag}"
    GITEE_ZIPBALL = "https://gitee.com/weiwu001/MC-Schedule/repository/archive/{tag}.zip"
    
    def __init__(self, project_root: str, timeout: int = 30):
        self.project_root = project_root
        self.timeout = timeout
        self.current_version = self._get_current_version()
    
    def _get_current_version(self) -> str:
        version_file = os.path.join(self.project_root, 'VERSION')
        if os.path.exists(version_file):
            with open(version_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return 'v0.0.0'
    
    def _fetch_url(self, url: str, headers: dict = None, github_api: bool = False) -> tuple:
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'MC-Schedule-Updater/1.0')
            # GitHub API 需要特殊的 Accept 头
            if github_api or 'api.github.com' in url:
                req.add_header('Accept', 'application/vnd.github.v3+json')
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
        def parse(v):
            parts = v.lstrip('v').split('.')
            # 支持 1-4 位版本号，不足的补 0
            nums = []
            for p in parts[:4]:
                try:
                    nums.append(int(p))
                except ValueError:
                    break
            # 补零到至少 3 位
            while len(nums) < 3:
                nums.append(0)
            return nums
        
        p1, p2 = parse(v1), parse(v2)
        if p1 < p2:
            return -1
        elif p1 > p2:
            return 1
        return 0
    
    def test_sources(self) -> List[SourceStatus]:
        import time
        
        results = []
        
        start = time.time()
        success, _ = self._fetch_url(self.GITHUB_API_LATEST)
        latency = int((time.time() - start) * 1000)
        results.append(SourceStatus(
            id='github',
            name='GitHub（直连）',
            available=success,
            latency=latency,
            error=None if success else _
        ))
        
        start = time.time()
        success, _ = self._fetch_url(self.GITEE_API_LATEST)
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
        """检查更新 - 使用版本列表获取真正的最新版本"""
        # 获取版本列表（不包含预发布版本）
        success, releases = self.get_releases(source_id=source_id, prerelease=False)
        
        if not success:
            return VersionInfo(
                current_version=self.current_version,
                latest_version='获取失败',
                has_update=False,
                update_log=[f'获取版本列表失败: {releases}'],
                used_source=None
            )
        
        if not releases:
            return VersionInfo(
                current_version=self.current_version,
                latest_version='无可用版本',
                has_update=False,
                update_log=['未找到可用版本'],
                used_source=None
            )
        
        # 按版本号排序，找出最新版本
        sorted_releases = sorted(
            releases,
            key=lambda r: self._version_key(r.tag_name),
            reverse=True
        )
        
        latest = sorted_releases[0]
        latest_version = latest.tag_name
        
        # 构建更新日志
        update_log = []
        if latest.body:
            update_log = [line.strip() for line in latest.body.split('\n') if line.strip()][:10]
        
        has_update = self._compare_versions(self.current_version, latest_version) < 0
        
        return VersionInfo(
            current_version=self.current_version,
            latest_version=latest_version,
            has_update=has_update,
            update_log=update_log,
            used_source=source_id if source_id != 'auto' else 'releases',
            release_url=latest.html_url
        )
    
    def _version_key(self, version: str) -> tuple:
        """版本号排序键"""
        parts = version.lstrip('v').split('.')
        nums = []
        for p in parts[:4]:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(0)
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums)
    
    def get_releases(self, source_id: str = 'auto', prerelease: bool = False) -> tuple:
        """
        获取版本列表
        
        Args:
            source_id: 'auto', 'github', 'gitee'
            prerelease: 是否包含预发布版本
        
        Returns:
            (success, releases_or_error)
        """
        releases = []
        
        if source_id == 'gitee':
            sources = [('gitee', self.GITEE_API_RELEASES)]
        elif source_id == 'github':
            sources = [('github', self.GITHUB_API_RELEASES)]
        else:
            sources = [('gitee', self.GITEE_API_RELEASES), ('github', self.GITHUB_API_RELEASES)]
        
        for source_name, api_url in sources:
            success, data = self._fetch_url(api_url)
            
            if success:
                try:
                    releases_data = json.loads(data)
                    
                    for r in releases_data:
                        if not prerelease and r.get('prerelease', False):
                            continue
                        
                        # Gitee 使用 created_at，GitHub 使用 published_at
                        published_at = r.get('published_at', '') or r.get('created_at', '')
                        # 统一 zipball_url（Gitee 可能用不同的字段名）
                        zipball = r.get('zipball_url', '') or r.get('tarball_url', '')
                        if not zipball and 'tag_name' in r:
                            # 手动构造 zipball URL
                            if 'gitee' in api_url:
                                zipball = f"https://gitee.com/weiwu001/MC-Schedule/archive/{r['tag_name']}.zip"
                            else:
                                zipball = f"https://github.com/WEIWU-001/MC-Schedule/archive/refs/tags/{r['tag_name']}.zip"
                        
                        releases.append(Release(
                            tag_name=r.get('tag_name', ''),
                            name=r.get('name', ''),
                            body=r.get('body', ''),
                            published_at=published_at,
                            prerelease=r.get('prerelease', False),
                            html_url=r.get('html_url', ''),
                            zipball_url=zipball
                        ))
                    
                    logger.info(f'从 {source_name} 获取到 {len(releases)} 个版本')
                    
                    # 按版本号排序（从高到低）
                    releases.sort(key=lambda r: self._version_key(r.tag_name), reverse=True)
                    
                    return True, releases
                except json.JSONDecodeError:
                    logger.warning(f'{source_name} 返回数据解析失败')
                    continue
            else:
                logger.warning(f'{source_name} 获取版本列表失败: {data}')
        
        return False, '无法获取版本列表'
    
    def do_update(self, source_id: str = 'auto', target_version: str = None, create_backup: bool = True) -> UpdateResult:
        """
        执行更新（支持切换到指定版本）
        
        Args:
            source_id: 'auto', 'github', 'gitee'
            target_version: 目标版本号（如 v1.2.5），None 则更新到最新
            create_backup: 是否创建备份
        
        Returns:
            UpdateResult 对象
        """
        # 获取版本列表
        success, releases = self.get_releases(source_id)
        
        if not success:
            return UpdateResult(
                success=False,
                message=f'获取版本列表失败: {releases}'
            )
        
        if not releases:
            return UpdateResult(
                success=False,
                message='未找到可用版本'
            )
        
        # 确定目标版本
        if target_version:
            target_release = next((r for r in releases if r.tag_name == target_version), None)
            if not target_release:
                return UpdateResult(
                    success=False,
                    message=f'未找到版本: {target_version}'
                )
        else:
            # 获取最新版本（非预发布）
            stable_releases = [r for r in releases if not r.prerelease]
            if stable_releases:
                target_release = stable_releases[0]
            else:
                target_release = releases[0]
        
        target_version = target_release.tag_name
        
        # 检查是否已是当前版本
        if target_version == self.current_version:
            return UpdateResult(
                success=False,
                message=f'已是当前版本 {self.current_version}'
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
        if source_id == 'gitee':
            download_url = self.GITEE_ZIPBALL.format(tag=target_version)
            used_source = 'Gitee'
        elif source_id == 'github':
            download_url = self.GITHUB_ZIPBALL.format(tag=target_version)
            used_source = 'GitHub'
        else:
            # 使用 Gitee 优先
            download_url = self.GITEE_ZIPBALL.format(tag=target_version)
            used_source = 'Gitee'
        
        logger.info(f'开始从 {used_source} 下载版本: {target_version}')
        
        # 下载 ZIP
        temp_dir = tempfile.mkdtemp(prefix='update_download_')
        zip_path = os.path.join(temp_dir, 'update.zip')
        
        success, error = self._download_file(download_url, zip_path)
        
        if not success:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if backup_path:
                shutil.rmtree(backup_path, ignore_errors=True)
            
            return UpdateResult(
                success=False,
                message=f'下载更新包失败: {error}\n\n建议使用"上传更新包"功能手动更新',
                used_source=used_source
            )
        
        if not zipfile.is_zipfile(zip_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return UpdateResult(
                success=False,
                message='下载的文件不是有效的ZIP格式',
                used_source=used_source
            )
        
        # 应用更新
        result = self._apply_zip_update(zip_path, target_version)
        
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        if result.success:
            if backup_path:
                shutil.rmtree(backup_path, ignore_errors=True)
            
            result.used_source = used_source
            result.new_version = target_version
        else:
            if backup_path:
                self._restore_backup(backup_path)
        
        return result
    
    def upload_update(self, zip_file, create_backup: bool = True) -> UpdateResult:
        backup_path = None
        if create_backup:
            backup_path = self._create_backup()
            if not backup_path:
                return UpdateResult(
                    success=False,
                    message='创建备份失败，取消更新以保护数据'
                )
        
        try:
            temp_dir = tempfile.mkdtemp(prefix='update_upload_')
            zip_path = os.path.join(temp_dir, 'update.zip')
            zip_file.save(zip_path)
            
            if not zipfile.is_zipfile(zip_path):
                shutil.rmtree(temp_dir, ignore_errors=True)
                return UpdateResult(
                    success=False,
                    message='无效的ZIP文件'
                )
            
            new_version = self._extract_version_from_zip(zip_path)
            result = self._apply_zip_update(zip_path, new_version)
            
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            if result.success:
                if backup_path:
                    shutil.rmtree(backup_path, ignore_errors=True)
                result.update_method = 'zip_upload'
            else:
                if backup_path:
                    self._restore_backup(backup_path)
            
            return result
            
        except Exception as e:
            logger.error(f'上传更新失败: {e}')
            return UpdateResult(
                success=False,
                message=f'上传更新失败: {str(e)}'
            )
    
    def _create_backup(self) -> Optional[str]:
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
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('VERSION'):
                        content = zf.read(name).decode('utf-8').strip()
                        return content
        except:
            pass
        return 'unknown'
    
    def _apply_zip_update(self, zip_path: str, new_version: str) -> UpdateResult:
        try:
            extract_dir = tempfile.mkdtemp(prefix='update_extract_')
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
            
            extracted_items = os.listdir(extract_dir)
            if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
                content_dir = os.path.join(extract_dir, extracted_items[0])
            else:
                content_dir = extract_dir
            
            updated_files = []
            for root, dirs, files in os.walk(content_dir):
                dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]
                
                for filename in files:
                    if filename in self.EXCLUDE_FILES:
                        continue
                    
                    src_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(src_path, content_dir)
                    dst_path = os.path.join(self.project_root, rel_path)
                    
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.copy2(src_path, dst_path)
                    updated_files.append(rel_path)
            
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
    # app.root_path 是 Flask 应用目录，VERSION 文件在项目根目录
    # 如果 app.py 在项目根目录，则 root_path 就是项目根目录
    project_root = app.root_path
    return Updater(project_root)
