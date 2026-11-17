import io
import json
import unittest
from unittest.mock import patch

from plexconfigcontrol import setup_protocol as protocol


class SetupProtocolTests(unittest.TestCase):
    def test_dataset_context_does_not_turn_password_prompt_into_a_choice(self):
        with patch.object(protocol, '_context', ['  1. Pool/Data (/mnt/Pool/Data)']), \
             patch.object(protocol, 'emit') as emit, \
             patch.object(protocol.sys, 'stdin', io.StringIO('{"answer":"my secret"}\n')):
            self.assertEqual(protocol._ask('Nowe hasło do panelu PlexConfigControl: ', secret=True), 'my secret')
        event = emit.call_args.kwargs
        self.assertEqual(event['choices'], [])
        self.assertTrue(event['secret'])
        self.assertNotIn('my secret', repr(event))

    def test_confirmation_token_is_sent_as_metadata(self):
        with patch.object(protocol, 'emit') as emit, \
             patch.object(protocol.sys, 'stdin', io.StringIO('{"answer":"od nowa"}\n')):
            self.assertEqual(protocol._ask('Wpisz od nowa, aby utworzyć konto techniczne: '), 'od nowa')
        self.assertEqual(emit.call_args.kwargs['confirmation'], 'od nowa')

    def test_replies_reject_embedded_newlines(self):
        with patch.object(protocol, 'emit'), \
             patch.object(protocol.sys, 'stdin', io.StringIO(json.dumps({'answer': 'one\ntwo'}) + '\n')):
            with self.assertRaises(ValueError):
                protocol._ask('Name: ')
