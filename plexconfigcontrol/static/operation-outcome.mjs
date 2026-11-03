// Historical coordinator results only. Never infer archive validity from listing.
const codes=new Set(['BACKUP_IN_PROGRESS','BACKUP_COMPLETED','BACKUP_FAILED','BACKUP_PUBLISHED_REVIEW',
  'BACKUP_PUBLICATION_UNCERTAIN','BACKUP_RECONCILED','BACKUP_INTERRUPTED']);
const name=/^TrueNASPlexConfig_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.tar\.gz$/;
export function normalizeOutcome(value){
  if(value==null)return null; // Older persisted records have no outcome.
  if(typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==2||
     !Object.hasOwn(value,'code')||!Object.hasOwn(value,'archive')||!codes.has(value.code))return undefined;
  if(!(value.code==='BACKUP_INTERRUPTED'&&value.archive===null)&&
     !(typeof value.archive==='string'&&name.test(value.archive)&&!/[\r\n]/.test(value.archive)))return undefined;
  return{code:value.code,archive:value.archive};
}
export function recoveryOutcome(data,language='en'){
  const outcome=normalizeOutcome(data?.outcome),pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  if(!outcome||data.kind!=='BACKUP'||!['RECOVERY_REQUIRED','FAILED'].includes(data.phase))return '';
  const messages={
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
export function backupResult(snapshot,language='en'){
  const operation=snapshot?.operation,outcome=normalizeOutcome(operation?.outcome),progress=snapshot?.progress;
  if(!outcome||operation.kind!=='BACKUP'||!['FAILED','SUCCESS'].includes(operation.phase)||operation.snapshot_id!==null||
     snapshot.publication?.pending!==false||snapshot.publication?.status!=='NONE'||
     snapshot.publication?.archive!==null||snapshot.publication?.temporary_file!==null)return '';
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  if(outcome.code==='BACKUP_COMPLETED'&&operation.phase==='SUCCESS'&&progress?.operation==='BACKUP'&&
     progress.stage==='COMPLETED'&&progress.active===false&&Number.isFinite(progress.finished))
    return tx('Last Backup completed successfully: ','Ostatni Backup zakończył się sukcesem: ')+outcome.archive;
  if(operation.phase==='FAILED'&&outcome.code==='BACKUP_RECONCILED')
    return tx('The retained archive was fully reverified. The original Backup remains FAILED: ',
      'Zachowane archiwum zostało ponownie w pełni zweryfikowane. Pierwotny Backup nadal ma wynik FAILED: ')+outcome.archive;
  if(operation.phase==='FAILED'&&outcome.code==='BACKUP_FAILED')return recoveryOutcome(operation,language);
  return '';
}
