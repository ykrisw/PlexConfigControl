"""Structured installer prompts for the desktop wizard, disabled by default."""
import builtins
from collections import deque
import getpass
import json
import os
import re
import sys

PREFIX = 'PCC_SETUP_EVENT:'
_enabled = False
_context = deque(maxlen=24)


def emit(kind, **values):
    if _enabled or os.environ.get('PCC_SETUP_PROTOCOL') == '1':
        sys.__stdout__.write('\n' + PREFIX + json.dumps({'type': kind, **values}, ensure_ascii=False) + '\n')
        sys.__stdout__.flush()


def _ask(text, secret=False):
    context = '\n'.join(_context)[-6000:]
    choices = re.findall(r'^\s*(\d+)\. (.+\(/mnt/[^\r\n]+\))\s*$', context, re.MULTILINE)
    if secret or not re.search('Numer z listy|Enter a number or a custom path', text):
        choices = []
    confirmation = re.search(r'(?:Wpisz (od nowa|tak), aby|Type (start over|yes) to)', text)
    token = next((value for value in confirmation.groups() if value), None) if confirmation else None
    emit('prompt', message=text, secret=secret, choices=choices, confirmation=token, context=context)
    line = sys.stdin.readline()
    if not line:
        raise EOFError('Desktop installer disconnected')
    reply = json.loads(line)
    if not isinstance(reply, dict) or not isinstance(reply.get('answer'), str):
        raise ValueError('Invalid desktop response')
    answer = reply['answer']
    if '\n' in answer or '\r' in answer or '\x00' in answer:
        raise ValueError('Use a single line of text')
    return answer


def enable():
    global _enabled
    _enabled = True
    os.environ['PCC_SETUP_PROTOCOL'] = '1'
    original_print = builtins.print

    def capture(*args, **kwargs):
        if kwargs.get('file') in (None, sys.stdout, sys.stderr):
            _context.extend(' '.join(map(str, args)).splitlines())
        original_print(*args, **kwargs)

    builtins.print = capture
    builtins.input = _ask
    getpass.getpass = lambda prompt='Password: ', **kwargs: _ask(prompt, secret=True)
    emit('stage', code='CHECK_REQUIREMENTS')
