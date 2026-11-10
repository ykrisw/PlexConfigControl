"""Cross-platform, in-memory desktop installer for the full TrueNAS app."""
import base64
import codecs
import hashlib
import json
from pathlib import Path
import queue
import re
import shlex
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

import paramiko

PREFIX = 'PCC_SETUP_EVENT:'
STAGES = {
    'CONNECT': ('Connecting to TrueNAS', 'Łączenie z TrueNAS'),
    'UPLOAD': ('Sending the installer', 'Przesyłanie instalatora'),
    'CHECK_REQUIREMENTS': ('Checking requirements', 'Sprawdzanie wymagań'),
    'BUILD_PANEL': ('Building the panel image', 'Budowanie obrazu panelu'),
    'BUILD_WORKER': ('Building the backup worker', 'Budowanie obrazu wykonującego kopie'),
    'CHECK_RUNTIME': ('Checking Plex compatibility', 'Sprawdzanie zgodności z Plexem'),
    'REGISTER_APP': ('Installing in TrueNAS Apps', 'Instalowanie w TrueNAS Apps'),
    'VERIFY_APP': ('Waiting for the application to be ready', 'Sprawdzanie gotowości aplikacji'),
}


class SetupError(Exception):
    pass


class Cancelled(Exception):
    pass


def classify_prompt(event):
    text = event.get('message', '')
    if event.get('confirmation'):
        return 'confirmation'
    if event.get('choices'):
        return 'dataset'
    if event.get('secret'):
        return 'password-confirm' if re.search('Powtórz|Repeat|Confirm', text) else 'panel-password'
    if re.search('folder|Folder', text):
        return 'folder'
    if re.search('IPv4', text):
        return 'ip'
    return text


def split_events(buffer):
    lines = buffer.split('\n')
    return lines[:-1], lines[-1]


class TrustHost(paramiko.MissingHostKeyPolicy):
    def __init__(self, ask, approved):
        self.ask = ask
        self.approved = approved

    def missing_host_key(self, client, hostname, key):
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        identity = (hostname, key.get_name(), fingerprint)
        if identity not in self.approved:
            answer = self.ask({'type': 'host-key', 'host': hostname, 'fingerprint': fingerprint})
            if answer != 'yes':
                raise Cancelled()
            self.approved.add(identity)
        client.get_host_keys().add(hostname, key.get_name(), key)


