"""History-log downloads generated in memory; no files left on the NAS."""
import io
import zipfile

class MissingHistoryEvent(LookupError):
    pass

def history_logs(history, ids, max_bytes=32*1024*1024):
    if (not isinstance(ids,list) or not ids or len(ids)>1000
            or any(type(i) is not int or i<=0 for i in ids)
            or len(set(ids))!=len(ids)):
        raise ValueError('Select distinct history events')
    logs=[]
    total=0
    for event_id in ids:
        event=history.detail(event_id)
        if event is None:
            raise MissingHistoryEvent('Selected history event no longer exists')
        data=event['log'].encode('utf-8')
        total+=len(data)
        if total>max_bytes:
            raise ValueError('Download too large; select fewer events')
        # User-supplied names/paths never become ZIP entries.
        logs.append((f'Event_{event_id}.log',data))
    if len(logs)==1:
        name,data=logs[0]
        return name,'text/plain; charset=utf-8',data
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in logs:
            archive.writestr(name,data)
    return 'PlexConfigControl_Logs.zip','application/zip',output.getvalue()
