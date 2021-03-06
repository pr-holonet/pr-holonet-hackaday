'''

Copyright 2017 Ewan Mellor

Changes authored by Hadi Esiely:
Copyright 2018 The Johns Hopkins University Applied Physics Laboratory LLC.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
contributors may be used to endorse or promote products derived from this
software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

'''


import logging
from logging.handlers import RotatingFileHandler
import os
import os.path

from flask import Flask, redirect, render_template, request, \
    send_from_directory, url_for
from flask_webpack import Webpack

from holonet import mailboxes, queue_manager, system_manager
from holonet.utils import printable_phone_number


LOG_FILE = '/var/opt/pr-holonet/log/holonet-web.log'
HOLONET_LOG_LEVEL = logging.DEBUG


is_flask_subprocess = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
is_gunicorn = "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")
thisdir = os.path.abspath(os.path.dirname(__file__))

webpack = Webpack()
app = Flask(__name__)
app.config['WEBPACK_MANIFEST_PATH'] = \
    os.path.join(thisdir, 'build', 'manifest.json')
webpack.init_app(app)

holonet_logger = logging.getLogger('holonet')
holonet_logger.setLevel(HOLONET_LOG_LEVEL)
for handler in app.logger.handlers:
    holonet_logger.addHandler(handler)

if is_gunicorn:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1000000, backupCount=1)
    fmt = '%(asctime)-15s %(levelname)-7.7s %(message)s'
    handler.setFormatter(logging.Formatter(fmt=fmt))
    holonet_logger.addHandler(handler)
    app.logger.addHandler(handler)

if not is_gunicorn:
    dev_root = os.path.join(thisdir, '..')
    mailboxes.mailboxes_root = \
        os.path.abspath(os.path.join(dev_root, 'mailboxes'))
    system_manager.system_manager_root = \
        os.path.abspath(os.path.join(dev_root, 'system_manager'))

if is_flask_subprocess or is_gunicorn:
    queue_manager.start(app.config.get('ROCKBLOCK_DEVICE'))

if is_gunicorn:
    system_manager.safety_catch = False


@app.route('/')
def index():
    # Note that this is an async request to refresh the signal strength.  If
    # it does't get done by the time we've parsed the mailboxes (which is
    # likely because we should be reading the SD card a lot faster than the
    # serial line) then we'll be reporting the stale strength, not the new one.
    # That's OK for now.
    queue_manager.request_signal_strength()

    outbox = mailboxes.read_outbox()
    local_user = _get_local_user()
    recipients = mailboxes.list_recipients(local_user)
    recipients_printable = _printable_phone_number_dict(recipients)
    pending = queue_manager.message_pending_senders.keys()
    pending_printable = _printable_phone_number_dict(pending)
    signal = queue_manager.last_known_signal_strength

    return render_template('index.html',
                           outbox=outbox,
                           pending=pending,
                           pending_printable=pending_printable,
                           recipients=recipients,
                           recipients_printable=recipients_printable,
                           signal=signal)


def _printable_phone_number_dict(nos):
    return dict(map(lambda x: (x, printable_phone_number(x)), nos))


@app.route("/assets/<path:filename>")
def send_asset(filename):
    return send_from_directory(os.path.join(thisdir, 'build', 'public'),
                               filename)


@app.route('/network_configure', methods=['POST'])
def network_configure():
    system_manager.configure_network(request.form)
    return _response_return_to_previous()


@app.route('/send_message', methods=['POST'])
def send_message():
    body = request.form.get('body')
    recipient = request.form.get('recipient')

    resp = _response_return_to_previous()

    if not body or not recipient:
        return resp

    local_user = _get_local_user()

    mailboxes.queue_message_send(local_user, recipient, body)
    queue_manager.check_outbox()

    return resp


@app.route('/send_receive', methods=['POST'])
def send_receive():
    queue_manager.check_outbox()
    queue_manager.get_messages(ack_ring=False)

    return _response_return_to_previous()


@app.route('/system')
def system():
    # Note that this is an async request to refresh the signal strength,
    # same as index() above.
    queue_manager.request_signal_strength()

    status = system_manager.get_system_status()
    return render_template('system.html', **status)


@app.route('/system_configure', methods=['POST'])
def system_configure():
    system_manager.set_ap_settings(request.form)
    return _response_return_to_previous()


@app.route('/test')
def test():
    inbox = mailboxes.read_inbox()
    outbox = mailboxes.read_outbox()
    local_user = _get_local_user()
    recipients = mailboxes.list_recipients(local_user)

    return render_template('test.html',
                           inbox=inbox,
                           outbox=outbox,
                           recipients=recipients)


@app.route('/thread/<recipient>')
def thread(recipient):
    queue_manager.clear_message_pending(recipient)
    local_user = _get_local_user()
    messages = mailboxes.get_thread(local_user, recipient)
    recipient_printable = printable_phone_number(recipient)
    return render_template('thread.html',
                           messages=messages,
                           recipient=recipient,
                           recipient_printable=recipient_printable)


@app.route('/thread/<recipient>', methods=['DELETE'])
def thread_delete(recipient):
    return _thread_delete(recipient)

@app.route('/thread_delete/<recipient>')
def thread_delete_by_get(recipient):
    return _thread_delete(recipient)

def _thread_delete(recipient):
    queue_manager.clear_message_pending(recipient)
    local_user = _get_local_user()
    messages = mailboxes.delete_thread(local_user, recipient)
    return _response_return_to_previous()


def _get_local_user():
    # TODO: Some concept of signing in?
    return 'local'


def _response_return_to_previous():
    return redirect(request.referrer or url_for('index'))


if __name__ == '__main__':
    app.jinja_env.auto_reload = True
    app.run(debug=True, host='0.0.0.0',
            extra_files=[app.config["WEBPACK_MANIFEST_PATH"]])
