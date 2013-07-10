from __future__ import unicode_literals

import logging
import sys
import pytest
from raven.utils.testutils import TestCase
from raven.utils import six
from raven.base import Client
from raven.handlers.logging import SentryHandler
from raven.utils.stacks import iter_stack_frames


class TempStoreClient(Client):
    def __init__(self, servers=None, **kwargs):
        self.events = []
        super(TempStoreClient, self).__init__(servers=servers, **kwargs)

    def is_enabled(self):
        return True

    def send(self, **kwargs):
        self.events.append(kwargs)


class LoggingIntegrationTest(TestCase):
    def setUp(self):
        self.client = TempStoreClient(include_paths=['tests', 'raven'])
        self.handler = SentryHandler(self.client)

    def make_record(self, msg, args=(), level=logging.INFO, extra=None, exc_info=None):
        record = logging.LogRecord('root', level, __file__, 27, msg, args, exc_info, 'make_record')
        if extra:
            for key, value in six.iteritems(extra):
                record.__dict__[key] = value
        return record

    def test_logger_basic(self):
        record = self.make_record('This is a test error')
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert event['logger'] == 'root'
        assert event['level'] == logging.INFO
        assert event['message'] == 'This is a test error'
        assert 'sentry.interfaces.Stacktrace' not in event
        assert 'sentry.interfaces.Exception' not in event
        assert 'sentry.interfaces.Message' in event
        msg = event['sentry.interfaces.Message']
        assert msg['message'] == 'This is a test error'
        assert msg['params'] == ()

    def test_logger_extra_data(self):
        record = self.make_record('This is a test error', extra={'data': {
            'url': 'http://example.com',
        }})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        if six.PY3:
            expected = "'http://example.com'"
        else:
            expected = "u'http://example.com'"
        assert event['extra']['url'] == expected

    def test_logger_exc_info(self):
        try:
            raise ValueError('This is a test ValueError')
        except ValueError:
            record = self.make_record('This is a test info with an exception', exc_info=sys.exc_info())
        else:
            self.fail('Should have raised an exception')

        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)

        self.assertEqual(event['message'], 'This is a test info with an exception')
        assert 'sentry.interfaces.Stacktrace' in event
        assert 'sentry.interfaces.Exception' in event
        exc = event['sentry.interfaces.Exception']
        assert exc['type'] == 'ValueError'
        assert exc['value'] == 'This is a test ValueError'
        assert 'sentry.interfaces.Message' in event
        msg = event['sentry.interfaces.Message']
        assert msg['message'] == 'This is a test info with an exception'
        assert msg['params'] == ()

    def test_message_params(self):
        record = self.make_record('This is a test of %s', args=('args',))
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert event['message'] == 'This is a test of args'
        msg = event['sentry.interfaces.Message']
        assert msg['message'] == 'This is a test of %s'
        expected = ("'args'",) if six.PY3 else ("u'args'",)
        assert msg['params'] == expected

    def test_record_stack(self):
        record = self.make_record('This is a test of stacks', extra={'stack': True})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert 'sentry.interfaces.Stacktrace' in event
        frames = event['sentry.interfaces.Stacktrace']['frames']
        assert len(frames) != 1
        frame = frames[0]
        assert frame['module'] == 'raven.handlers.logging'
        assert 'sentry.interfaces.Exception' not in event
        assert 'sentry.interfaces.Message' in event
        assert event['culprit'] == 'root in make_record'
        assert event['message'] == 'This is a test of stacks'

    def test_no_record_stack(self):
        record = self.make_record('This is a test with no stacks', extra={'stack': False})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert event['message'] == 'This is a test with no stacks'
        assert 'sentry.interfaces.Stacktrace' not in event

    def test_explicit_stack(self):
        record = self.make_record('This is a test of stacks', extra={'stack': iter_stack_frames()})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert 'sentry.interfaces.Stacktrace' in event
        assert 'culprit' in event
        assert event['culprit'] == 'root in make_record'
        assert 'message' in event, event
        assert event['message'] == 'This is a test of stacks'
        assert 'sentry.interfaces.Exception' not in event
        assert 'sentry.interfaces.Message' in event
        msg = event['sentry.interfaces.Message']
        assert msg['message'] == 'This is a test of stacks'
        assert msg['params'] == ()

    def test_extra_culprit(self):
        record = self.make_record('This is a test of stacks', extra={'culprit': 'foo in bar'})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert event['culprit'] == 'foo in bar'

    def test_extra_data_as_string(self):
        record = self.make_record('Message', extra={'data': 'foo'})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        expected = "'foo'" if six.PY3 else "u'foo'"
        assert event['extra']['data'] == expected

    def test_tags(self):
        record = self.make_record('Message', extra={'tags': {'foo': 'bar'}})
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert event['tags'] == {'foo': 'bar'}

    def test_tags_on_error(self):
        try:
            raise ValueError('This is a test ValueError')
        except ValueError:
            record = self.make_record('Message', extra={'tags': {'foo': 'bar'}}, exc_info=sys.exc_info())
        self.handler.emit(record)

        assert len(self.client.events) == 1
        event = self.client.events.pop(0)
        assert event['tags'] == {'foo': 'bar'}


class TestLoggingHandler(object):
    def test_client_arg(self):
        client = TempStoreClient(include_paths=['tests'])
        handler = SentryHandler(client)
        assert handler.client == client

    def test_client_kwarg(self):
        client = TempStoreClient(include_paths=['tests'])
        handler = SentryHandler(client=client)
        assert handler.client == client

    def test_args_as_servers_and_key(self):
        handler = SentryHandler(['http://sentry.local/api/store/'], 'KEY')
        assert isinstance(handler.client, Client)

    def test_first_arg_as_dsn(self):
        handler = SentryHandler('http://public:secret@example.com/1')
        assert isinstance(handler.client, Client)

    def test_custom_client_class(self):
        handler = SentryHandler('http://public:secret@example.com/1', client_cls=TempStoreClient)
        assert type(handler.client) == TempStoreClient

    def test_invalid_first_arg_type(self):
        with pytest.raises(ValueError):
            SentryHandler(object)

    def test_logging_level_set(self):
        handler = SentryHandler('http://public:secret@example.com/1', level="ERROR")
        # XXX: some version of python 2.6 seem to pass the string on instead of coercing it
        assert handler.level in (logging.ERROR, 'ERROR')

    def test_logging_level_not_set(self):
        handler = SentryHandler('http://public:secret@example.com/1')
        assert handler.level == logging.NOTSET
