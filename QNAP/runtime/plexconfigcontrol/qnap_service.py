"""Fixed-purpose root-side QNAP backup service. Never starts/stops/restores Plex.

All authority and snapshot/publication intent stay in the root-owned directory.
The panel sends typed requests over a peer-UID checked socket, not commands.
"""
from contextlib import contextmanager
import configparser
import ctypes
from dataclasses import asdict
from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from .archive_store import ArchiveStore, file_identity
from .archives import archive_name
from .archives import InvalidArchive
from .backup_archive import BackupArchiveError
from .execution import parse_backup_request
from .history import History
from .naming import folder_component
from .qnap_api import QnapLocalReadOnlyApi, QnapApiError, local_certificate_context
from .qnap_archive_capture import capture_snapshot_archive
from .qnap_discovery import discover_qnap_plex
from .qnap_runtime import plex_process_state
from .qnap_restore import QnapRestore, QnapRestoreError
from .qnap_snapshot_probe import OwnedSnapshotProbe, storage_snapshots
from .qnap_snapshot_reader import open_snapshot_data
from .qnap_snapshot_reader import QnapSnapshotReadError

EVENT_BASE=1_000_000_000
ACTIVE={'QUEUED','RUNNING','RECOVERY_REQUIRED','VALIDATING','WAITING_FOR_PLEX_STOP'}


class QnapServiceError(RuntimeError):
    pass


def write_record(path,data):
    temporary=path.with_suffix('.new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    sync_directory(path.parent)


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def directory_identity(path):
    info=Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode):raise QnapServiceError('A real directory is required')
    return [info.st_dev,info.st_ino]


def native_shares(path=Path('/etc/config/smb.conf')):
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    parser.read_string(path.read_text())
    entries=[]
    for name in parser.sections():
        if name.lower() in ('global','homes','home','printers') or name.startswith('.') or name.endswith('$'):continue
        raw=parser.get(name,'path',fallback='')
        if not raw.startswith('/share/'):continue
        try:root=Path(raw).resolve(strict=True)
        except OSError:continue
        if not root.is_dir() or '.qpkg' in root.parts or '.zfs' in root.parts:continue
        identifier=hashlib.sha256((name+'\0'+str(root)).encode()).hexdigest()
        entries.append({'id':identifier,'name':name,'path':str(root)})
    return entries


def administrator(username):
    if not isinstance(username,str) or not 1<=len(username)<=128 or any(ord(c)<32 for c in username):
        raise QnapServiceError('A local QNAP administrator account is required')
    try:
        user=pwd.getpwnam(username);admin=grp.getgrnam('administrators')
    except KeyError:raise QnapServiceError('A local QNAP administrator account is required') from None
    if user.pw_uid!=0 and user.pw_gid!=admin.gr_gid and username not in admin.gr_mem:
        raise QnapServiceError('A local QNAP administrator account is required')
    return user


def publish_held_file(source_fd,destination_fd,name):
    """Link the verified held inode, not a mutable SMB directory entry."""
    libc=ctypes.CDLL(None,use_errno=True)
    linkat=libc.linkat
    linkat.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_int]
    linkat.restype=ctypes.c_int
    # /proc resolves the held descriptor itself. AT_SYMLINK_FOLLOW avoids
    # requiring CAP_DAC_READ_SEARCH for AT_EMPTY_PATH on NAS service processes.
    if linkat(-100,os.fsencode('/proc/self/fd/'+str(source_fd)),destination_fd,os.fsencode(name),0x400)!=0:
        error=ctypes.get_errno()
        raise OSError(error,os.strerror(error))
    os.fsync(destination_fd)


