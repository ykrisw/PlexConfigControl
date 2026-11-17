"""Journaled QNAP subtree Restore. Never starts/stops Plex or rolls back ZFS."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import ctypes
import errno
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import uuid
import traceback

from .archives import BASE, InvalidArchive, validate_archive
from .archive_store import NAME, file_identity
from .backup_archive import compare_contents
from .execution import parse_restore_request
from .qnap_runtime import plex_process_state
from .qnap_discovery import QnapDiscoveryError,discover_qnap_plex
from .qnap_snapshot_probe import OwnedSnapshotProbe, SnapshotProbeError
from .qnap_snapshot_reader import open_snapshot_data


class QnapRestoreError(RuntimeError):pass


def identity(path):
    try:info=Path(path).lstat()
    except FileNotFoundError:return None
    if not stat.S_ISDIR(info.st_mode):raise QnapRestoreError('Restore directory type changed')
    return [info.st_dev,info.st_ino]


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def rename_held(source_fd,source,target_fd,target):
    libc=ctypes.CDLL(None,use_errno=True)
    try:function=libc.renameat2
    except AttributeError:function=None
    if function is not None:
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        function.restype=ctypes.c_int
        result=function(source_fd,os.fsencode(source),target_fd,os.fsencode(target),1)
    else:
        # Older NAS glibc can lack the wrapper although its kernel supports
        # renameat2. Preserve RENAME_NOREPLACE using the native x86-64 syscall.
        # Never fall back to an overwriting os.rename().
        if platform.machine()!='x86_64':raise QnapRestoreError('Atomic no-replace rename requires x86-64')
        syscall=libc.syscall;syscall.restype=ctypes.c_long
        result=syscall(ctypes.c_long(316),ctypes.c_int(source_fd),ctypes.c_char_p(os.fsencode(source)),
                       ctypes.c_int(target_fd),ctypes.c_char_p(os.fsencode(target)),ctypes.c_uint(1))
    if result:
        code=ctypes.get_errno();raise OSError(code,os.strerror(code))
    os.fsync(source_fd);os.fsync(target_fd)


def stopped(installation,*,proc=Path('/proc'),pause=time.sleep):
    # Include scanners, transcoders and native SQLite, not just the main server.
    prefix=installation.install_directory+'/'
    for attempt in range(3):
        if plex_process_state(installation)!='STOPPED':raise QnapRestoreError('Stop Plex manually in QNAP App Center before Restore')
        for entry in proc.iterdir():
            if not entry.name.isdecimal():continue
            try:target=os.readlink(entry/'exe').removesuffix(' (deleted)')
            except OSError as error:
                if error.errno in (errno.ENOENT,errno.ESRCH):continue
                raise QnapRestoreError('Plex process absence cannot be confirmed') from None
            if target.startswith(prefix):raise QnapRestoreError('Plex package tools are still running; wait before Restore')
        if attempt<2:pause(.4)


def tree_digest(root,*,sync=False):
    """All regular bytes, symlink text, ownership, modes, mtimes and xattrs."""
    root=Path(root);digest=hashlib.sha256()
    def fail(error):raise error
    def add(path):
        info=path.lstat();mode=info.st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)):raise QnapRestoreError('Special files in Restore tree')
        # Symlink timestamps can be rounded by filesystems; preserve their text,
        # ownership and attributes. Regular files/directories retain mtimes.
        row=[str(path.relative_to(root)),mode,info.st_uid,info.st_gid]
        if not stat.S_ISLNK(mode):row.append(info.st_mtime_ns)
        attributes=[]
        for name in sorted(os.listxattr(path,follow_symlinks=False)):
            attributes.append([name,os.getxattr(path,name,follow_symlinks=False).hex()])
        row.append(attributes)
        if stat.S_ISLNK(mode):row.append(os.readlink(path))
        elif stat.S_ISREG(mode):
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as source:
                before=os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode) or (before.st_dev,before.st_ino)!=(info.st_dev,info.st_ino):raise QnapRestoreError('File identity changed during verification')
                row.extend([before.st_size,hashlib.file_digest(source,'sha256').hexdigest()])
                if file_identity(os.fstat(source.fileno()))!=file_identity(before):raise QnapRestoreError('File changed during verification')
                if sync:os.fsync(source.fileno())
        digest.update(json.dumps(row,ensure_ascii=True,separators=(',',':')).encode()+b'\n')
    add(root)
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=fail):
        dirs.sort();files.sort()
        for name in dirs+files:add(Path(directory)/name)
        if sync:sync_directory(Path(directory))
    return digest.hexdigest()


def trusted_sqlite(installation,workspace,database,sql,*,timeout=1800):
    root=Path(installation.install_directory)
    candidates=[]
    for path in (root/'Plex SQLite',root/'Resources/Plex SQLite'):
        if not path.exists():continue
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode&0o022 or info.st_uid!=0 or not os.access(path,os.X_OK):
            raise QnapRestoreError('Trusted Plex SQLite is unavailable')
        if path.parent.resolve(strict=True)!=path.parent:raise QnapRestoreError('Plex SQLite parent changed')
        candidates.append(path)
    if len(candidates)!=1:raise QnapRestoreError('One trusted Plex SQLite executable is required')
    env={'PATH':'/bin:/usr/bin:/usr/local/bin','LANG':'C','LC_ALL':'C','HOME':str(workspace),'TMPDIR':str(workspace),
         'SQLITE_HISTORY':'/dev/null','LD_LIBRARY_PATH':str(root/'lib')+':'+str(root)}
    result=subprocess.run([str(candidates[0]),'-batch','-noheader','-init','/dev/null',str(database),sql],
                          cwd=workspace,env=env,capture_output=True,text=True,timeout=timeout,check=False)
    if result.returncode:raise QnapRestoreError('Plex SQLite integrity check failed')
    return result.stdout.strip()


def check_databases(installation,workspace,prepared,report):
    result=trusted_sqlite(installation,workspace,':memory:','SELECT sqlite_version(); PRAGMA integrity_check;',timeout=20).splitlines()
    if len(result)!=2 or result[1]!='ok':raise QnapRestoreError('Plex SQLite self-test failed')
    database=prepared/'Plug-in Support/Databases'
    for directory in (prepared,prepared/'Plug-in Support',database):
        if identity(directory) is None:raise QnapRestoreError('Prepared database directory is missing')
    for name in ('com.plexapp.plugins.library.db','com.plexapp.plugins.library.blobs.db'):
        for suffix in ('','-wal','-journal','-shm'):
            path=database/(name+suffix)
            try:info=path.lstat()
            except FileNotFoundError:
                if not suffix:raise QnapRestoreError('Required Plex database missing')
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise QnapRestoreError('Unsafe database or recovery sidecar')
            if suffix=='-shm':path.unlink()  # Staging only. Persistent WAL/journal remain.
        report('CHECKING_DATABASE',name)
        if trusted_sqlite(installation,workspace,database/name,'PRAGMA integrity_check;')!='ok':raise QnapRestoreError('Prepared Plex database failed integrity check')
        report('DATABASE_OK',name)


def inspect_archive(path,progress=None):
    links={};ancestors={'config','config/Library','config/Library/Application Support'};base=BASE.rstrip('/')
    with tarfile.open(path,'r|gz') as archive:
        for index,member in enumerate(archive):
            if index>=2_000_000:raise InvalidArchive('Too many entries')
            name=member.name.rstrip('/')
            if name in ancestors or name==base:
                if not member.isdir():raise InvalidArchive('Invalid Plex parent directory')
            elif not name.startswith(BASE):raise InvalidArchive('File outside Plex data subtree')
            if member.issym():
                if name in links or len(member.linkname)>4096 or '\0' in member.linkname:raise InvalidArchive('Invalid symbolic link')
                links[name]=(member.linkname,member.uid,member.gid)
    result=validate_archive(path,expected_symlinks={k:v[0] for k,v in links.items()},progress_callback=progress)
    return result,links


def extract_private(archive,workspace,binary,validation,links,progress):
    destination=workspace/'extracted';destination.mkdir(mode=0o700)
    if shutil.disk_usage(workspace).free<validation.bytes_read+1024**3:raise QnapRestoreError('Insufficient free space for prepared Restore plus 1 GiB')
    result=subprocess.run([str(binary),'--acls','--xattrs','--xattrs-include=*','--numeric-owner','--same-owner','--same-permissions',
        '--no-wildcards','--anchored',*['--exclude='+name for name in links],'-xzpf',str(archive),'-C',str(destination)],
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=False)
    if result.returncode:raise QnapRestoreError('GNU tar extraction failed')
    for name,(target,uid,gid) in links.items():
        current=destination
        for part in Path(name).parts[:-1]:
            current=current/part
            if not stat.S_ISDIR(current.lstat().st_mode):raise QnapRestoreError('Symbolic link ancestor is not a directory')
        path=destination/name;os.symlink(target,path);os.lchown(path,uid,gid)
    prepared=destination/BASE.rstrip('/')
    compare_contents(prepared,archive,total_bytes=validation.bytes_read,source_layout='plex-data',preserve_symlinks=True,progress_callback=progress)
    return prepared


class QnapRestore:
    def __init__(self,service):self.s=service
    @property
    def job(self):return self.s.current
    @property
    def record(self):return self.job['restore']
    def installation(self):
        try:installation=self.s.discover()
        except QnapDiscoveryError:
            installation=discover_qnap_plex(recover_data_directory=self.job['installation']['data_directory'])
        if {k:v for k,v in asdict(installation).items() if k!='package_enabled'}!={k:v for k,v in self.job['installation'].items() if k!='package_enabled'}:raise QnapRestoreError('Plex installation changed after preparation')
        return installation
    def paths(self):
        installation=self.installation();live=Path(installation.data_directory);record=self.record
        parent=live.parent
        if parent.resolve(strict=True)!=parent or identity(parent)!=record['parent']:raise QnapRestoreError('Plex data parent changed')
        work=parent/('.pcc-restore-'+record['id'])
        if record.get('workspace_identity') and (work.exists() or work.is_symlink()):
            info=work.lstat()
            if identity(work)!=record['workspace_identity'] or info.st_uid!=os.geteuid() or info.st_mode&0o077:raise QnapRestoreError('Private Restore workspace changed')
        return installation,live,work

    def start_validation(self,data):
        if not isinstance(data,dict) or set(data)!={'archive','background'} or data['background'] is not True or not isinstance(data['archive'],str) or not NAME.fullmatch(data['archive']):raise QnapRestoreError('Choose one recognized backup archive')
        s=self.s
        with s.mutex:
            s._idle()
            if s.api is None:raise QnapRestoreError('Sign in to QNAP before Restore preparation')
            binding,path=s._binding();installation=s.discover();live=Path(installation.data_directory)
            if live.resolve(strict=True)!=live or identity(live) is None or live.stat().st_dev!=live.parent.stat().st_dev or installation.dedicated_dataset_root:
                raise QnapRestoreError('Restore requires a regular Plex subtree on its parent filesystem')
            rows=[row for row in s._archives() if row.name==data['archive']]
            if len(rows)!=1:raise QnapRestoreError('Selected archive is unavailable')
            identifier=uuid.uuid4().hex;now=s.clock();stamp=str(time.time_ns())
            s.current={'request_id':identifier,'kind':'RESTORE','state':'VALIDATING','created_ns':stamp,'updated_ns':stamp,'started':now,'finished':None,
                       'archive':data['archive'],'stage':'STAGING_ARCHIVE','done':0,'total':None,'snapshot':None,'error':None,'admitted':False,
                       'destination':binding,'installation':asdict(installation),'selected':s._wire(rows[0]),
                       'restore':{'id':identifier,'parent':identity(live.parent),'original':identity(live),'prepared':None,'workspace_identity':None,'phase':'PREPARING','retained':False}}
            s._save();s.busy=True
            try:threading.Thread(target=self._prepare,name='pcc-restore-prepare',daemon=False).start()
            except Exception:s.busy=False;self.finish(False,'Restore preparation worker could not start');raise
            return {'accepted':True,'status_url':'/api/operation'}

    def _copy_archive(self,path,destination):
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as source:
            before=os.fstat(source.fileno());selected=self.job['selected']
            if not stat.S_ISREG(before.st_mode) or any(str(getattr(before,attr))!=selected[key] for attr,key in [('st_dev','device'),('st_ino','inode'),('st_size','size'),('st_mtime_ns','modified_ns')]):raise QnapRestoreError('Archive changed since selection')
            if shutil.disk_usage(destination.parent).free<before.st_size+1024**3:raise QnapRestoreError('Insufficient free space to stage archive')
            with destination.open('xb') as output:
                os.chmod(destination,0o600);done=0
                while chunk:=source.read(1024*1024):
                    output.write(chunk);done+=len(chunk)
                    if done>before.st_size:raise QnapRestoreError('Archive changed during staging')
                output.flush();os.fsync(output.fileno())
            if done!=before.st_size or file_identity(os.fstat(source.fileno()))!=file_identity(before):raise QnapRestoreError('Archive changed during staging')
        return file_identity(before)

    def _prepare(self):
        s=self.s;log=None
        try:
            installation,live,work=self.paths();log=s._open_log()
            work.mkdir(mode=0o700);os.chmod(work,0o700);self.record['workspace_identity']=identity(work);s._save();sync_directory(work.parent)
            binding,path=s._binding()
            if binding!=self.job['destination']:raise QnapRestoreError('Archive folder changed')
            self.job['file_identity']=self._copy_archive(path/self.job['archive'],work/'source.tar.gz');s._save()
            def progress(stage,done):s._progress(stage,done)
            validation,links=inspect_archive(work/'source.tar.gz',progress)
            self.job.update(sha256=validation.sha256,files=validation.files,bytes=validation.bytes_read);s._save();s._progress('STAGING_ARCHIVE')
            prepared=extract_private(work/'source.tar.gz',work,s.private_tar,validation,links,lambda done,total:s._progress('VERIFYING_RESTORE',done,total))
            os.rename(prepared,work/'prepared');sync_directory(work)
            check_databases(installation,work,work/'prepared',lambda stage,value:log.write(stage+': '+value+'\n'))
            pid=work/'prepared/plexmediaserver.pid'
            if pid.exists() or pid.is_symlink():
                info=pid.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise QnapRestoreError('Invalid private staging PID file')
                pid.unlink();log.write('Removed stale PID from private staging only.\n')
            self.record.update(prepared=identity(work/'prepared'),prepared_digest=tree_digest(work/'prepared',sync=True),phase='READY')
            if identity(live)!=self.record['original'] or self.record['prepared'][0]!=self.record['original'][0]:raise QnapRestoreError('Plex directory identity changed')
            log.write('SHA-256: '+validation.sha256+'\nFull extraction/byte/symlink comparison and both database checks: OK.\nWaiting for manual Plex stop.\n')
            log.flush();os.fsync(log.fileno());log.close();log=None
            s.history.add('ARCHIVE_VALIDATION','SUCCESS',self.job['log'],self.job['archive'])
            with s.mutex:self.job.update(state='WAITING_FOR_PLEX_STOP',stage='WAITING_FOR_PLEX_STOP');s._save()
        except BaseException as error:
            message=str(error) if isinstance(error,(QnapRestoreError,InvalidArchive)) else type(error).__name__
            if log:
                try:log.write('Preparation failed: '+message+'\n');log.close()
                except OSError:pass
            self.finish(False,message)
        finally:
            with s.mutex:s.busy=False

    def details(self):
        job=self.job
        if job['state']=='FAILED' and not job.get('admitted'):return {'archive':job['archive'],'status':'FAILED','reason':job.get('error')}
        if job['state'] in ('VALIDATING','WAITING_FOR_PLEX_STOP') or job.get('sha256'):
            return {'archive':job['archive'],'status':'VALID' if job.get('sha256') and job['state']!='VALIDATING' else 'VALIDATING',
                    'reason':None,'sha256':job.get('sha256'),'files':job.get('files'),'bytes_read':job.get('bytes'),
                    'file_identity':job.get('file_identity')}
        return {'archive':job['archive'],'status':'FAILED','reason':job.get('error')}

    def readiness(self):
        s=self.s;state=plex_process_state(s.discover());job=s.current
        plex={'state':state,'available':state!='UNKNOWN','restore_allowed':state=='STOPPED','checked_at':datetime.now(timezone.utc).isoformat()}
        reason='VALIDATE_ARCHIVE_FIRST';archive=None
        if job and job['kind']=='RESTORE' and job['state']=='WAITING_FOR_PLEX_STOP':
            archive=job['archive'];reason='STOP_PLEX_MANUALLY' if state=='RUNNING' else 'PLEX_STOP_NOT_CONFIRMED'
            if state=='STOPPED':
                try:
                    self.paths();binding,path=s._binding()
                    if binding!=job['destination'] or file_identity((path/archive).lstat())!=job['file_identity']:reason='ARCHIVE_CHANGED_REVALIDATE'
                    else:reason=None
                except Exception:reason='ARCHIVE_CHANGED_REVALIDATE'
            if s.api is None:reason='QNAP_AUTHENTICATION_REQUIRED'
        return {'ready':reason is None,'reason':reason,'plex':plex,'archive':archive,'confirmation_text':'RESTORE','confirmation_required':True,'platform':'QNAP'}

    def execute(self,data):
        request=parse_restore_request(data);s=self.s
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        with s.mutex:
            old=s._load(request.request_id)
            if old:
                if old.get('request_digest')!=digest:raise QnapRestoreError('Operation request identity changed')
                return {'accepted':True,'request_id':request.request_id,'kind':'RESTORE','status_url':'/api/operation'}
            if s.busy or s.auth_busy or not self.readiness()['ready']:raise QnapRestoreError('Restore readiness changed; stop Plex manually and refresh')
            if request.archive!=self.job['archive'] or request.sha256!=self.job['sha256']:raise QnapRestoreError('Confirmed archive changed')
            self.job.update(request_id=request.request_id,request_digest=digest,admitted=True,state='QUEUED',stage='PREPARING');s._save();s.busy=True
            try:threading.Thread(target=self._apply,name='pcc-restore-apply',daemon=False).start()
            except Exception:s.busy=False;self.finish(False,'Restore execution worker could not start');raise
            return {'accepted':True,'request_id':request.request_id,'kind':'RESTORE','status_url':'/api/operation'}

    def layout(self):
        installation,live,work=self.paths();old,new=self.record['original'],self.record['prepared']
        current,previous,prepared,rejected=[identity(path) for path in (live,work/'previous',work/'prepared',work/'rejected')]
        if current==old and previous is None:
            if prepared==new and rejected is None and new is not None:return 'READY'
            if prepared is None and rejected==new and new is not None:return 'ROLLED_BACK'
            if new is None:return 'PREPARING'
        if current==new and previous==old and prepared is None and rejected is None and new is not None:return 'APPLIED'
        if current is None and previous==old and new is not None:
            if prepared==new and rejected is None:return 'OLD_SAVED'
            if prepared is None and rejected==new:return 'ROLLBACK_GAP'
        raise QnapRestoreError('Restore directory layout is ambiguous; no directory was removed')

    def move(self,source,target):
        installation,live,work=self.paths()
        parent_fd=os.open(live.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);work_fd=os.open(work,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            if [os.fstat(parent_fd).st_dev,os.fstat(parent_fd).st_ino]!=self.record['parent'] or [os.fstat(work_fd).st_dev,os.fstat(work_fd).st_ino]!=self.record['workspace_identity']:raise QnapRestoreError('Restore directory identity changed')
            source_fd=parent_fd if source=='LIVE' else work_fd;target_fd=parent_fd if target=='LIVE' else work_fd
            rename_held(source_fd,live.name if source=='LIVE' else source,target_fd,live.name if target=='LIVE' else target)
        finally:os.close(parent_fd);os.close(work_fd)

    def rollback(self):
        s=self.s;installation,live,work=self.paths();situation=self.layout()
        if situation in ('READY','PREPARING','ROLLED_BACK'):
            if self.record.get('original_digest') and self.record.get('phase') in ('SWAP_STARTED','OLD_SAVED','ROLLBACK_STARTED','APPLIED'):
                if tree_digest(live)!=self.record['original_digest']:raise QnapRestoreError('Original configuration rollback verification failed')
                self.record.update(phase='ROLLED_BACK',retained=True);s._save()
            return
        stopped(installation)
        if tree_digest(work/'previous')!=self.record['original_digest']:raise QnapRestoreError('Retained original configuration changed; rollback blocked')
        s._progress('ROLLING_BACK');self.record['phase']='ROLLBACK_STARTED';s._save()
        if situation=='APPLIED':
            self.move('LIVE','rejected');stopped(installation)
            if self.layout()!='ROLLBACK_GAP':raise QnapRestoreError('Rollback layout changed')
        self.move('previous','LIVE');stopped(installation)
        if self.layout() not in ('READY','ROLLED_BACK') or tree_digest(live)!=self.record['original_digest']:raise QnapRestoreError('Original configuration rollback verification failed')
        self.record.update(phase='ROLLED_BACK',retained=True);s._save()

    def _apply(self):
        s=self.s;log=None;success=False;message=None
        try:
            installation,live,work=self.paths();stopped(installation)
            self.job['apply_archive']=self.job['archive'];s._save()
            if self.layout()!='READY' or tree_digest(work/'prepared')!=self.record['prepared_digest']:raise QnapRestoreError('Prepared Restore tree changed')
            self.record['original_digest']=tree_digest(live,sync=True);s._save();stopped(installation)
            self.job.update(state='RUNNING',stage='CREATING_SNAPSHOT');s._save();log=s._open_log()
            coordinator=self
            class RestoreProbe(OwnedSnapshotProbe):
                def _change(self,function):
                    s._snapshot_record(self,**({'attempted':True} if function=='create_snapshot' else {'delete_requested':True}))
                    return super()._change(function)
                def _owned_row(self):
                    row=super()._owned_row()
                    if row:s._snapshot_record(self,identifier=row['id'])
                    return row
                def _cleanup(self):
                    s._snapshot_record(self)
                    if not coordinator.record.get('verified'):raise SnapshotProbeError('Restore failed; owned recovery snapshot retained')
                    super()._cleanup();s._snapshot_record(self,cleanup_confirmed=True)
            def apply(identifier,baseline):
                with open_snapshot_data(installation,identifier,baseline,report=report) as source:
                    stopped(installation)
                    if self.layout()!='READY':raise QnapRestoreError('Restore layout changed before swap')
                    self.record['phase']='SWAP_STARTED';s._save();s._progress('RESTORING')
                    self.move('LIVE','previous');self.record['phase']='OLD_SAVED';s._save();stopped(installation)
                    if self.layout()!='OLD_SAVED':raise QnapRestoreError('Restore layout changed during swap')
                    self.move('prepared','LIVE');self.record.update(phase='APPLIED',retained=True);s._save();stopped(installation)
                    s._progress('VERIFYING_RESTORE')
                    if self.layout()!='APPLIED' or tree_digest(live,sync=True)!=self.record['prepared_digest']:raise QnapRestoreError('Restored byte/metadata verification failed')
                    stopped(installation);self.record['verified']=True;s._save()
                    return source.storage_identity
            unchecked_apply=apply
            def apply(identifier,baseline):
                try:return unchecked_apply(identifier,baseline)
                except Exception as error:
                    self.job['apply_failure']={'type':type(error).__name__,'errno':getattr(error,'errno',None),'phase':self.record.get('phase')}
                    s._save()
                    log.write('APPLY_FAILURE: '+json.dumps(self.job['apply_failure'],sort_keys=True)+'\n')
                    log.write(traceback.format_exc()+'\n')
                    raise
            def report(stage,value):
                log.write(stage+': '+str(value)+'\n')
                if stage in ('WAITING_FOR_DELETION','CLEANUP_CONFIRMED'):s._progress('REMOVING_SNAPSHOT')
            probe=RestoreProbe(s.api,installation,inspect_data=apply,report=report);probe.name='pcc-restore-'+uuid.uuid4().hex;probe.expire_minutes=1440
            result=probe.run()
            if result['error'] or not result['readable'] or not result['cleanup_confirmed']:
                self.job['snapshot_failure']={key:result.get(key) for key in ('created','readable','cleanup_confirmed','error','cleanup_error','id')}
                s._save()
                log.write('SNAPSHOT_RESULT: '+json.dumps(self.job['snapshot_failure'],sort_keys=True)+'\n')
                raise QnapRestoreError('Restore snapshot stage failed: '+str(result['error'] or result['cleanup_error'] or 'verification incomplete'))
            log.write('Restore bytes/metadata verified. Recovery snapshot deletion confirmed by API and ZFS.\nStart Plex manually, check playback, then accept Restore or stop Plex manually and roll back.\n')
            success=True
        except BaseException as error:
            message=str(error) if isinstance(error,QnapRestoreError) else type(error).__name__
            try:
                if not self.record.get('verified'):self.rollback()
            except Exception:message+='; previous configuration recovery requires manual Plex stop and explicit recovery'
            if log:
                try:log.write('Restore failed: '+message+'\n')
                except OSError:pass
        finally:
            if log:
                try:log.flush();os.fsync(log.fileno());log.close()
                except OSError:success=False;message='Restore operation log finalization failed'
            try:self.finish(success,message)
            finally:
                with s.mutex:s.busy=False

    def finish(self,success,error):
        s=self.s
        if not success and not self.job.get('admitted'):
            try:self.cleanup()
            except Exception:
                self.job.update(state='RECOVERY_REQUIRED',stage='CLEANUP_REQUIRED',error='Restore preparation cleanup requires review');s._save();return
        snapshot=self.job.get('snapshot');phase=self.record.get('phase')
        unresolved=bool(snapshot and snapshot.get('attempted') and not snapshot.get('cleanup_confirmed')) or phase in ('SWAP_STARTED','OLD_SAVED','ROLLBACK_STARTED')
        if not success and self.record.get('verified'):unresolved=True
        if not success and not unresolved and phase in ('PREPARING','READY') and not self.record.get('retained'):
            try:self.cleanup()
            except Exception:unresolved=True
        target='RECOVERY_REQUIRED' if unresolved else 'SUCCEEDED' if success else 'FAILED'
        self.job.update(state='RECOVERY_REQUIRED' if unresolved else 'RUNNING',stage='COMPLETED' if success else 'CLEANUP_REQUIRED' if unresolved else 'FAILED',error=error,finished=s.clock());s._save()
        try:
            s.history.add('RESTORE', 'SUCCESS' if success else 'WARNING' if unresolved else 'FAILED',self.job.get('log','Restore operation did not create a log'),self.job['archive'])
            self.job['state']=target;s._save()
        except Exception:self.job.update(state='RECOVERY_REQUIRED',stage='CLEANUP_REQUIRED',error='Restore final reporting failed');s._save()

    def cancel(self):
        with self.s.mutex:
            if self.s.busy or self.s.auth_busy or self.job['state'] not in ('WAITING_FOR_PLEX_STOP','FAILED') or self.job.get('admitted'):raise QnapRestoreError('Only unused Restore preparation can be cancelled')
            self.cleanup();self.job.update(state='FAILED',stage='FAILED',error=None,cancelled=True);self.s._save()
            return {'cancelled':True}

    def cleanup(self):
        installation,live,work=self.paths()
        if identity(live)!=self.record['original'] and not (self.record.get('accepted') and identity(live)==self.record['prepared']):raise QnapRestoreError('Configuration identity does not permit cleanup')
        if self.record.get('workspace_identity') and (work.exists() or work.is_symlink()):
            shutil.rmtree(work);sync_directory(work.parent)
        elif work.exists() or work.is_symlink():raise QnapRestoreError('Unrecorded private workspace requires manual inspection')
        self.record.update(workspace_identity=None,retained=False,cleaned=True);self.s._save()

    def recover(self):
        installation,live,work=self.paths()
        if self.record.get('accepted'):
            # User-authorized deletion of the retained old tree may have been
            # interrupted. Never roll back into a partially deleted old tree.
            if identity(live)!=self.record['prepared']:raise QnapRestoreError('Accepted live configuration identity changed')
            self.s._recover_snapshot();self.cleanup();self.job['error']=None;self.finish(True,None);return
        if self.record.get('original_digest'):stopped(installation)
        if not work.exists() and identity(live)==self.record['original']:
            if self.record.get('original_digest') and tree_digest(live)!=self.record['original_digest']:raise QnapRestoreError('Original configuration identity requires review')
            self.record['phase']='ROLLED_BACK' if self.job.get('admitted') else 'PREPARING';self.s._save()
        else:self.rollback()
        if self.record.get('original_digest') and tree_digest(live)!=self.record['original_digest']:raise QnapRestoreError('Original configuration identity requires review')
        self.s._recover_snapshot();self.record['verified']=False
        self.cleanup();self.finish(False,'Original configuration retained/recovered; interrupted Restore remains failed')

    def retained_action(self,data):
        if not isinstance(data,dict) or set(data)!={'action','confirmed'} or data['confirmed'] is not True or data['action'] not in ('accept','rollback'):raise QnapRestoreError('Confirm acceptance or rollback of the retained Restore')
        s=self.s
        with s.mutex:
            if s.busy or s.auth_busy or self.job['state'] not in ('SUCCEEDED','FAILED') or not self.record.get('retained'):raise QnapRestoreError('No completed Restore is awaiting review')
            if s.api is None:raise QnapRestoreError('Sign in to QNAP before confirming Restore')
            s.busy=True
            self.record['review_action']=data['action'];s._save()
            try:threading.Thread(target=self._review,name='pcc-restore-review',daemon=False).start()
            except Exception:s.busy=False;raise
            return {'accepted':True}

    def _review(self):
        s=self.s;log=None
        try:
            installation,live,work=self.paths()
            if self.record['review_action']=='rollback':
                stopped(installation)
                log=s._open_log();self.job['state']='RUNNING';s._save()
                self.rollback();self.record['verified']=False
                self.cleanup();log.write('Explicit rollback verified. Original configuration is live; start Plex manually.\n')
                log.flush();os.fsync(log.fileno());log.close();log=None
                self.finish(False,'Original configuration restored by explicit rollback')
            else:
                situation=self.layout()
                if situation not in ('APPLIED','ROLLED_BACK'):raise QnapRestoreError('Restore layout does not permit acceptance')
                if situation=='APPLIED' and plex_process_state(installation)!='RUNNING':raise QnapRestoreError('Start Plex manually and verify it before accepting Restore')
                log=s._open_log();self.record['review_previous_state']=self.job['state']
                self.record['accepted']=situation=='APPLIED';self.job['state']='RUNNING';s._save()
                self.cleanup();log.write('User accepted Restore review. Private retained configuration/staging removed. Live configuration and source archive retained.\n')
                log.flush();os.fsync(log.fileno());log.close();log=None
                s.history.add('RESTORE_CONFIRMATION','SUCCESS',self.job['log'],self.job['archive'])
                self.record['review_action']=None;self.job['state']=self.record['review_previous_state'];self.job['error']=None;s._save()
        except BaseException as error:
            self.job['error']=str(error) if isinstance(error,QnapRestoreError) else type(error).__name__
            if self.job['state']=='RUNNING':self.job.update(state='RECOVERY_REQUIRED',stage='CLEANUP_REQUIRED')
            s._save()
        finally:
            if log:
                try:log.close()
                except OSError:pass
            with s.mutex:s.busy=False
