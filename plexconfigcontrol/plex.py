"""Read-only Plex state adapter. Never starts or stops an application."""
from datetime import datetime, timezone

class PlexStatus:
    def __init__(self, api, app_name='plex'):
        self.api=api
        self.app_name=app_name

    def read(self):
        checked=datetime.now(timezone.utc).isoformat()
        try:
            rows=self.api.call('app.query', [['name','=',self.app_name]])
            if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
                raise ValueError('Unexpected application response')
            row=rows[0]
            if row.get('name')!=self.app_name:
                raise ValueError('Application identity mismatch')
            state=row.get('state')
            if state not in ('RUNNING','STOPPED','DEPLOYING','STOPPING','CRASHED'):
                state='UNKNOWN'
            return {'state':state,'checked_at':checked,'available':state!='UNKNOWN',
                    'restore_allowed':state=='STOPPED'}
        except Exception:
            # Do not expose arbitrary API exception strings: they may contain
            # transport URLs, authentication data or other host information.
            return {'state':'UNKNOWN','checked_at':checked,'available':False,
                    'restore_allowed':False}