class Installer:
    def __init__(self, event_queue, cancelled, approved, credentials):
        self.events = event_queue
        self.cancelled = cancelled
        self.approved = approved
        self.credentials = credentials

    def event(self, kind, **values):
        self.events.put({'type': kind, **values})

    def ask(self, event):
        response = queue.Queue(maxsize=1)
        self.events.put({**event, 'response': response})
        while not self.cancelled.is_set():
            try:
                answer = response.get(timeout=.2)
                if answer is None:
                    raise Cancelled()
                return answer
            except queue.Empty:
                pass
        raise Cancelled()

    def connect(self, host, user):
        client = paramiko.SSHClient()
        known = Path.home() / '.ssh' / 'known_hosts'
        if known.is_file():
            client.load_system_host_keys(str(known))
        client.set_missing_host_key_policy(TrustHost(self.ask, self.approved))
        options = dict(hostname=host, username=user, timeout=15, auth_timeout=30, banner_timeout=15)
        try:
            client.connect(**options)
        except paramiko.SSHException as error:
            if not isinstance(error, paramiko.AuthenticationException) and str(error) != 'No authentication methods available':
                raise
            client.close()
            password = self.credentials.get('password') or self.ask({'type': 'ssh-password'})
            try:
                client.connect(**options, password=password, allow_agent=False, look_for_keys=False)
                self.credentials['password'] = password
            except paramiko.AuthenticationException:
                self.credentials.clear()
                raise
            finally:
                password = None
        return client

    def run(self, host, user, language):
        client = None
        channel = None
        remote = None
        try:
            self.event('stage', code='CONNECT')
            client = self.connect(host, user)
            _, stdout, _ = client.exec_command('umask 077; mktemp -d /var/tmp/pcc-gui.XXXXXXXX', timeout=15)
            remote = stdout.read(256).decode().strip()
            if stdout.channel.recv_exit_status() or not re.fullmatch(r'/var/tmp/pcc-gui\.[A-Za-z0-9]{8}', remote):
                raise SetupError('TEMP_DIRECTORY')
            filename = 'PlexConfigControl_Instalator.py' if language == 'pl' else 'PlexConfigControl_Installer.py'
            payload = Path(__file__).resolve().parent / 'payload' / filename
            if not payload.is_file():
                raise SetupError('MISSING_PAYLOAD')
            self.event('stage', code='UPLOAD')
            with client.open_sftp() as sftp:
                sftp.put(str(payload), remote + '/setup.py')
                sftp.chmod(remote + '/setup.py', 0o600)
            channel = client.get_transport().open_session(timeout=15)
            channel.get_pty(term='dumb', width=120, height=40)
            path = shlex.quote(remote + '/setup.py')
            channel.exec_command(
                'stty -echo; sudo -S -p PCC_SUDO_PASSWORD: -- python3 ' + path
                + ' --desktop --gui --ssh-connection $SSH_CONNECTION')
            channel.settimeout(.2)
            buffer = ''
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            last_output = time.monotonic()
            last_error = ''
            panel_url = None
            sudo_attempts = 0
            while True:
                if self.cancelled.is_set():
                    raise Cancelled()
                try:
                    chunk = channel.recv(16384)
                except socket.timeout:
                    if channel.exit_status_ready():
                        break
                    if time.monotonic() - last_output > 1200:
                        raise SetupError('TIMEOUT')
                    continue
                if not chunk:
                    break
                last_output = time.monotonic()
                buffer += decoder.decode(chunk)
                if 'PCC_SUDO_PASSWORD:' in buffer:
                    before, buffer = buffer.split('PCC_SUDO_PASSWORD:', 1)
                    sudo_attempts += 1
                    if sudo_attempts > 3:
                        raise SetupError('SUDO_AUTH')
                    password = self.credentials.get('password') if sudo_attempts == 1 else None
                    if password is None:
                        password = self.ask({'type': 'sudo-password', 'again': sudo_attempts > 1})
                    channel.sendall((password + '\n').encode())
                    password = None
                lines, buffer = split_events(buffer)
                for line in lines:
                    line = line.strip('\r')
                    if line.startswith(PREFIX):
                        event = json.loads(line[len(PREFIX):])
                        if event.get('type') == 'prompt':
                            answer = self.ask(event)
                            channel.sendall((json.dumps({'answer': answer}, ensure_ascii=False) + '\n').encode())
                            answer = None
                        elif event.get('type') == 'stage':
                            self.events.put(event)
                    else:
                        url = re.search(r'https://([0-9]{1,3}\.){3}[0-9]{1,3}:\d{4,5}', line)
                        if url:
                            panel_url = url[0]
                        if line.startswith(('Przerwano:', 'Stopped:', 'ERROR:')):
                            last_error = line[:600]
                if len(buffer) > 65536:
                    buffer = buffer[-8192:]
            status = channel.recv_exit_status()
            if status != 0:
                raise SetupError(last_error or 'INSTALL_FAILED')
            if not panel_url:
                raise SetupError('NO_PANEL_URL')
            self.event('complete', url=panel_url)
        except Cancelled:
            self.event('cancelled')
        except paramiko.BadHostKeyException:
            self.event('failure', error='HOST_KEY_CHANGED')
        except paramiko.AuthenticationException:
            self.event('failure', error='SSH_AUTH')
        except (OSError, paramiko.SSHException):
            self.event('failure', error='CONNECTION')
        except Exception as error:
            self.event('failure', error=str(error) if isinstance(error, SetupError) else 'INSTALL_FAILED')
        finally:
            if channel is not None:
                channel.close()
            if client is not None:
                if remote and re.fullmatch(r'/var/tmp/pcc-gui\.[A-Za-z0-9]{8}', remote):
                    try:
                        _, result, _ = client.exec_command('rm -f -- ' + remote + '/setup.py; rmdir -- ' + remote, timeout=10)
                        result.channel.recv_exit_status()
                    except Exception:
                        pass
                client.close()


