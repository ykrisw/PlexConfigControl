"""UI translation catalog. Stable machine statuses and filenames stay unchanged."""
CATALOG = {
'en': {
'setup_incomplete':'Folder setup could not be confirmed. Inspect and manually rename the new backup folder before retrying. No files were automatically removed.',
'unsafe_destination':'Choose a valid destination outside protected Plex and application storage, without symbolic links.',
'destination_changed':'The selected folder was replaced or moved. Check the location before continuing; no replacement folder was adopted.',
'setup_access_required':'Access was denied. Check access for the app and your SMB user. No existing permissions were changed.',
'setup_parent_unavailable':'The selected parent folder is unavailable. Select an existing folder; missing parent folders will not be created.',
'setup_failed':'Setup could not be confirmed. Check the selected location. No files were automatically removed.',
'dashboard':'Dashboard','backup':'Backup','restore':'Restore','history':'History','settings':'Settings',
'account':'Account','active':'ACTIVE','inactive':'INACTIVE','plex_server':'Plex Server','running':'RUNNING','stopped':'STOPPED','unknown':'UNKNOWN',
'change_password':'Change Password','log_out':'Log Out','current_password':'Current Password','new_password':'New Password','confirm_password':'Confirm New Password','save_password':'Save Password','cancel':'Cancel',
'upload_photo':'Upload Photo','remove_photo':'Remove Photo','language':'Language','appearance':'Appearance','theme':'Theme','light':'Light','dark':'Dark','system':'System','about':'About','application':'Application','version':'Version','created_by':'Created by','details':'Details',
'create_new_backup':'Create a new backup','create_backup':'Create Backup','existing_backups':'Existing Backups','refresh':'Refresh','delete_selected_archives':'Delete Selected Archives','important':'Important','backup_description':'Create and verify a new copy of your Plex configuration.','backup_notice':'Existing backups will not be deleted automatically. Each completed backup is verified before it becomes available.',
'archive_validation':'Archive Validation','validate_archive':'Validate Archive','select_backup_archive':'Select Backup Archive','select_and_validate':'Select an archive and start validation before continuing.','not_started':'NOT STARTED','valid':'VALID','failed':'FAILED','success':'SUCCESS',
'waiting_for_plex':'Waiting for Plex to stop…','stop_manually':'Stop Plex manually in TrueNAS Apps to continue.','type_restore':'Type RESTORE to confirm','restore_configuration':'Restore Configuration','start_manually':'Plex remains stopped. Start Plex manually in TrueNAS.',
'overwrite_existing':'Overwrite Existing','create_dated_copy':'Create New Dated Copy','one_archive_prompt':'One backup archive exists. Overwrite it or create a new dated copy?',
'operations_events':'Operations & Events','total_operations':'Total Operations','successful':'Successful','all':'All','download_logs':'Download Logs','clear_selected':'Clear Selected','operation_log':'Operation Log','duration':'Duration','elapsed':'Elapsed',
'clear_history_confirmation':'Permanently delete selected panel history? Files in backup folder/Logs will remain.','delete_archives_confirmation':'Permanently delete the selected backup archives?',
'remove_temporary_snapshot':'Remove Temporary Snapshot','remove_emergency_snapshot':'Remove Emergency Snapshot','snapshot_confirmation':'Permanently remove this snapshot? This cannot be undone.','rename_folder':'The selected backup folder already exists. Rename it manually, then retry setup. Its contents and permissions have not been changed.',
'backup_in_progress':'Backup in progress','restore_in_progress':'Restore in progress','preparing':'Preparing','creating_snapshot':'Creating temporary snapshot','creating_archive':'Creating archive','verifying_archive':'Verifying archive','removing_snapshot':'Removing temporary snapshot','backup_completed':'Backup completed successfully','backup_failed':'Backup failed','restore_completed':'Restore completed successfully','restore_failed':'Restore failed','cleanup_required':'Cleanup required before another operation can start.',
'wrong_password':'Incorrect password','password_mismatch':'New passwords do not match.','sign_in':'Sign In','password':'Password','login_blocked':'Sign-in temporarily blocked','preview':'Development preview',
},
'pl': {
'setup_incomplete':'Nie potwierdzono utworzenia folderów. Sprawdź i ręcznie zmień nazwę nowego folderu kopii przed ponowieniem. Nie usunięto automatycznie żadnych plików.',
'unsafe_destination':'Wybierz poprawną lokalizację poza chronioną konfiguracją Plex i danymi aplikacji, bez linków symbolicznych.',
'destination_changed':'Wybrany folder został podmieniony lub przeniesiony. Sprawdź lokalizację przed kontynuowaniem; aplikacja nie przejęła innego folderu.',
'setup_access_required':'Odmówiono dostępu. Sprawdź dostęp aplikacji i swojego użytkownika SMB. Nie zmieniono istniejących uprawnień.',
'setup_parent_unavailable':'Wybrany folder nadrzędny jest niedostępny. Wybierz istniejący folder; aplikacja nie utworzy brakujących folderów nadrzędnych.',
'setup_failed':'Nie udało się potwierdzić konfiguracji folderów. Sprawdź wybraną lokalizację. Nie usunięto automatycznie żadnych plików.',
'dashboard':'Pulpit','backup':'Kopia zapasowa','restore':'Przywracanie','history':'Historia','settings':'Ustawienia',
'account':'Konto','active':'AKTYWNE','inactive':'NIEAKTYWNE','plex_server':'Serwer Plex','running':'URUCHOMIONY','stopped':'ZATRZYMANY','unknown':'NIEZNANY',
'change_password':'Zmień hasło','log_out':'Wyloguj się','current_password':'Obecne hasło','new_password':'Nowe hasło','confirm_password':'Potwierdź nowe hasło','save_password':'Zapisz hasło','cancel':'Anuluj',
'upload_photo':'Dodaj lub zmień zdjęcie','remove_photo':'Usuń zdjęcie','language':'Język','appearance':'Wygląd','theme':'Motyw','light':'Jasny','dark':'Ciemny','system':'Systemowy','about':'O aplikacji','application':'Aplikacja','version':'Wersja','created_by':'Autor','details':'Szczegóły',
'create_new_backup':'Utwórz nową kopię zapasową','create_backup':'Utwórz kopię','existing_backups':'Istniejące kopie zapasowe','refresh':'Odśwież','delete_selected_archives':'Usuń zaznaczone archiwa','important':'Ważne','backup_description':'Utwórz i zweryfikuj kopię konfiguracji Plexa.','backup_notice':'Istniejące kopie nie są usuwane automatycznie. Każda nowa kopia jest weryfikowana przed udostępnieniem.',
'archive_validation':'Weryfikacja archiwum','validate_archive':'Zweryfikuj archiwum','select_backup_archive':'Wybierz archiwum kopii','select_and_validate':'Wybierz archiwum i rozpocznij weryfikację przed kontynuowaniem.','not_started':'NIEROZPOCZĘTA','valid':'POPRAWNE','failed':'BŁĄD','success':'SUKCES',
'waiting_for_plex':'Oczekiwanie na zatrzymanie Plexa…','stop_manually':'Aby kontynuować, zatrzymaj ręcznie Plexa w aplikacjach TrueNAS.','type_restore':'Wpisz RESTORE, aby potwierdzić','restore_configuration':'Przywróć konfigurację','start_manually':'Plex pozostaje zatrzymany. Uruchom go ręcznie w TrueNAS.',
'overwrite_existing':'Nadpisz istniejącą kopię','create_dated_copy':'Utwórz kolejną datowaną kopię','one_archive_prompt':'Istnieje jedna kopia zapasowa. Nadpisać ją czy utworzyć kolejną datowaną kopię?',
'operations_events':'Operacje i zdarzenia','total_operations':'Wszystkie operacje','successful':'Udane','all':'Wszystkie','download_logs':'Pobierz logi','clear_selected':'Wyczyść zaznaczone','operation_log':'Log operacji','duration':'Czas trwania','elapsed':'Upłynęło',
'clear_history_confirmation':'Trwale usunąć zaznaczoną historię panelu? Pliki w folderze kopii/Logs pozostaną.','delete_archives_confirmation':'Trwale usunąć zaznaczone archiwa kopii zapasowych?',
'remove_temporary_snapshot':'Usuń tymczasowy snapshot','remove_emergency_snapshot':'Usuń snapshot awaryjny','snapshot_confirmation':'Trwale usunąć ten snapshot? Tej operacji nie można cofnąć.','rename_folder':'Wybrany folder kopii już istnieje. Zmień ręcznie jego nazwę i ponów konfigurację. Jego zawartość i uprawnienia nie zostały zmienione.',
'backup_in_progress':'Tworzenie kopii w toku','restore_in_progress':'Przywracanie w toku','preparing':'Przygotowanie','creating_snapshot':'Tworzenie tymczasowego snapshotu','creating_archive':'Tworzenie archiwum','verifying_archive':'Weryfikacja archiwum','removing_snapshot':'Usuwanie tymczasowego snapshotu','backup_completed':'Kopia zapasowa zakończona pomyślnie','backup_failed':'Tworzenie kopii nie powiodło się','restore_completed':'Przywracanie zakończone pomyślnie','restore_failed':'Przywracanie nie powiodło się','cleanup_required':'Przed kolejną operacją wymagane jest zakończenie sprzątania.',
'wrong_password':'Nieprawidłowe hasło','password_mismatch':'Nowe hasła nie są identyczne.','sign_in':'Zaloguj się','password':'Hasło','login_blocked':'Logowanie tymczasowo zablokowane','preview':'Wersja rozwojowa',
}}
LANGUAGES = {'en':'English','pl':'Polski'}

def translate(key, language='en'):
    if language not in LANGUAGES:
        raise ValueError('Unsupported language')
    return CATALOG[language][key]
