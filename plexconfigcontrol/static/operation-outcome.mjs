// Historical coordinator results only. Never infer archive validity from listing.
const codes=new Set(['BACKUP_IN_PROGRESS','BACKUP_COMPLETED','BACKUP_FAILED','BACKUP_PUBLISHED_REVIEW',
  'BACKUP_PUBLICATION_UNCERTAIN','BACKUP_RECONCILED','BACKUP_INTERRUPTED',
  'RESTORE_IN_PROGRESS','RESTORE_COMPLETED','RESTORE_FAILED_UNCHANGED','RESTORE_ROLLBACK_VERIFIED',
  'RESTORE_RECOVERY_UNCONFIRMED','RESTORE_VERIFIED_REPORTING_FAILED','RESTORE_INTERRUPTED']);
const name=/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.tar\.gz$/;
export function normalizeOutcome(value){
  if(value==null)return null; // Older persisted records have no outcome.
  if(typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==2||
     !Object.hasOwn(value,'code')||!Object.hasOwn(value,'archive')||!codes.has(value.code))return undefined;
  if(!(['BACKUP_INTERRUPTED','RESTORE_INTERRUPTED'].includes(value.code)&&value.archive===null)&&
     !(typeof value.archive==='string'&&name.test(value.archive)&&!/[\r\n]/.test(value.archive)))return undefined;
  return{code:value.code,archive:value.archive};
}
export function recoveryOutcome(data,language='en'){
  const outcome=normalizeOutcome(data?.outcome),pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  if(!outcome||!['BACKUP','RESTORE'].includes(data.kind)||!outcome.code.startsWith(data.kind+'_')||
     !['RECOVERY_REQUIRED','FAILED'].includes(data.phase))return '';
  const messages={
    RESTORE_FAILED_UNCHANGED:tx('Restore failed before configuration writes. Any recorded snapshot or temporary files still require review.',
      'Restore nie powiodło się przed zapisem konfiguracji. Zapisany snapshot lub pliki tymczasowe mogą nadal wymagać sprawdzenia.'),
    RESTORE_ROLLBACK_VERIFIED:tx('Rollback was verified. Restore remains FAILED; review any remaining snapshot or cleanup. Plex was not started by the panel.',
      'Rollback został zweryfikowany. Restore nadal ma wynik FAILED; sprawdź pozostały snapshot i sprzątanie. Panel nie uruchomił Plex.'),
    RESTORE_RECOVERY_UNCONFIRMED:tx('Configuration may have changed. Recovery could not be verified. Do not start Plex until the configuration is checked.',
      'Konfiguracja mogła się zmienić. Nie udało się zweryfikować odzyskania danych. Nie uruchamiaj Plex przed sprawdzeniem konfiguracji.'),
    RESTORE_VERIFIED_REPORTING_FAILED:tx('Restored configuration and snapshot removal were verified, but final reporting failed. Full operation review is still required.',
      'Zweryfikowano przywróconą konfigurację i usunięcie snapshotu, ale zapis raportu nie powiódł się. Nadal trzeba sprawdzić pełny wynik operacji.'),
    RESTORE_INTERRUPTED:tx('Restore was interrupted. Its final result is unconfirmed; recovery checks are required before starting Plex.',
      'Restore zostało przerwane. Nie potwierdzono wyniku końcowego; przed uruchomieniem Plex trzeba sprawdzić stan odzyskiwania.'),
    BACKUP_PUBLISHED_REVIEW:tx('An archive was saved before the operation failed. This is not a successful Backup; verify the retained archive before use.',
      'Archiwum zostało zapisane przed wystąpieniem błędu. Backup nie zakończył się sukcesem; przed użyciem zweryfikuj zachowane archiwum.'),
    BACKUP_PUBLICATION_UNCERTAIN:tx('Archive saving could not be confirmed. Check the recorded files before using a copy.',
      'Nie udało się potwierdzić zapisu archiwum. Przed użyciem kopii sprawdź pliki zapisane w szczegółach operacji.'),
    BACKUP_FAILED:tx('Backup failed. No new archive has been confirmed.',
      'Backup nie powiódł się. Nie potwierdzono utworzenia nowego archiwum.'),
    BACKUP_INTERRUPTED:tx('Backup was interrupted. Its final result is unconfirmed; recovery checks are required.',
      'Backup został przerwany. Nie potwierdzono jego wyniku końcowego; wymagane jest sprawdzenie stanu odzyskiwania.'),
  };
  return messages[outcome.code]||'';
}
function executionMatches(snapshot,kind,success=false){
  const job=snapshot?.execution;
  if(job==null)return true; // Legacy/direct coordinator result, no admitted job.
  return typeof job==='object'&&job.kind===kind&&typeof job.request_id==='string'&&/^[0-9a-f]{32}$/.test(job.request_id)&&
    snapshot.operation?.execution_request_id===job.request_id&&snapshot.execution_bound!==false&&
    ['QUEUED','RUNNING','SUCCEEDED','FAILED','RECOVERY_REQUIRED'].includes(job.state)&&(!success||job.state==='SUCCEEDED');
}
export function backupResult(snapshot,language='en'){
  const operation=snapshot?.operation,outcome=normalizeOutcome(operation?.outcome),progress=snapshot?.progress;
  if(!executionMatches(snapshot,'BACKUP'))return '';
  if(!outcome||operation.kind!=='BACKUP'||!['FAILED','SUCCESS'].includes(operation.phase)||operation.snapshot_id!==null||
     snapshot.publication?.pending!==false||snapshot.publication?.status!=='NONE'||
     snapshot.publication?.archive!==null||snapshot.publication?.temporary_file!==null)return '';
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  if(executionMatches(snapshot,'BACKUP',true)&&outcome.code==='BACKUP_COMPLETED'&&operation.phase==='SUCCESS'&&progress?.operation==='BACKUP'&&
     progress.stage==='COMPLETED'&&progress.active===false&&Number.isFinite(progress.finished))
    return tx('Last Backup completed successfully: ','Ostatni Backup zakończył się sukcesem: ')+outcome.archive;
  if(operation.phase==='FAILED'&&outcome.code==='BACKUP_RECONCILED')
    return tx('The retained archive was fully reverified. The original Backup remains FAILED: ',
      'Zachowane archiwum zostało ponownie w pełni zweryfikowane. Pierwotny Backup nadal ma wynik FAILED: ')+outcome.archive;
  if(operation.phase==='FAILED'&&outcome.code==='BACKUP_FAILED')return recoveryOutcome(operation,language);
  return '';
}

export function restoreResult(snapshot,language='en'){
  const operation=snapshot?.operation,outcome=normalizeOutcome(operation?.outcome),progress=snapshot?.progress;
  if(!executionMatches(snapshot,'RESTORE'))return '';
  if(!outcome||operation.kind!=='RESTORE'||operation.snapshot_id!==null||
     snapshot.publication?.pending!==false||snapshot.publication?.status!=='NONE'||
     snapshot.publication?.archive!==null||snapshot.publication?.temporary_file!==null)return '';
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  if(executionMatches(snapshot,'RESTORE',true)&&operation.phase==='SUCCESS'&&outcome.code==='RESTORE_COMPLETED'&&progress?.operation==='RESTORE'&&
     progress.stage==='COMPLETED'&&progress.active===false&&Number.isFinite(progress.finished))
    return tx('Last Restore completed successfully. Plex was not started automatically. Archive: ',
      'Ostatnie Restore zakończyło się sukcesem. Plex nie został uruchomiony automatycznie. Archiwum: ')+outcome.archive;
  if(operation.phase==='FAILED'&&outcome.code==='RESTORE_FAILED_UNCHANGED')return recoveryOutcome(operation,language);
  return '';
}
