# -*- coding: utf-8 -*-
"""
MC-Schedule 更新器模块
用于从 GitHub/Gitee 仓库检查和执行更新
"""

import os
import sys
import subprocess
import threading
import time
import shutil
import zipfile
import tempfile
import logging
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class UpdateSource:
    """更新源"""
    def __init__(self, id: str, name: str, url: str = '', source_type: str = 'mirror', description: str = ''):
        self.id = id
        self.name = name
        self.url = url
        self.type = source_type  # 'mirror', 'direct'
        self.description = description


@dataclass
class VersionInfo:
    """版本信息"""
    current_version: str
    current_branch: str
    latest_version: str
    has_update: bool
    update_log: List[str]
    used_source: Optional[str]
    remote_commit: Optional[str] = None


@dataclass
class UpdateResult:
    """更新结果"""
    success: bool
    message: str
    new_version: Optional[str] = None
    output: Optional[str] = None
    used_source: Optional[str] = None
    backup_path: Optional[str] = None
    updated_files: Optional[List[str]] = None
    update_method: Optional[str] = None  # 'git', 'zip_download', 'zip_upload'


class UpdaterError(Exception):
    """更新器异常"""
    pass


class Updater:
    """更新器核心类"""
    
    # 默认更新源配置
    DEFAULT_SOURCES = [
        UpdateSource('git', 'GitHub', '', 'direct', 'GitHub仓库直连'),
        UpdateSource('gitee', 'Gitee', '', 'direct', 'Gitee仓库'),
        UpdateSource('ghproxy', 'GHProxy', 'https://ghproxy.com/https://github.com', 'mirror', 'GHProxy镜像'),
        UpdateSource('gitclone', 'GitClone', 'https://gitclone.com/github.com', 'mirror', 'GitClone镜像'),
    ]
    
    # 排除的目录和文件
    EXCLUDE_DIRS = {'logs', 'database.db', '__pycache__', '.git', 'node_modules', 'update_temp', '.venv', 'venv', 'env'}
    EXCLUDE_FILES = {'.env', '.production_mode', '.secret_key', '.env.example', 'requirements.txt'}
    
    def __init__(
        self,
        project_root: str,
        remote_repo_url: str = 'https://github.com/WEIWU-001/MC-Schedule.git',
        default_branch: str = 'main',
        update_sources: Optional[List[UpdateSource]] = None,
        http_proxy: str = '',
        https_proxy: str = '',
        timeout: int = 60,
        max_retries: int = 2
    ):
        """
        初始化更新器
        
        Args:
            project_root: 项目根目录
            remote_repo_url: 远程仓库URL
            default_branch: 默认分支
            update_sources: 更新源列表
            http_proxy: HTTP代理
            https_proxy: HTTPS代理
            timeout: 超时时间(秒)
            max_retries: 最大重试次数
        """
        self.project_root = project_root
        self.remote_repo_url = remote_repo_url
        self.default_branch = default_branch
        self.update_sources = update_sources or self.DEFAULT_SOURCES
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self.timeout = timeout
        self.max_retries = max_retries
        
        self._setup_proxy()
    
    def _setup_proxy(self):
        """设置代理环境变量"""
        if self.http_proxy:
            os.environ['HTTP_PROXY'] = self.http_proxy
            os.environ['http_proxy'] = self.http_proxy
        if self.https_proxy:
            os.environ['HTTPS_PROXY'] = self.https_proxy
            os.environ['https_proxy'] = self.https_proxy
    
    def _run_git_command(self, args: List[str], cwd: str = None, timeout: int = None) -> Tuple[int, str, str]:
        """
        运行git命令
        
        Returns:
            (returncode, stdout, stderr)
        """
        if cwd is None:
            cwd = self.project_root
        
        timeout = timeout or self.timeout
        
        try:
            proc = subprocess.Popen(
                ['git'] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd
            )
            
            stdout, stderr = proc.communicate(timeout=timeout)
            return proc.returncode, stdout.strip(), stderr.strip()
        except subprocess.TimeoutExpired:
            proc.kill()
            return -1, '', 'Command timeout'
        except FileNotFoundError:
            return -2, '', 'Git not found'
        except Exception as e:
            return -3, '', str(e)
    
    def _run_git_command_with_thread(self, args: List[str], timeout: int = None) -> Dict:
        """使用线程运行git命令，避免阻塞"""
        timeout = timeout or self.timeout
        result = {'returncode': None, 'stdout': '', 'stderr': '', 'exception': None}
        
        def run():
            try:
                result['returncode'], result['stdout'], result['stderr'] = self._run_git_command(args, timeout=timeout)
            except Exception as e:
                result['exception'] = str(e)
        
        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout + 5)
        
        if thread.is_alive():
            return {'returncode': -1, 'stdout': '', 'stderr': 'Thread timeout', 'exception': None}
        
        return result
    
    def get_current_version(self) -> Tuple[str, str]:
        """
        获取当前版本信息
        
        Returns:
            (commit_hash, branch_name)
        """
        os.chdir(self.project_root)
        
        _, commit_hash, _ = self._run_git_command(['rev-parse', 'HEAD'])
        if not commit_hash or 'not a git repository' in commit_hash.lower():
            # 尝试从VERSION文件读取
            version_file = os.path.join(self.project_root, 'VERSION')
            if os.path.exists(version_file):
                with open(version_file, 'r', encoding='utf-8') as f:
                    commit_hash = f.read().strip()
            else:
                commit_hash = 'unknown'
        
        _, branch, _ = self._run_git_command(['branch', '--show-current'])
        if not branch:
            branch = self.default_branch
        
        return commit_hash, branch
    
    def get_version_from_file(self) -> Optional[str]:
        """从VERSION文件获取语义化版本"""
        version_file = os.path.join(self.project_root, 'VERSION')
        if os.path.exists(version_file):
            try:
                with open(version_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                # 简单验证是否为版本号格式
                if content and len(content) <= 20:
                    return content
            except:
                pass
        return None
    
    def _fetch_via_api(self, source: UpdateSource, branch: str) -> Optional[str]:
        """通过 HTTP API 获取远程 commit（git ls-remote 的备选方案）"""
        try:
            if source.id == 'gitee' or 'gitee.com' in self.remote_repo_url:
                api_url = f'https://gitee.com/api/v5/repos/weiwu001/MC-Schedule/commits/{branch}'
            else:
                api_url = f'https://api.github.com/repos/WEIWU-001/MC-Schedule/commits/{branch}'
            
            req = urllib.request.Request(api_url)
            req.add_header('User-Agent', 'MC-Schedule-Updater/1.0')
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                sha = data.get('sha')
                if sha:
                    logger.info(f'通过 API 获取到 {source.name} 的 commit: {sha[:7]}')
                    return sha
        except urllib.error.HTTPError as e:
            logger.warning(f'API 请求 {source.name} HTTP 错误: {e.code}')
        except urllib.error.URLError as e:
            logger.warning(f'API 请求 {source.name} 网络错误: {e.reason}')
        except Exception as e:
            logger.warning(f'API 请求 {source.name} 异常: {e}')
        return None

    def _fetch_remote_version(self, source: UpdateSource) -> Optional[str]:
        """通过 HTTP 获取远程 VERSION 文件内容"""
        try:
            if source.id == 'gitee' or 'gitee.com' in self.remote_repo_url:
                version_url = 'https://gitee.com/weiwu001/MC-Schedule/raw/master/VERSION'
            else:
                version_url = 'https://raw.githubusercontent.com/WEIWU-001/MC-Schedule/master/VERSION'
            
            req = urllib.request.Request(version_url)
            req.add_header('User-Agent', 'MC-Schedule-Updater/1.0')
            
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode('utf-8').strip()
                if content:
                    logger.info(f'通过 HTTP 获取到 {source.name} 的 VERSION: {content}')
                    return content
        except urllib.error.HTTPError as e:
            logger.warning(f'获取远程 VERSION {source.name} HTTP 错误: {e.code}')
        except urllib.error.URLError as e:
            logger.warning(f'获取远程 VERSION {source.name} 网络错误: {e.reason}')
        except Exception as e:
            logger.warning(f'获取远程 VERSION {source.name} 异常: {e}')
        return None

    def try_fetch_from_source(self, source: UpdateSource, branch: str) -> Tuple[bool, Optional[str]]:
        """
        从指定源获取远程commit
        
        Returns:
            (success, remote_commit)
        """
        if source.type == 'direct':
            if source.id == 'gitee':
                repo_url = self.remote_repo_url.replace('github.com', 'gitee.com')
                repo_url = repo_url.replace('WEIWU-001', 'weiwu001')
            else:
                repo_url = self.remote_repo_url
        elif source.type == 'mirror' and source.url:
            repo_url = self.remote_repo_url.replace('https://github.com', source.url)
        else:
            return False, None
        
        # 设置远程仓库
        self._run_git_command(['remote', 'rm', 'origin'])
        _, _, _ = self._run_git_command(['remote', 'add', 'origin', repo_url])
        
        for attempt in range(self.max_retries):
            result = self._run_git_command_with_thread(
                ['ls-remote', '--heads', 'origin', branch],
                timeout=self.timeout
            )
            
            if result['returncode'] == 0 and result['stdout']:
                lines = result['stdout'].strip().split('\n')
                if lines and lines[0]:
                    remote_commit = lines[0].split()[0]
                    return True, remote_commit
            
            if attempt < self.max_retries - 1:
                time.sleep(1)
        
        # git ls-remote 失败，尝试 HTTP API 备选方案
        logger.info(f'git ls-remote {source.name} 失败，尝试 API 方式')
        api_commit = self._fetch_via_api(source, branch)
        if api_commit:
            return True, api_commit
        
        return False, None
    
    def check_update(self, source_id: str = '') -> VersionInfo:
        """
        检查更新
        
        Args:
            source_id: 指定更新源ID，为空则自动选择
            
        Returns:
            VersionInfo对象
        """
        current_commit, current_branch = self.get_current_version()
        
        # 尝试从VERSION文件获取语义化版本
        semantic_version = self.get_version_from_file()
        display_version = semantic_version or (current_commit[:7] if current_commit != 'unknown' else 'unknown')
        
        remote_commit = None
        used_source_name = None
        
        # 确定要使用的源
        if source_id:
            selected_source = next((s for s in self.update_sources if s.id == source_id), None)
            if selected_source:
                success, remote = self.try_fetch_from_source(selected_source, current_branch)
                if success:
                    remote_commit = remote
                    used_source_name = selected_source.name
        else:
            # 按照配置文件中的顺序尝试更新源
            # 顺序：git (GitHub) → gitee → ghproxy → gitclone
            for source in self.update_sources:
                success, remote = self.try_fetch_from_source(source, current_branch)
                if success:
                    remote_commit = remote
                    used_source_name = source.name
                    break
        
        if not remote_commit:
            raise UpdaterError('无法连接到任何更新源，请检查网络或配置代理')
        
        # 判断是否是 git 仓库
        is_git_repo = os.path.exists(os.path.join(self.project_root, '.git'))
        
        # 如果不是 git 仓库，用 VERSION 文件比较
        remote_version = None
        if not is_git_repo and semantic_version:
            for source in self.update_sources:
                remote_version = self._fetch_remote_version(source)
                if remote_version:
                    break
        
        # 获取更新日志
        update_log = []
        
        if is_git_repo:
            has_update = current_commit != remote_commit
        else:
            has_update = (semantic_version != remote_version) if remote_version else False
        
        if has_update:
            self._run_git_command(['remote', 'rm', 'origin'])
            self._run_git_command(['remote', 'add', 'origin', self.remote_repo_url])
            
            _, log_output, _ = self._run_git_command(
                ['log', '--oneline', f'{current_commit}..origin/{current_branch}', '-n', '10']
            )
            if log_output:
                update_log = log_output.split('\n')
        
        # 确定显示的最新版本
        latest_display = remote_version if (not is_git_repo and remote_version) else (remote_commit[:7] if remote_commit else 'unknown')
        
        return VersionInfo(
            current_version=display_version,
            current_branch=current_branch,
            latest_version=latest_display,
            has_update=has_update,
            update_log=update_log,
            used_source=used_source_name,
            remote_commit=remote_commit
        )
    
    def create_backup(self) -> Optional[str]:
        """
        创建当前版本的备份
        
        Returns:
            备份目录路径，失败返回None
        """
        try:
            backup_dir = os.path.join(self.project_root, 'update_backup')
            
            # 清理旧备份
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            
            os.makedirs(backup_dir, exist_ok=True)
            
            # 复制文件
            for item in os.listdir(self.project_root):
                if item in self.EXCLUDE_DIRS or item.startswith('.'):
                    continue
                src = os.path.join(self.project_root, item)
                dst = os.path.join(backup_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            
            logger.info(f'备份已创建: {backup_dir}')
            return backup_dir
        except Exception as e:
            logger.error(f'创建备份失败: {e}')
            return None
    
    def restore_backup(self, backup_path: str) -> bool:
        """
        从备份恢复
        
        Args:
            backup_path: 备份目录路径
            
        Returns:
            是否成功
        """
        try:
            if not os.path.exists(backup_path):
                logger.error(f'备份不存在: {backup_path}')
                return False
            
            # 清理当前目录
            for item in os.listdir(self.project_root):
                if item in self.EXCLUDE_DIRS or item.startswith('.'):
                    continue
                src = os.path.join(self.project_root, item)
                if os.path.isdir(src):
                    shutil.rmtree(src)
                else:
                    os.remove(src)
            
            # 恢复备份
            for item in os.listdir(backup_path):
                src = os.path.join(backup_path, item)
                dst = os.path.join(self.project_root, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            
            logger.info('已从备份恢复')
            return True
        except Exception as e:
            logger.error(f'恢复备份失败: {e}')
            return False
    
    def _download_zip(self, source: UpdateSource) -> Tuple[bool, str, str]:
        """
        从指定源下载ZIP更新包
        
        Returns:
            (success, zip_path, error_message)
        """
        try:
            # 构建ZIP下载URL
            if source.id == 'gitee' or 'gitee.com' in self.remote_repo_url:
                zip_url = f'https://gitee.com/weiwu001/MC-Schedule/repository/archive/{self.default_branch}.zip'
            else:
                zip_url = f'https://github.com/WEIWU-001/MC-Schedule/archive/refs/heads/{self.default_branch}.zip'
            
            # 如果有镜像，使用镜像URL
            if source.type == 'mirror' and source.url:
                zip_url = zip_url.replace('https://github.com', source.url)
            
            logger.info(f'正在从 {source.name} 下载ZIP: {zip_url}')
            
            # 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix='update_download_')
            zip_path = os.path.join(temp_dir, 'update.zip')
            
            # 下载文件
            req = urllib.request.Request(zip_url)
            req.add_header('User-Agent', 'MC-Schedule-Updater/1.0')
            
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(zip_path, 'wb') as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            
            # 验证ZIP文件
            if not zipfile.is_zipfile(zip_path):
                shutil.rmtree(temp_dir)
                return False, '', '下载的文件不是有效的ZIP格式'
            
            logger.info(f'ZIP下载成功: {zip_path}')
            return True, zip_path, ''
            
        except urllib.error.HTTPError as e:
            logger.error(f'下载ZIP HTTP错误: {e.code}')
            return False, '', f'HTTP {e.code}'
        except urllib.error.URLError as e:
            logger.error(f'下载ZIP网络错误: {e.reason}')
            return False, '', str(e.reason)
        except Exception as e:
            logger.error(f'下载ZIP异常: {e}')
            return False, '', str(e)
    
    def _apply_zip_update(self, zip_path: str) -> UpdateResult:
        """
        应用ZIP更新包
        
        Args:
            zip_path: ZIP文件路径
            
        Returns:
            UpdateResult对象
        """
        try:
            # 解压
            extract_dir = tempfile.mkdtemp(prefix='update_extract_')
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # 检查是否有嵌套目录
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
                    
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.copy2(src_path, dst_path)
                    updated_files.append(rel_path)
            
            # 清理临时文件
            shutil.rmtree(extract_dir)
            os.remove(zip_path)
            
            return UpdateResult(
                success=True,
                message='ZIP更新成功！请重启服务器以应用更改',
                updated_files=updated_files,
                update_method='zip_download'
            )
            
        except Exception as e:
            logger.error(f'应用ZIP更新失败: {e}')
            return UpdateResult(
                success=False,
                message=f'应用ZIP更新失败: {str(e)}'
            )
    
    def do_update(self, source_id: str = '', create_backup: bool = True) -> UpdateResult:
        """
        执行更新
        
        Args:
            source_id: 指定更新源ID
            create_backup: 是否创建备份
            
        Returns:
            UpdateResult对象
        """
        current_commit, current_branch = self.get_current_version()
        backup_path = None
        
        # 创建备份
        if create_backup:
            backup_path = self.create_backup()
            if not backup_path:
                return UpdateResult(
                    success=False,
                    message='创建备份失败，取消更新以保护数据'
                )
        
        try:
            remote_commit = None
            used_source_name = None
            output_messages = []
            
            # 收集所有可用源
            sources_to_try = []
            
            if source_id:
                selected_source = next((s for s in self.update_sources if s.id == source_id), None)
                if selected_source:
                    sources_to_try.append(selected_source)
            else:
                # 按照配置文件中的顺序尝试更新源
                sources_to_try = list(self.update_sources)
            
            # 尝试每个源
            for source in sources_to_try:
                success, remote = self.try_fetch_from_source(source, current_branch)
                if success:
                    remote_commit = remote
                    used_source_name = source.name
                    
                    # 执行pull
                    if source.type == 'direct':
                        if source.id == 'gitee':
                            pull_url = self.remote_repo_url.replace('github.com', 'gitee.com')
                            pull_url = pull_url.replace('WEIWU-001', 'weiwu001')
                        else:
                            pull_url = self.remote_repo_url
                    else:
                        pull_url = self.remote_repo_url.replace('https://github.com', source.url)
                    
                    self._run_git_command(['remote', 'rm', 'origin'])
                    self._run_git_command(['remote', 'add', 'origin', pull_url])
                    
                    returncode, stdout, stderr = self._run_git_command(
                        ['pull', 'origin', current_branch],
                        timeout=self.timeout * 2
                    )
                    
                    if returncode == 0:
                        # 获取新版本
                        new_commit, _ = self.get_current_version()
                        
                        # 清理备份
                        if backup_path and os.path.exists(backup_path):
                            try:
                                shutil.rmtree(backup_path)
                            except:
                                pass
                        
                        return UpdateResult(
                            success=True,
                            message='更新成功！请重启服务器以应用更改',
                            new_version=new_commit[:7],
                            output=stdout,
                            used_source=used_source_name,
                            backup_path=backup_path,
                            update_method='git'
                        )
                    else:
                        output_messages.append(f'{source.name}: {stderr or stdout}')
            
            # 所有源都失败
            return UpdateResult(
                success=False,
                message=f'所有更新源均无法完成更新。\n' + '\n'.join(output_messages),
                backup_path=backup_path
            )
            
        except Exception as e:
            logger.error(f'更新异常: {e}')
            return UpdateResult(
                success=False,
                message=f'更新失败: {str(e)}',
                backup_path=backup_path
            )
    
    def hybrid_update(self, source_id: str = '', create_backup: bool = True) -> UpdateResult:
        """
        混合更新策略：先尝试git，失败则下载ZIP包
        
        流程：
        1. 尝试git pull更新
        2. 如果git失败，尝试下载ZIP包并应用
        3. 如果都失败，提示手动上传ZIP
        
        Args:
            source_id: 指定更新源ID
            create_backup: 是否创建备份
            
        Returns:
            UpdateResult对象
        """
        current_commit, current_branch = self.get_current_version()
        backup_path = None
        
        # 创建备份
        if create_backup:
            backup_path = self.create_backup()
            if not backup_path:
                return UpdateResult(
                    success=False,
                    message='创建备份失败，取消更新以保护数据'
                )
        
        # 阶段1：尝试git更新
        logger.info('阶段1：尝试git更新...')
        git_result = self.do_update(source_id=source_id, create_backup=False)
        
        if git_result.success:
            # 清理备份
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except:
                    pass
            git_result.backup_path = backup_path
            return git_result
        
        logger.info(f'git更新失败: {git_result.message}')
        
        # 阶段2：尝试下载ZIP包
        logger.info('阶段2：尝试下载ZIP更新包...')
        
        # 确定要尝试的源
        sources_to_try = []
        if source_id:
            selected_source = next((s for s in self.update_sources if s.id == source_id), None)
            if selected_source:
                sources_to_try.append(selected_source)
        else:
            sources_to_try = list(self.update_sources)
        
        for source in sources_to_try:
            logger.info(f'尝试从 {source.name} 下载ZIP...')
            success, zip_path, error = self._download_zip(source)
            
            if success:
                logger.info(f'从 {source.name} 下载ZIP成功，准备应用更新...')
                zip_result = self._apply_zip_update(zip_path)
                
                if zip_result.success:
                    # 更新VERSION文件
                    try:
                        version_file = os.path.join(self.project_root, 'VERSION')
                        if os.path.exists(version_file):
                            with open(version_file, 'r', encoding='utf-8') as f:
                                current_version = f.read().strip()
                            # 增加补丁版本号
                            version_parts = current_version.lstrip('v').split('.')
                            if len(version_parts) == 3:
                                version_parts[2] = str(int(version_parts[2]) + 1)
                                new_version = 'v' + '.'.join(version_parts)
                                with open(version_file, 'w', encoding='utf-8') as f:
                                    f.write(new_version)
                                zip_result.new_version = new_version
                    except:
                        pass
                    
                    # 清理备份
                    if backup_path and os.path.exists(backup_path):
                        try:
                            shutil.rmtree(backup_path)
                        except:
                            pass
                    
                    zip_result.backup_path = backup_path
                    zip_result.used_source = source.name
                    return zip_result
                else:
                    logger.warning(f'应用ZIP更新失败: {zip_result.message}')
            else:
                logger.warning(f'从 {source.name} 下载ZIP失败: {error}')
        
        # 阶段3：所有自动方式都失败，提示手动上传
        logger.info('阶段3：所有自动更新方式均失败')
        
        # 恢复备份（如果有）
        if backup_path and os.path.exists(backup_path):
            self.restore_backup(backup_path)
        
        return UpdateResult(
            success=False,
            message='自动更新失败。git连接超时，且无法下载ZIP包。\n\n' +
                    '建议：\n' +
                    '1. 在服务器配置代理（HTTP_PROXY=http://127.0.0.1:7890）\n' +
                    '2. 手动下载更新包并上传\n' +
                    '3. 使用"📦 上传更新包"功能手动更新',
            backup_path=backup_path
        )
    
    def upload_update(self, zip_file, create_backup: bool = True) -> UpdateResult:
        """
        通过上传ZIP包更新
        
        Args:
            zip_file: 上传的ZIP文件对象
            create_backup: 是否创建备份
            
        Returns:
            UpdateResult对象
        """
        backup_path = None
        
        # 创建备份
        if create_backup:
            backup_path = self.create_backup()
            if not backup_path:
                return UpdateResult(
                    success=False,
                    message='创建备份失败，取消更新以保护数据'
                )
        
        try:
            # 保存上传的文件
            temp_dir = tempfile.mkdtemp(prefix='update_')
            zip_path = os.path.join(temp_dir, 'update.zip')
            zip_file.save(zip_path)
            
            # 验证ZIP文件
            if not zipfile.is_zipfile(zip_path):
                shutil.rmtree(temp_dir)
                return UpdateResult(
                    success=False,
                    message='无效的ZIP文件',
                    backup_path=backup_path
                )
            
            # 解压
            extract_dir = os.path.join(temp_dir, 'content')
            os.makedirs(extract_dir)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # 检查是否有嵌套目录
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
                    
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.copy2(src_path, dst_path)
                    updated_files.append(rel_path)
            
            # 清理临时文件
            shutil.rmtree(temp_dir)
            
            # 清理备份
            if backup_path and os.path.exists(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except:
                    pass
            
            return UpdateResult(
                success=True,
                message='更新包上传成功！请重启服务器以应用更改',
                updated_files=updated_files,
                backup_path=backup_path,
                update_method='zip_upload'
            )
            
        except Exception as e:
            logger.error(f'上传更新失败: {e}')
            return UpdateResult(
                success=False,
                message=f'更新失败: {str(e)}',
                backup_path=backup_path
            )
    
    def test_sources(self) -> List[Dict]:
        """
        测试所有更新源的连通性
        
        Returns:
            [{id, name, success, latency, error}, ...]
        """
        results = []
        
        for source in self.update_sources:
            result = {
                'id': source.id,
                'name': source.name,
                'success': False,
                'latency': -1,
                'error': None
            }
            
            start_time = time.time()
            
            try:
                if source.type == 'mirror' and source.url:
                    test_url = source.url.split('/https://github.com')[0]
                    if test_url.endswith('/'):
                        test_url = test_url[:-1]
                    
                    # 使用curl测试
                    returncode, stdout, stderr = self._run_git_command(
                        ['ls-remote', '--heads', f'{source.url}/https://github.com/WEIWU-001/MC-Schedule.git', 'main'],
                        timeout=30
                    )
                    
                    result['latency'] = int((time.time() - start_time) * 1000)
                    result['success'] = returncode == 0
                    if not result['success']:
                        result['error'] = stderr or stdout
                elif source.type == 'direct':
                    # 测试Gitee
                    returncode, stdout, stderr = self._run_git_command(
                        ['ls-remote', '--heads', self.remote_repo_url, 'main'],
                        timeout=30
                    )
                    
                    result['latency'] = int((time.time() - start_time) * 1000)
                    result['success'] = returncode == 0
                    if not result['success']:
                        result['error'] = stderr or stdout
            except Exception as e:
                result['error'] = str(e)
            
            results.append(result)
        
        return results


# Flask集成辅助函数
def get_updater_from_app(app) -> Updater:
    """从Flask应用获取Updater实例"""
    return Updater(
        project_root=app.root_path,
        remote_repo_url=app.config.get('REMOTE_REPO_URL', 'https://github.com/WEIWU-001/MC-Schedule.git'),
        default_branch=app.config.get('DEFAULT_BRANCH', 'main'),
        update_sources=_build_sources_from_config(app.config.get('UPDATE_SOURCES', [])),
        http_proxy=app.config.get('HTTP_PROXY', ''),
        https_proxy=app.config.get('HTTPS_PROXY', '')
    )


def _build_sources_from_config(config_list: List[Dict]) -> List[UpdateSource]:
    """从配置字典构建UpdateSource列表"""
    sources = []
    for item in config_list:
        sources.append(UpdateSource(
            id=item.get('id', ''),
            name=item.get('name', ''),
            url=item.get('url', ''),
            source_type=item.get('type', 'mirror'),
            description=item.get('description', '')
        ))
    return sources