class SetupWindow:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.approved_hosts = set()
        self.credentials = {}
        self.identity = None
        self.values = {}
        self.pending = None
        self.busy = False
        self.panel_url = None
        self.language = tk.StringVar(value='English')
        self.host = tk.StringVar()
        self.user = tk.StringVar()
        self.prompt_value = tk.StringVar()
        root.title('PlexConfigControl Setup')
        root.geometry('660x530')
        root.minsize(620, 500)
        style = ttk.Style(root)
        style.configure('Title.TLabel', font=('TkDefaultFont', 20, 'bold'))
        style.configure('Subtitle.TLabel', font=('TkDefaultFont', 11))
        outer = ttk.Frame(root, padding=26)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='PlexConfigControl', style='Title.TLabel').pack(anchor='w')
        self.subtitle = ttk.Label(outer, style='Subtitle.TLabel')
        self.subtitle.pack(anchor='w', pady=(5, 18))
        self.language_box = ttk.Combobox(outer, textvariable=self.language, state='readonly', values=('English', 'Polski'), width=18)
        self.language_box.pack(anchor='e')
        self.language_box.bind('<<ComboboxSelected>>', lambda _: self.translate())
        self.connection = ttk.Frame(outer)
        self.connection.pack(fill='x', pady=10)
        self.host_label = ttk.Label(self.connection)
        self.host_label.grid(row=0, column=0, sticky='w', pady=6)
        ttk.Entry(self.connection, textvariable=self.host, width=34).grid(row=0, column=1, sticky='ew', padx=(16, 0))
        self.user_label = ttk.Label(self.connection)
        self.user_label.grid(row=1, column=0, sticky='w', pady=6)
        ttk.Entry(self.connection, textvariable=self.user, width=34).grid(row=1, column=1, sticky='ew', padx=(16, 0))
        self.connection.columnconfigure(1, weight=1)
        self.stage = ttk.Label(outer, wraplength=590)
        self.stage.pack(anchor='w', pady=(10, 8))
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x')
        self.prompt = ttk.Frame(outer)
        self.prompt.pack(fill='both', expand=True, pady=18)
        self.prompt_label = ttk.Label(self.prompt, wraplength=590)
        self.prompt_label.pack(anchor='w', pady=(0, 8))
        self.field = ttk.Entry(self.prompt, textvariable=self.prompt_value)
        self.choice = ttk.Combobox(self.prompt, textvariable=self.prompt_value, state='readonly')
        self.note = ttk.Label(outer, wraplength=590)
        self.note.pack(anchor='w', pady=(0, 12))
        self.buttons = ttk.Frame(outer)
        self.buttons.pack(fill='x')
        self.close_button = ttk.Button(self.buttons, command=self.close)
        self.close_button.pack(side='left')
        self.primary = ttk.Button(self.buttons, command=self.start)
        self.primary.pack(side='right')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Return>', lambda _: self.primary.invoke() if str(self.primary['state']) != 'disabled' else None)
        self.translate()
        root.after(80, self.poll)

    def tx(self, en, pl):
        return pl if self.language.get() == 'Polski' else en

    def translate(self):
        self.subtitle.config(text=self.tx('Install or update your TrueNAS application', 'Zainstaluj lub zaktualizuj aplikację na TrueNAS'))
        self.host_label.config(text=self.tx('TrueNAS address', 'Adres TrueNAS'))
        self.user_label.config(text=self.tx('TrueNAS username', 'Użytkownik TrueNAS'))
        self.close_button.config(text=self.tx('Close', 'Zamknij'))
        if not self.busy:
            self.primary.config(text=self.tx('Open panel', 'Otwórz panel') if self.panel_url else self.tx('Connect', 'Połącz'))
        if not self.busy and not self.panel_url:
            self.stage.config(text=self.tx('Enter the NAS address and your administrator username.', 'Wpisz adres NAS i nazwę użytkownika z uprawnieniami administratora.'))

    def start(self):
        if self.busy:
            return
        host, user = self.host.get().strip(), self.user.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', host) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user):
            self.note.config(text=self.tx('Enter a valid NAS address and username.', 'Wpisz poprawny adres NAS i nazwę użytkownika.'))
            return
        if self.identity != (host, user):
            self.credentials.clear()
            self.identity = (host, user)
        self.busy = True
        self.language_box.config(state='disabled')
        self.primary.config(command=self.start)
        self.panel_url = None
        self.cancelled.clear()
        self.note.config(text='')
        self.prompt_label.config(text='')
        self.field.pack_forget()
        self.choice.pack_forget()
        self.primary.config(state='disabled')
        self.progress.start(12)
        language = 'pl' if self.language.get() == 'Polski' else 'en'
        worker = Installer(self.events, self.cancelled, self.approved_hosts, self.credentials)
        threading.Thread(target=worker.run, args=(host, user, language), daemon=True).start()

    def poll(self):
        try:
            while True:
                self.handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def handle(self, event):
        kind = event['type']
        if kind == 'stage':
            pair = STAGES.get(event.get('code'), ('Working…', 'Pracuję…'))
            self.stage.config(text=self.tx(*pair))
            self.note.config(text=self.tx('Please keep this window open. The first installation can take several minutes.', 'Pozostaw to okno otwarte. Pierwsza instalacja może potrwać kilka minut.'))
        elif kind in ('prompt', 'ssh-password', 'sudo-password', 'host-key'):
            self.show_prompt(event)
        elif kind == 'complete':
            self.finish()
            self.panel_url = event['url']
            self.stage.config(text=self.tx('PlexConfigControl is ready.', 'PlexConfigControl jest gotowy.'))
            self.note.config(text=self.panel_url)
            self.primary.config(text=self.tx('Open panel', 'Otwórz panel'), state='normal', command=lambda: webbrowser.open(self.panel_url))
        elif kind in ('failure', 'cancelled'):
            self.finish()
            code = event.get('error', 'CANCELLED')
            messages = {
                'HOST_KEY_CHANGED': ('The server key changed. Verify the TrueNAS SSH key before trying again.', 'Klucz serwera zmienił się. Sprawdź klucz SSH TrueNAS przed ponownym połączeniem.'),
                'SSH_AUTH': ('SSH login failed. Check your TrueNAS username and password.', 'Logowanie SSH nie powiodło się. Sprawdź użytkownika i hasło TrueNAS.'),
                'CONNECTION': ('Could not connect. Check the NAS address and whether SSH is enabled.', 'Nie udało się połączyć. Sprawdź adres NAS i czy usługa SSH jest włączona.'),
                'MISSING_PAYLOAD': ('Installer files are missing. Extract the entire package.', 'Brakuje plików instalatora. Rozpakuj całą paczkę.'),
                'CANCELLED': ('Setup stopped. Check the application in TrueNAS Apps.', 'Instalator zatrzymany. Sprawdź aplikację w TrueNAS Apps.'),
            }
            self.stage.config(text=self.tx('Setup could not finish.', 'Instalacja nie została zakończona.'))
            self.note.config(text=self.tx(*messages[code]) if code in messages else code if code.startswith(('Przerwano:', 'Stopped:', 'ERROR:')) else self.tx('Check the NAS connection and application state, then try again.', 'Sprawdź połączenie z NAS i stan aplikacji, a następnie spróbuj ponownie.'))
            self.primary.config(text=self.tx('Try again', 'Spróbuj ponownie'), state='normal', command=self.start)

    def finish(self):
        self.busy = False
        self.language_box.config(state='readonly')
        self.pending = None
        self.progress.stop()
        self.field.pack_forget()
        self.choice.pack_forget()
        self.prompt_value.set('')
        self.prompt_label.config(text='')

    def show_prompt(self, event):
        self.pending = event
        self.field.pack_forget()
        self.choice.pack_forget()
        self.prompt_value.set('')
        self.primary.config(text=self.tx('Next', 'Dalej'), state='normal', command=self.answer)
        kind = event['type']
        if kind in ('ssh-password', 'sudo-password'):
            text = self.tx('Enter your TrueNAS account password.', 'Wpisz hasło konta TrueNAS.')
            if event.get('again'):
                text = self.tx('Authentication failed. Enter the password again.', 'Hasło nie zostało przyjęte. Wpisz je ponownie.')
            self.field.config(show='•')
            self.field.pack(fill='x')
            self.field.focus_set()
        elif kind == 'host-key':
            text = self.tx('Compare this SSH fingerprint with your TrueNAS server, then confirm.', 'Porównaj ten odcisk klucza SSH z serwerem TrueNAS i potwierdź.') + '\n\n' + event['host'] + '\n' + event['fingerprint']
            self.primary.config(text=self.tx('Trust and connect', 'Zaufaj i połącz'))
        else:
            key = classify_prompt(event)
            text = event.get('message', '')
            if key == 'confirmation':
                if event['confirmation'] in ('od nowa', 'start over'):
                    text = self.tx('Replace the previous setup and install PlexConfigControl? Existing backups will be kept.', 'Zastąpić poprzednie przygotowanie i zainstalować PlexConfigControl? Kopie zostaną zachowane.')
                else:
                    text = self.tx('Continue with the reviewed settings?', 'Kontynuować z wybranymi ustawieniami?')
                review = '\n'.join(line for line in event.get('context', '').splitlines()
                                   if line.startswith(('Folder kopii:', 'Backup folder:', 'Panel:')))
                if review:
                    text += '\n\n' + review
                self.primary.config(text=self.tx('Install / update', 'Instaluj / aktualizuj'))
            elif key == 'dataset':
                text = self.tx('Choose where to keep backup archives and logs.', 'Wybierz miejsce na archiwa kopii i logi.')
                options = [label for _, label in event['choices']]
                self.choice.config(values=options)
                previous = self.values.get(key)
                self.prompt_value.set(previous if previous in options else options[0])
                self.choice.pack(fill='x')
            else:
                default = re.search(r'\[([^\]]*)\]', text)
                self.prompt_value.set(self.values.get(key, default[1] if default else ''))
                self.field.config(show='•' if event.get('secret') else '')
                self.field.pack(fill='x')
                self.field.focus_set()
        self.prompt_label.config(text=text)
        self.note.config(text=self.tx('Your entries are kept only while this installer window is open.', 'Wpisane dane są zachowane tylko na czas otwarcia tego okna.'))

    def answer(self):
        event = self.pending
        if not event:
            return
        kind = event['type']
        value = self.prompt_value.get()
        if kind == 'host-key':
            value = 'yes'
        elif kind == 'prompt':
            key = classify_prompt(event)
            if key == 'confirmation':
                value = event['confirmation']
            elif key == 'dataset':
                self.values[key] = value
                value = next(index for index, label in event['choices'] if label == value)
            else:
                self.values[key] = value
        if any(char in value for char in '\r\n\x00'):
            return
        self.pending = None
        self.prompt_value.set('')
        self.field.pack_forget()
        self.choice.pack_forget()
        self.prompt_label.config(text='')
        self.primary.config(state='disabled')
        event['response'].put(value)

    def close(self):
        if self.busy and not messagebox.askyesno('PlexConfigControl', self.tx('Close setup? Check TrueNAS Apps before starting another installation.', 'Zamknąć instalator? Przed kolejną próbą sprawdź stan w TrueNAS Apps.')):
            return
        self.cancelled.set()
        if self.pending:
            self.pending['response'].put(None)
        self.values.clear()
        self.credentials.clear()
        self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    app = SetupWindow(window)
    if '--self-test' in sys.argv:
        window.update()
        app.language.set('Polski')
        app.translate()
        app.busy = True
        app.handle({'type': 'stage', 'code': 'BUILD_WORKER'})
        assert 'obrazu' in app.stage.cget('text')
        response = queue.Queue()
        prompt = {'type': 'prompt', 'message': 'Nazwa nowego folderu kopii [Plex Config]: ',
                  'choices': [], 'confirmation': None, 'response': response}
        app.show_prompt(prompt)
        app.prompt_value.set('Moje kopie')
        app.answer()
        assert response.get_nowait() == 'Moje kopie'
        app.handle({'type': 'failure', 'error': 'CONNECTION'})
        assert app.primary.cget('text') == 'Spróbuj ponownie'
        app.show_prompt(prompt)
        assert app.prompt_value.get() == 'Moje kopie'
        app.handle({'type': 'complete', 'url': 'https://192.0.2.10:8787'})
        assert app.primary.cget('text') == 'Otwórz panel'
        assert app.panel_url == 'https://192.0.2.10:8787'
        payload = Path(__file__).resolve().parent / 'payload'
        for filename in ('PlexConfigControl_Instalator.py', 'PlexConfigControl_Installer.py'):
            compile((payload / filename).read_text(), filename, 'exec')
        window.destroy()
        print('Desktop wizard progress, retry values, completion and bundled payloads passed')
    else:
        window.mainloop()
