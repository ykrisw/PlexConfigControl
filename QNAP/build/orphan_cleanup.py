"""Installer-only cleanup of positively identified orphan PCC processes.

Never kills by port, generic python name, or a stale PID alone. SIGTERM only.
A normally installed PCC must first pass its own maintenance/recovery guard.
"""
import os
import signal
import subprocess
import sys
import time


def identify(pid,proc='/proc',prefix='/share/'):
    try:
        base=os.path.join(proc,str(pid))
        uid=os.stat(base).st_uid
        raw=open(os.path.join(base,'cmdline'),'rb').read(16384)
        args=[os.fsdecode(arg) for arg in raw.split(b'\0') if arg]
        if len(args)!=5 or args[1:3]!=['-I','-S'] or args[4] not in ('--supervise','--web-child'):return None
        root=os.path.dirname(args[3])
        if (not root.startswith(prefix) or not root.endswith('/.qpkg/PCC')
                or os.path.normpath(root)!=root or os.path.basename(args[3])!='launcher.py'
                or args[0]!=root+'/python/bin/python3'):return None
        if args[4]=='--supervise' and uid!=0:return None
        if args[4]=='--web-child' and not 60000<=uid<61000:return None
        executable=os.readlink(os.path.join(base,'exe'))
        plain=executable.removesuffix(' (deleted)')
        if plain not in (root+'/python/bin/python3',root+'/python/bin/python3.12'):return None
        text=open(os.path.join(base,'stat')).read();fields=text[text.rfind(')')+2:].split()
        if fields[0]=='Z':return None
        return (int(pid),fields[19],uid,root,args[4],executable)
    except (OSError,ValueError,IndexError):return None


def stop_identified(record,*,proc='/proc',prefix='/share/',pause=time.sleep,terminate=None,attempts=40):
    terminate=terminate or (lambda pid:os.kill(pid,signal.SIGTERM))
    pid=record[0]
    if identify(pid,proc,prefix)!=record:return
    for attempt in range(attempts):
        if identify(pid,proc,prefix)!=record:return
        if attempt%5==0:terminate(pid)
        pause(1)
    raise RuntimeError('Identified orphan PCC process did not stop; installation aborted without a forced kill')


def cleanup(*,proc='/proc',prefix='/share/'):
    records=[identify(pid,proc,prefix) for pid in os.listdir(proc) if pid.isdecimal()]
    for record in (value for value in records if value and value[4]=='--supervise'):
        root=record[3];python=root+'/python/bin/python3';launcher=root+'/launcher.py'
        if not record[5].endswith(' (deleted)') and all(os.path.isfile(path) for path in (python,launcher,root+'/var/owner/service.json')):
            # Unregistered but intact: retain its normal recovery protections.
            subprocess.run([python,'-I','-S',launcher,'--can-maintain'],check=True)
            subprocess.run([python,'-I','-S',launcher,'--stop'],check=True)
            stop_identified(record,proc=proc,prefix=prefix)
        else:
            stop_identified(record,proc=proc,prefix=prefix)
    # Only remaining PCC web children; never touch an unrelated listener.
    for pid in os.listdir(proc):
        if not pid.isdecimal():continue
        record=identify(pid,proc,prefix)
        if record and record[4]=='--web-child':
            active=[identify(value,proc,prefix) for value in os.listdir(proc) if value.isdecimal()]
            if any(value and value[3]==record[3] and value[4]=='--supervise' for value in active):
                raise RuntimeError('PCC supervisor is still active; no web child was stopped')
            stop_identified(record,proc=proc,prefix=prefix,attempts=30)


if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('PCC installer process cleanup requires root')
    cleanup()