class QnapBackupService:
    def __init__(self,owner,private_tar,*,discover=discover_qnap_plex,shares=native_shares,clock=time.time):
        self.owner=Path(owner);self.private_tar=Path(private_tar)
        self.discover,self.shares,self.clock=discover,shares,clock
        self.jobs=self.owner/'qnap-jobs';self.jobs.mkdir(mode=0o700,exist_ok=True)
        self.pointer=self.owner/'qnap-current.json';self.location=self.owner/'archive-location.json'
        self.history=History(self.owner/'qnap-history')
        self.mutex=threading.RLock();self.api=None;self.user=None;self.busy=False;self.auth_busy=False
        self.current=None;self.restore=QnapRestore(self)
        if self.pointer.exists():
            identifier=json.loads(self.pointer.read_text())['request_id']
            self.current=self._load(identifier)
            if self.current and self.current['state'] in ('QUEUED','RUNNING','VALIDATING'):
                self.current['state']='RECOVERY_REQUIRED'
                self.current['error']='Operation interrupted; authenticate and finish recovery before another backup'
                self.current['stage']='CLEANUP_REQUIRED';self._save()
        from .qnap_session import start
        start(self)

    def _load(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[0-9a-f]{32}',identifier):raise QnapServiceError('Invalid operation identity')
        path=self.jobs/(identifier+'.json')
        return json.loads(path.read_text()) if path.exists() else None

    def _save(self):
        self.current['updated_ns']=str(time.time_ns())
        write_record(self.jobs/(self.current['request_id']+'.json'),self.current)
        write_record(self.pointer,{'request_id':self.current['request_id']})

    def _idle(self):
        if self.busy or self.auth_busy or self.current and (self.current['state'] in ACTIVE or self.current.get('restore',{}).get('workspace_identity')):
            raise QnapServiceError('An operation or recovery must finish first')

    def _binding(self):
        if not self.location.exists():raise QnapServiceError('Choose an archive share and folder first')
        record=json.loads(self.location.read_text());path=Path(record['path'])
        available=self.shares()
        if not any(row['id']==record['share_id'] and row['path']==record['share_path'] for row in available):
            raise QnapServiceError('The selected SMB share changed')
        if path.parent!=Path(record['share_path']) or directory_identity(path)!=record['identity']:
            raise QnapServiceError('The selected archive folder changed')
        if path.resolve(strict=True)!=path or directory_identity(path/'Logs')!=record['logs_identity']:
            raise QnapServiceError('Archive/log directory identity changed')
        installation=self.discover();live=Path(installation.data_directory)
        if path==live or live in path.parents or path in live.parents:
            raise QnapServiceError('Archive and Plex data directories overlap')
        return record,path

    def _archives(self):
        record,path=self._binding()
        return ArchiveStore(path,self.owner/'qnap-archive-state').list()

    @staticmethod
    def _wire(row):
        return {'name':row.name,**{key:str(getattr(row,key)) for key in ('size','device','inode','modified_ns')}}

    def info(self):
        with self.mutex:
            location=None
            try:
                record,path=self._binding();location={'path':str(path),'share_id':record['share_id'],'folder':path.name}
            except (OSError,ValueError,QnapServiceError):pass
            return {'authenticated':self.api is not None,'username':self.user.pw_name if self.user else None,
                    'location':location,'busy':self.busy or self.auth_busy,'recovery_required':bool(self.current and self.current['state']=='RECOVERY_REQUIRED'),
                    'restore_review':bool(self.current and self.current.get('restore',{}).get('retained')),
                    'restore_preparation':bool(self.current and self.current['kind']=='RESTORE' and self.current['state'] in ('VALIDATING','WAITING_FOR_PLEX_STOP')),
                    'error':self.current.get('error') if self.current else None}

    def authenticate(self,data):
        if not isinstance(data,dict) or set(data)!={'username','password','totp'}:raise QnapServiceError('Invalid QNAP sign-in fields')
        user=administrator(data['username'])
        password=data['password'];totp=data['totp']
        if not isinstance(password,str) or not 1<=len(password)<=4096 or not isinstance(totp,str) or totp and not re.fullmatch(r'[0-9]{6}',totp):
            raise QnapServiceError('Enter the QNAP password and current six-digit TOTP')
        with self.mutex:
            if self.busy or self.auth_busy:raise QnapServiceError('Wait for the active operation')
            self.auth_busy=True
        api=None
        try:
            context,pin=local_certificate_context(Path('/etc/stunnel/stunnel.pem').read_text())
            api=QnapLocalReadOnlyApi(443,tls_context=context,certificate_sha256=pin,local_certificate_path="/etc/stunnel/stunnel.pem")
            try:api.login(user.pw_name,password,security_code_provider=lambda:totp)
            except QnapApiError:
                self.history.add('QNAP_LOGIN','FAILED','QNAP sign-in failed for local administrator '+user.pw_name+'. Password and TOTP were not stored.')
                raise
            self.history.add('QNAP_LOGIN','SUCCESS','QNAP sign-in succeeded for local administrator '+user.pw_name+'. Password and TOTP were not stored.')
            with self.mutex:
                if self.api:self.api.forget_session()
                self.api,self.user=api,user
                from .qnap_session import remember
                remember(self)
            return {'authenticated':True,'username':user.pw_name}
        finally:
            if api is not None and self.api is not api:api.forget_session()
            data.pop('password',None);data.pop('totp',None)
            del password,totp
            with self.mutex:self.auth_busy=False

    def configure(self,data):
        if not isinstance(data,dict) or set(data)!={'share_id','folder'}:raise QnapServiceError('Choose one SMB share and folder name')
        folder=folder_component(data['folder'])
        with self.mutex:
            self._idle()
            if self.api is None or self.user is None:raise QnapServiceError('Sign in with a QNAP administrator first')
            matches=[row for row in self.shares() if row['id']==data['share_id']]
            if len(matches)!=1:raise QnapServiceError('The selected share is unavailable')
            share=matches[0];root=Path(share['path']);path=root/folder
            live=Path(self.discover().data_directory)
            if path==live or live in path.parents or path in live.parents:raise QnapServiceError('Archive folder overlaps Plex data')
            root_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            def child(parent,name):
                created=False
                try:os.mkdir(name,mode=0o770,dir_fd=parent);created=True
                except FileExistsError:pass
                fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                if created:
                    os.fchown(fd,self.user.pw_uid,self.user.pw_gid);os.fchmod(fd,0o770);os.fsync(parent)
                return fd
            try:
                folder_fd=child(root_fd,folder)
                try:
                    logs_fd=child(folder_fd,'Logs')
                    try:
                        info=os.fstat(folder_fd);log_info=os.fstat(logs_fd)
                        record={'share_id':share['id'],'share_path':str(root),'path':str(path),
                                'identity':[info.st_dev,info.st_ino],'logs_identity':[log_info.st_dev,log_info.st_ino],
                                'uid':self.user.pw_uid,'gid':self.user.pw_gid}
                    finally:os.close(logs_fd)
                finally:os.close(folder_fd)
            finally:os.close(root_fd)
            if path.resolve(strict=True)!=path or directory_identity(path)!=record['identity']:
                raise QnapServiceError('Archive directory changed during configuration')
            write_record(self.location,record)
            from .qnap_eventlog import flush_events
            flush_events(self)
            return {'path':str(path)}

    def status(self,identifier=None):
        with self.mutex:
            job=self._load(identifier) if identifier else self.current
            if not job or job['kind']=='RESTORE' and not job.get('admitted'):return None
            return {key:job[key] for key in ('request_id','kind','state','created_ns','updated_ns')}

    def operation(self):
        with self.mutex:
            job=self.current
            snapshot=job.get('snapshot') if job else None
            pending=bool(snapshot and not snapshot.get('cleanup_confirmed'))
            phase=(job['state'] if job['state'] in ('VALIDATING','WAITING_FOR_PLEX_STOP','RECOVERY_REQUIRED') else
                   'RUNNING' if job['state'] in ('QUEUED','RUNNING') else
                   'SUCCESS' if job['state']=='SUCCEEDED' else 'FAILED') if job else 'IDLE'
            operation={'phase':phase,'kind':job['kind'] if job else None,'archive_identity':job.get('sha256') if job and job['kind']=='RESTORE' else None,
                       'snapshot_id':snapshot['dataset']+'@'+snapshot['name'] if pending else None,
                       'validation_details':self.restore.details() if job and job['kind']=='RESTORE' else None,
                       'execution_request_id':job['request_id'] if job and self.status() else None,'outcome':None}
            if job and job['kind']=='BACKUP':
                operation['outcome']={'code':'BACKUP_COMPLETED' if phase=='SUCCESS' else 'BACKUP_IN_PROGRESS' if phase=='RUNNING' else 'BACKUP_INTERRUPTED' if phase=='RECOVERY_REQUIRED' else 'BACKUP_RECONCILED' if job.get('reconciled') else 'BACKUP_FAILED','archive':job['archive']}
            elif job and job.get('admitted'):
                operation['outcome']={'code':'RESTORE_COMPLETED' if phase=='SUCCESS' else 'RESTORE_IN_PROGRESS' if phase=='RUNNING' else 'RESTORE_INTERRUPTED' if phase=='RECOVERY_REQUIRED' else 'RESTORE_ROLLBACK_VERIFIED' if job['restore']['phase']=='ROLLED_BACK' else 'RESTORE_FAILED_UNCHANGED','archive':job['archive']}
            progress=None
            if job:
                progress={'operation':job['kind'],'archive':job['archive'],'stage':job['stage'],'started':job['started'],'updated':float(job['updated_ns'])/1e9,
                          'finished':job.get('finished'),'done':job.get('done',0),'total':job.get('total'),
                          'elapsed_seconds':max(0,(job.get('finished') or self.clock())-job['started']),
                          'stage_percent':round(100*job.get('done',0)/job['total'],1) if job.get('total') else None,
                          'active':job['state'] in ('QUEUED','RUNNING','VALIDATING')}
            publication={'status':'NONE','pending':False,'archive':None,'temporary_file':None,'replaced_archive':None}
            if job and job.get('publishing') and job['state']=='RECOVERY_REQUIRED':
                publication.update(status='VERIFICATION_REQUIRED',pending=True,archive=job['archive'],temporary_file=job['temporary'])
            return {'platform':'QNAP','restore_review':bool(job and job.get('restore',{}).get('retained')),'operation':operation,'progress':progress,'publication':publication,'archive_discovery':None,
                    'execution':self.status(),'execution_bound':self.status() is not None}

    def plan(self):
        with self.mutex:
            self._idle();rows=self._archives()
            return {'archive_count':len(rows),'archive_prefix':'PlexConfig','action':'ASK_OVERWRITE_OR_NEW' if len(rows)==1 else 'CREATE_NEW',
                    'existing_archive':self._wire(rows[0]) if len(rows)==1 else None,'overwrite_available':False}

    def start_backup(self,data,zone='Europe/London'):
        request=parse_backup_request(data)
        if request.mode=='OVERWRITE':raise QnapServiceError('Overwrite is not enabled in this build')
        ZoneInfo(zone)
        canonical={'request':asdict(request),'timezone':zone}
        request_digest=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
        with self.mutex:
            previous=self._load(request.request_id)
            if previous:
                if previous['request_digest']!=request_digest:raise QnapServiceError('Request identity was reused with different parameters')
                return self._receipt(previous)
            self._idle()
            if self.api is None:raise QnapServiceError('Sign in with a QNAP administrator before backup')
            binding,path=self._binding();installation=self.discover()
            if plex_process_state(installation)!='RUNNING':raise QnapServiceError('Plex must be confirmed RUNNING for backup')
            rows=self._archives()
            if request.mode=='NEW' and len(rows)==1:raise QnapServiceError('Choose another dated copy')
            if request.mode=='ANOTHER' and (len(rows)!=1 or request.archive!=rows[0]):raise QnapServiceError('Archive selection changed')
            final=archive_name(datetime.now(timezone.utc),zone,prefix=request.prefix or 'PlexConfig')
            if (path/final).exists() or (path/final).is_symlink():raise QnapServiceError('A backup with this timestamp already exists')
            now=self.clock();stamp=str(time.time_ns())
            self.current={'request_id':request.request_id,'request_digest':request_digest,'kind':'BACKUP','state':'QUEUED',
                          'created_ns':stamp,'updated_ns':stamp,'started':now,'finished':None,'archive':final,
                          'stage':'PREPARING','done':0,'total':None,'snapshot':None,'error':None,
                          'temporary':'.pcc-'+request.request_id+'.tmp','publishing':False,
                          'destination':binding,'installation':asdict(installation)}
            self._save();self.busy=True
            try:threading.Thread(target=self._backup,name='pcc-qnap-backup',daemon=False).start()
            except Exception:
                self.busy=False;self._finish(False,'Worker could not start');raise
            return self._receipt(self.current)

    @staticmethod
    def _receipt(job):
        return {'accepted':True,'request_id':job['request_id'],'kind':'BACKUP','status_url':'/api/operation'}

    def _progress(self,stage,done=0,total=None):
        with self.mutex:
            self.current.update(stage=stage,done=done,total=total)
            self._save()

    def _snapshot_record(self,probe,**changes):
        with self.mutex:
            prior=self.current.get('snapshot') or {}
            value={'name':probe.name,'dataset':probe.installation.dataset,'volume_id':probe.installation.volume_id,
                   'identifier':probe.identifier or prior.get('identifier'),'storage':probe.storage_identifier or prior.get('storage'),
                   'baseline_ids':sorted(probe.baseline_ids),'baseline_storage':sorted(probe.baseline_storage),
                   'attempted':probe.attempted or prior.get('attempted',False),
                   'delete_requested':probe.delete_requested or prior.get('delete_requested',False),'cleanup_confirmed':prior.get('cleanup_confirmed',False)}
            value.update(changes);self.current['snapshot']=value;self._save()

    def _open_log(self):
        binding,path=self._binding()
        directory=os.open(path/'Logs',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            if [os.fstat(directory).st_dev,os.fstat(directory).st_ino]!=binding['logs_identity']:raise QnapServiceError('Logs folder changed')
            name='plex-'+self.current['kind'].lower()+'-'+datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')+'-'+uuid.uuid4().hex[:8]+'.log'
            fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
            os.fchown(fd,binding['uid'],binding['gid'])
            self.current['log']=name;self._save()
            return os.fdopen(fd,'w',buffering=1)
        finally:os.close(directory)

    def _publish(self,archive,validation):
        binding,path=self._binding()
        if binding!=self.current['destination']:raise QnapServiceError('Archive destination changed during operation')
        directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        temporary=self.current['temporary'];fd=None;created=None
        try:
            if [os.fstat(directory).st_dev,os.fstat(directory).st_ino]!=binding['identity']:raise QnapServiceError('Archive folder changed')
            self.current.update(publishing=True,sha256=validation.sha256,files=validation.files,bytes=validation.bytes_read)
            self._save();self._progress('PUBLISHING_ARCHIVE')
            fd=os.open(temporary,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
            created=[os.fstat(fd).st_dev,os.fstat(fd).st_ino]
            self.current['temporary_identity']=created;self._save()
            with archive.open('rb') as source:
                while chunk:=source.read(1024*1024):
                    view=memoryview(chunk)
                    while view:view=view[os.write(fd,view):]
            os.fsync(fd);os.lseek(fd,0,os.SEEK_SET)
            with os.fdopen(os.dup(fd),'rb') as copy:
                if hashlib.file_digest(copy,'sha256').hexdigest()!=validation.sha256:raise QnapServiceError('Published copy verification failed')
            # Hard-link this held inode atomically with no replacement.
            publish_held_file(fd,directory,self.current['archive'])
            os.fchown(fd,binding['uid'],binding['gid']);os.fsync(fd)
            self.current['published_identity']=file_identity(os.fstat(fd));self.current['publishing']=False;self._save()
        finally:
            if fd is not None:os.close(fd)
            if created:
                try:
                    info=os.stat(temporary,dir_fd=directory,follow_symlinks=False)
                    if [info.st_dev,info.st_ino]==created:os.unlink(temporary,dir_fd=directory);os.fsync(directory)
                except FileNotFoundError:pass
            os.close(directory)

    @contextmanager
    def _workspace(self):
        name='backup-'+self.current['request_id']
        self.current['workspace']=name;self._save()
        path=self.owner/name
        path.mkdir(mode=0o700)
        try:yield path
        finally:self._remove_workspace()

    def _remove_workspace(self):
        name=self.current.get('workspace')
        if not name:return
        if name!='backup-'+self.current['request_id']:raise QnapServiceError('Invalid private workspace identity')
        path=self.owner/name
        if path.exists() or path.is_symlink():
            info=path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077:
                raise QnapServiceError('Private workspace changed')
            shutil.rmtree(path);sync_directory(self.owner)
        self.current['workspace']=None;self._save()

    def _backup(self):
        log=None;success=False;error_message=None
        try:
            self.current['state']='RUNNING';self._save()
            log=self._open_log()
            def report(stage,value):
                if stage!='SNAPSHOT_MOUNT_INFO':log.write(stage+': '+str(value)+'\n');log.flush()
                stages={'CREATING':'CREATING_SNAPSHOT','CREATED':'CREATING_ARCHIVE','READ_ONLY_PLEX_DATA_CONFIRMED':'REMOVING_SNAPSHOT',
                        'WAITING_FOR_DELETION':'REMOVING_SNAPSHOT','CLEANUP_CONFIRMED':'REMOVING_SNAPSHOT'}
                if stage in stages:self._progress(stages[stage])
            service=self
            class DurableProbe(OwnedSnapshotProbe):
                def _change(self,function):
                    service._snapshot_record(self,**({'attempted':True} if function=='create_snapshot' else {'delete_requested':True}))
                    return super()._change(function)
                def _owned_row(self):
                    row=super()._owned_row()
                    if row:
                        service._snapshot_record(self,identifier=row['id'])
                    return row
                def _cleanup(self):
                    service._snapshot_record(self)
                    super()._cleanup()
                    service._snapshot_record(self,cleanup_confirmed=True)
            installation=self.discover()
            if asdict(installation)!=self.current['installation']:raise QnapServiceError('Plex installation changed before backup')
            with self._workspace() as workspace:
                output=Path(workspace)/'archive.tar.gz';validation=None
                last=[None,None]
                def progress(done,total):
                    percent=int(100*done/total)//5 if total else None
                    if [percent,total]!=last or done==0:
                        last[:]=[percent,total];self._progress('VERIFYING_ARCHIVE',done,total)
                def capture(identifier,baseline):
                    nonlocal validation
                    with open_snapshot_data(installation,identifier,baseline) as source:
                        try:
                            validation=capture_snapshot_archive(source,output,self.private_tar,preserve_symlinks=True,verification_progress=progress)
                        except (InvalidArchive,BackupArchiveError) as error:
                            raise QnapSnapshotReadError('BACKUP_VALIDATION: '+str(error)) from error
                        return source.storage_identity
                probe=DurableProbe(self.api,installation,inspect_data=capture,report=report)
                probe.name='pcc-backup-'+uuid.uuid4().hex
                probe.expire_minutes=1440
                result=probe.run()
                if result['error'] or not result['readable'] or not result['cleanup_confirmed']:
                    raise QnapServiceError('Backup verification/cleanup failed: '+str(result['error'] or result['cleanup_error']))
                self._publish(output,validation)
                log.write('SHA-256: '+validation.sha256+'\nFiles: '+str(validation.files)+'\nVerified bytes: '+str(validation.bytes_read)+'\n')
            log.write('Backup completed. Owned snapshot removal confirmed by API and ZFS.\n')
            success=True
        except BaseException as error:
            message=str(error) if isinstance(error,(QnapServiceError,QnapApiError,QnapRestoreError)) else type(error).__name__
            error_message=message
            if log:
                try:log.write('Backup failed: '+message+'\n')
                except OSError:pass
            # Local backup errors must not sign the user out of QNAP.
            # The keeper discards credentials only after NAS-confirmed expiry.
        finally:
            if log:
                try:log.flush();os.fsync(log.fileno());log.close()
                except OSError:
                    success=False;error_message='Operation log could not be finalized'
            try:self._finish(success,error_message)
            finally:
                with self.mutex:self.busy=False

    def _finish(self,success,error,*,reconciled=False):
        with self.mutex:
            snapshot=self.current.get('snapshot')
            unresolved=bool(snapshot and snapshot.get('attempted') and not snapshot.get('cleanup_confirmed')) or self.current.get('publishing',False) or bool(self.current.get('workspace')) or bool(self.current.get('published_identity') and not success and not reconciled)
            self.current['reconciled']=reconciled
            target='RECOVERY_REQUIRED' if unresolved else 'SUCCEEDED' if success else 'FAILED'
            stage='CLEANUP_REQUIRED' if unresolved else 'COMPLETED' if success else 'FAILED'
            # A terminal success is not visible until its history event is durable.
            self.current.update(state='RECOVERY_REQUIRED' if unresolved else 'RUNNING',stage=stage,
                                error=error,finished=self.clock())
            self._save()
            try:
                if self.current.get('event_state')!=target:
                    event=self.history.add('PUBLICATION_RECOVERY' if reconciled else 'BACKUP','SUCCESS' if reconciled else {'SUCCEEDED':'SUCCESS','FAILED':'FAILED','RECOVERY_REQUIRED':'WARNING'}[target],self.current.get('log','Operation log unavailable'),self.current['archive'])
                    self.current.update(event_recorded=event,event_state=target)
                self.current['state']=target;self._save()
            except Exception:
                self.current.update(state='RECOVERY_REQUIRED',stage='CLEANUP_REQUIRED',error='Final history reporting failed; review this operation')
                self._save()

    def history_rows(self):
        return [{**row,'id':row['id']+EVENT_BASE} for row in self.history.list()[:1000]]

    def history_detail(self,identifier):
        if type(identifier) is not int or identifier<=EVENT_BASE:raise QnapServiceError('Invalid history identity')
        row=self.history.detail(identifier-EVENT_BASE)
        if row is None:return None
        if row['kind']=='QNAP_LOGIN':
            row['id']+=EVENT_BASE;return row
        filename=row['log']
        if not re.fullmatch(r'plex-(?:backup|restore)-[0-9_-]+-[0-9a-f]{8}\.log',filename):
            row['log']='Operation log is unavailable.'
        else:
            try:
                binding,path=self._binding();directory=os.open(path/'Logs',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:
                    if [os.fstat(directory).st_dev,os.fstat(directory).st_ino]!=binding['logs_identity']:raise QnapServiceError('Logs folder changed')
                    fd=os.open(filename,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                finally:os.close(directory)
                with os.fdopen(fd,'r',errors='replace') as stream:
                    info=os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size>4*1024*1024:raise QnapServiceError('Log is too large')
                    row['log']=stream.read(4*1024*1024+1)
            except (OSError,QnapServiceError):row['log']='Permanent operation log is unavailable; it may have been removed manually.'
        row['id']+=EVENT_BASE;return row

    def clear_history(self,ids):
        if not isinstance(ids,list) or not ids or len(ids)>10000 or any(type(i)is not int or i<=EVENT_BASE for i in ids):raise QnapServiceError('Choose valid history records')
        self.history.clear([i-EVENT_BASE for i in ids]);return {'cleared':len(ids)}

    def recovery(self):
        operation=self.operation()['operation'];publication=self.operation()['publication']
        snapshot=self.current.get('snapshot') if self.current else None
        state='NONE' if not operation['snapshot_id'] else 'UNKNOWN'
        if operation['snapshot_id'] and self.api:
            try:
                rows=self.api.snapshots(snapshot['volume_id'])
                row=next((row for row in rows if row['name']==snapshot['name']),None)
                if row:state='PRESENT'
                elif snapshot.get('storage') and snapshot['storage'] not in storage_snapshots(self.discover()):state='ABSENT'
            except Exception:pass
        return {'platform':'QNAP',**{key:operation[key] for key in ('phase','kind','snapshot_id','outcome')},'snapshot_state':state,
                'publication':publication,'removal_supported':False,'removal_available':False,'publication_resolution_supported':False}

    def recover(self):
        with self.mutex:
            if self.busy or self.auth_busy or self.api is None or not self.current or self.current['state']!='RECOVERY_REQUIRED':
                raise QnapServiceError('Authenticate before recovering the recorded operation')
            self.busy=True
            try:threading.Thread(target=self._recover,name='pcc-qnap-recovery',daemon=False).start()
            except Exception:self.busy=False;raise
            return {'accepted':True}

    def _recover_snapshot(self):
        snapshot=self.current.get('snapshot');installation=self.discover()
        if snapshot and not snapshot.get('cleanup_confirmed'):
            if (installation.dataset,installation.volume_id)!=(snapshot['dataset'],snapshot['volume_id']):raise QnapServiceError('Snapshot storage binding changed')
            probe=OwnedSnapshotProbe(self.api,installation)
            probe.name=snapshot['name'];probe.identifier=snapshot['identifier'];probe.storage_identifier=snapshot['storage']
            probe.baseline_ids=set(snapshot['baseline_ids']);probe.baseline_storage=set(snapshot['baseline_storage'])
            probe.attempted=snapshot['attempted'];probe.delete_requested=snapshot['delete_requested']
            row=probe._owned_row()
            if row:
                if probe.identifier is None:probe.identifier=row['id']
                if probe.storage_identifier is None:
                    with open_snapshot_data(installation,probe.identifier,probe.baseline_storage) as source:probe.storage_identifier=source.storage_identity
                self._snapshot_record(probe,delete_requested=True)
                probe._cleanup()
            else:
                storage=storage_snapshots(installation)
                if probe.storage_identifier:
                    if probe.storage_identifier in storage:raise QnapServiceError('Snapshot is still present in ZFS')
                elif storage-probe.baseline_storage:
                    raise QnapServiceError('Snapshot absence cannot be proven; inspect the recorded QNAP snapshot manually')
                elif not probe.delete_requested:
                    # An uncertain creation can complete asynchronously. Observe
                    # successful native inventories for a full grace window.
                    for attempt in range(60):
                        if probe._owned_row() is not None or storage_snapshots(installation)-probe.baseline_storage:
                            raise QnapServiceError('Snapshot appeared; repeat explicit recovery to resolve its identity')
                        time.sleep(1)
            self._snapshot_record(probe,cleanup_confirmed=True)

    def _recover(self):
        try:
            if self.current['kind']=='RESTORE':
                self.restore.recover();return
            self._recover_snapshot()
            self._remove_workspace()
            if self.current.get('publishing') or self.current.get('published_identity'):
                binding,path=self._binding();target=path/self.current['archive']
                if target.exists() or target.is_symlink():
                    fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                    with os.fdopen(fd,'rb') as stream:
                        info=os.fstat(stream.fileno())
                        expected=self.current.get('published_identity')
                        identity=[expected['device'],expected['inode']] if expected else self.current.get('temporary_identity')
                        if not stat.S_ISREG(info.st_mode) or [info.st_dev,info.st_ino]!=identity or hashlib.file_digest(stream,'sha256').hexdigest()!=self.current['sha256']:
                            raise QnapServiceError('Published archive identity cannot be reconciled')
                        os.fchown(stream.fileno(),binding['uid'],binding['gid']);os.fsync(stream.fileno())
                    self._remove_owned_temporary(path)
                    self.current['publishing']=False;self._save();self._finish(False,'Interrupted backup archive fully reverified; original operation remains failed',reconciled=True)
                    return
                self._remove_owned_temporary(path)
                self.current['publishing']=False;self._save()
            self._finish(False,'Interrupted backup cleanup completed; create a fresh backup')
        except BaseException as error:
            self.current.update(error=str(error) if isinstance(error,(QnapServiceError,QnapApiError,QnapRestoreError)) else type(error).__name__)
            self._save()
        finally:
            with self.mutex:self.busy=False

    def _remove_owned_temporary(self,path):
        directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            try:info=os.stat(self.current['temporary'],dir_fd=directory,follow_symlinks=False)
            except FileNotFoundError:return
            if (not stat.S_ISREG(info.st_mode) or [info.st_dev,info.st_ino]!=self.current.get('temporary_identity')):
                raise QnapServiceError('Temporary file identity cannot be proven; manual inspection is required')
            os.unlink(self.current['temporary'],dir_fd=directory);os.fsync(directory)
        finally:os.close(directory)

    def integration(self):
        with self.mutex:
            info=self.info();operation=self.operation()['operation']
            result={'schema':2,'platform':'QNAP','checked_at':datetime.now(timezone.utc).isoformat(),
                    'backup_available':bool(info['authenticated'] and info['location'] and not info['recovery_required'] and not info['restore_review'] and not info['restore_preparation']),
                    'restore_available':bool(info['authenticated'] and info['location'] and not info['recovery_required'] and not info['restore_review']),'execution_reason':'QNAP_BACKUP_CONNECTED',
                    'plex':{'configured':True,'state':'UNAVAILABLE','app_state':'UNKNOWN'},
                    'archives':{'configured':info['location'] is not None,'state':'NOT_CONFIGURED','count':None},
                    'snapshot':{'configured':info['authenticated'],'state':'NOT_CONFIGURED'},
                    'operation':{'phase':operation['phase'],'state':'RECOVERY_REQUIRED' if info['recovery_required'] else 'ACTIVE' if info['busy'] else 'IDLE'}}
            try:
                state=plex_process_state(self.discover())
                if state in ('RUNNING','STOPPED'):result['plex'].update(state='READ_VERIFIED',app_state=state)
            except Exception:pass
            if info['location']:
                try:result['archives'].update(state='LIST_VERIFIED',count=len(self._archives()))
                except Exception:result['archives']['state']='UNAVAILABLE'
            if info['authenticated']:
                result['snapshot']['state']='NO_RECORDED_SNAPSHOT' if not operation['snapshot_id'] else self.recovery()['snapshot_state']
            return result

    def dispatch(self,action,data):
        if action=='restore_validate':return self.restore.start_validation(data)
        if action=='restore_readiness':return self.restore.readiness()
        if action=='restore_execute':return self.restore.execute(data)
        if action=='restore_cancel':return self.restore.cancel()
        if action=='restore_review':return self.restore.retained_action(data)
        if action=='info':return self.info()
        if action=='integration':return self.integration()
        if action=='shares':return [{key:row[key] for key in ('id','name')} for row in self.shares()]
        if action=='auth':return self.authenticate(data)
        if action=='configure':return self.configure(data)
        if action=='archives':return [self._wire(row) for row in self._archives()]
        if action=='plan':return self.plan()
        if action=='operation':return self.operation()
        if action=='status':return self.status(data.get('request_id'))
        if action=='backup':return self.start_backup(data['request'],data.get('timezone','Europe/London'))
        if action=='recovery':return self.recovery()
        if action=='recover':
            if data!={'confirmed':True}:raise QnapServiceError('Confirm recovery of this application-owned operation')
            return self.recover()
        if action=='panel_event':
            from .qnap_eventlog import panel_event
            return panel_event(self,data)
        if action=='history':return self.history_rows()
        if action=='history_detail':return self.history_detail(data['id'])
        if action=='history_clear':return self.clear_history(data['ids'])
        raise QnapServiceError('Unsupported QNAP operation')
