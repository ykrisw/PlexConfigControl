const messages={
 TLS_UNTRUSTED:['TrueNAS uses an untrusted certificate or a different CA.','TrueNAS używa niezaufanego certyfikatu lub innej CA.'],
 TLS_HOSTNAME:['The TrueNAS certificate does not match the configured address.','Certyfikat TrueNAS nie pasuje do skonfigurowanego adresu.'],
 TLS_EXPIRED:['The TrueNAS certificate is expired or not yet valid.','Certyfikat TrueNAS wygasł lub nie jest jeszcze ważny.'],
 TLS_CA_UNAVAILABLE:['The saved TrueNAS trust file is unavailable.','Zapisany plik zaufania TrueNAS jest niedostępny.'],
 TLS_INVALID:['The TrueNAS TLS connection could not be verified.','Nie można zweryfikować połączenia TLS z TrueNAS.'],
 API_UNREACHABLE:['The TrueNAS API is unreachable.','API TrueNAS jest nieosiągalne.'],
 API_AUTHENTICATION:['TrueNAS rejected the application API credentials.','TrueNAS odrzucił dane uwierzytelniające API aplikacji.'],
};
export function renderConnectionNotice(root,code,language='en'){
 let notice=root.querySelector('[data-api-connection-error]');
 if(!notice){notice=root.ownerDocument.createElement('p');notice.className='pcc-notice';notice.dataset.apiConnectionError='';notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');root.querySelector('.pcc-plex')?.after(notice);}
 const message=messages[code];notice.hidden=!message;
 const text=message?message[language==='pl'?1:0]+' '+(language==='pl'?'Panel i zapisane dane pozostają dostępne. W kreatorze instalacji wybierz „Napraw połączenie”.':'The panel and saved data remain available. Open Setup and choose “Repair connection”.'):'';
 if(notice.textContent!==text)notice.textContent=text;
}
