#!/usr/bin/env python3

import configargparse
import logging
import os
import socket
import stat
import subprocess
from subprocess import Popen, PIPE
import sys
import time
from flask import Flask

app = Flask(__name__)
stream_sources = ["static-images", "v4l2"]


@app.route("/")
def info():
    return app


# Readiness
@app.route('/healthy')
def healthy():
    return "OK"


# Liveness
@app.route('/healthz')
def healthz():
    return probe_liveness()


def list_processes():
    ps = subprocess.Popen(['ps', 'aux'],
                          stdout=subprocess.PIPE,
                          encoding="utf8").communicate()[0]
    return ps


def probe_liveness():
    return "OK"


def net_local_iface_address(probe_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((probe_ip, 80))
    return s.getsockname()[0]


def stream_setup_gstreamer(source, ip, port, device):
    if stream_source == "static-images":
        gstreamer = subprocess.Popen([
            'gst-launch-1.0', '-v', '-e',
            'fdsrc',
            '!', 'pngdec',
            '!', 'videoconvert',
            '!', 'videorate',
            '!', 'video/x-raw,framerate=25/2',
            '!', 'theoraenc',
            '!', 'oggmux',
            '!', 'tcpserversink', 'host=' + ip + '', 'port=' + str(port) + ''
            ], stdin=subprocess.PIPE, encoding='utf8')

    elif stream_source == "v4l2":
        gstreamer = subprocess.Popen([
            'gst-launch-1.0', '-v', '-e',
            'v4l2src device=' + device,
            '!', 'videoconvert',
            '!', 'videorate',
            '!', 'video/x-raw,framerate=25/2',
            '!', 'theoraenc',
            '!', 'oggmux',
            '!', 'tcpserversink', 'host=' + ip + '', 'port=' + str(port) + ''
            ], stdin=subprocess.PIPE, encoding='utf8')

    return gstreamer


def gst_stream_images(gstreamer, img_path):
    t0 = int(round(time.time() * 1000))
    n = 0

    while True:
        filename = img_path + '/image_' + str(n).zfill(4) + '.png'
        t1 = int(round(time.time() * 1000))
        logging.info(filename + ": " + str(t1 - t0) + " ms")
        t0 = t1

        with open(filename, 'rb') as f:
            content = f.read()
            gstreamer.stdin.write(content)

        if 10 == n:
            n = 0
        else:
            n += 1


def stream_create_v4l2_src(device):
    # Check if device is an existing character device
    if not stat.S_ISCHR(os.lstat(device)[stat.ST_MODE]):
        logging.error(device + " does not exist, aborting..")
        sys.exit(1)

    # Create v4l2 recording of screen
    logging.info("Creating v4l2 stream with: " + device)
    p = subprocess.Popen([
                'wf-recorder',
                '--muxer=v4l2',
                '--file=/dev/video0',
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=False,
                encoding='utf8')

    # Handle wf-recorder prompt for overwriting the file
    p.stdin.write('Y\n')
    p.stdin.flush()

    for line in iter(p.stdout.readline, b''):
        if line != "":
            logging.info('>>> {}'.format(line.rstrip()))

    return True


if __name__ == "__main__":

    parser = configargparse.ArgParser(description="")
    parser.add_argument('--debug',
                        dest='debug',
                        env_var='DEBUG',
                        help="Show debug output",
                        type=bool,
                        default=False)
    parser.add_argument('--url',
                        dest='url',
                        env_var='URL',
                        help="The URL to open in a browser",
                        type=str,
                        default="")
    parser.add_argument('--stream_source',
                        dest='stream_source',
                        env_var='STREAM_SOURCE',
                        help="The source of the stream",
                        type=str,
                        default="v4l2")
    parser.add_argument('--stream-source-device',
                        dest='stream_source_device',
                        env_var='STREAM_SOURCE_DEVICE',
                        help="The source device to stream from",
                        type=str,
                        default="/dev/video0")
    parser.add_argument('--listen-address',
                        dest='listen_address',
                        env_var='LISTEN_ADDRESS',
                        help="The address to listen on",
                        type=str,
                        default="0.0.0.0")
    parser.add_argument('--listen-port',
                        dest='listen_port',
                        env_var='LISTEN_PORT',
                        help="The port to listen on",
                        type=int,
                        default=6000)
    parser.add_argument('--logfile',
                        dest='logfile',
                        env_var='LOGFILE',
                        help="Path to optional logfile",
                        type=str)
    parser.add_argument('--loglevel',
                        dest='loglevel',
                        env_var='LOGLEVEL',
                        help="Loglevel, default: INFO",
                        type=str,
                        default='INFO')
    parser.add_argument('--probe-ip',
                        dest='probe_ip',
                        env_var='PROBE_IP',
                        help="The address to probe for",
                        type=str,
                        default="9.9.9.9")

    args = parser.parse_args()
    debug = args.debug
    url = args.url
    stream_source = args.stream_source
    stream_source_device = args.stream_source_device
    listen_address = args.listen_address
    listen_port = args.listen_port
    probe_ip = args.probe_ip
    logfile = args.logfile
    loglevel = args.loglevel
    log_format = '[%(asctime)s] \
    {%(filename)s:%(lineno)d} %(levelname)s - %(message)s'

    # Optional File Logging
    if logfile:
        tlog = logfile.rsplit('/', 1)
        logpath = tlog[0]
        logfile = tlog[1]
        if not os.access(logpath, os.W_OK):
            # Our logger is not set up yet, so we use print here
            print("Logging: Can not write to directory. Skipping file handler")
        else:
            fn = logpath + '/' + logfile
            file_handler = logging.FileHandler(filename=fn)
            # Our logger is not set up yet, so we use print here
            print("Logging: Logging to " + fn)

    stdout_handler = logging.StreamHandler(sys.stdout)

    if 'file_handler' in locals():
        handlers = [file_handler, stdout_handler]
    else:
        handlers = [stdout_handler]

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers
    )

    logger = logging.getLogger(__name__)
    level = logging.getLevelName(loglevel)
    logger.setLevel(level)

    env = os.environ.copy()

    if debug:
        for k, v in env.items():
            logging.debug(k + '=' + v)

    try:
        logging.info(__name__)

    except Exception as e:
        logging.error(e)
        sys.exit(1)

    if debug:
        logging.debug(list_processes())

    if listen_port < 1025 or listen_port > 65535:
        logging.error("Invalid port, aborting..")
        sys.exit(1)

    if len(url) < 12:
        logging.error("Not a valid URL, aborting..")
        sys.exit(1)

    if not stream_source:
        logging.error("No source defined")
        sys.exit(1)

    if stream_source not in stream_sources:
        sources_str = " ".join(str(x) for x in stream_sources)
        logging.error("Invalid source, aborting..")
        logging.info("Possible choices are: " + sources_str)
        sys.exit(1)

    ip = net_local_iface_address(probe_ip)

    if stream_source == "v4l2":
        # Start streaming
        stream_src_device = "/dev/video0"
        stream_create_v4l2_src(stream_source_device)
        gst = stream_setup_gstreamer(stream_source,
                                     ip,
                                     listen_port,
                                     stream_source_device)

    elif stream_source == "static-images":
        # Start browser
        logging.info("Starting browser")
        p = Popen(['webdriver_util.py'],
                  stdout=subprocess.PIPE,
                  stderr=subprocess.STDOUT,
                  env=env,
                  start_new_session=True,
                  close_fds=False,
                  encoding='utf8')

        for line in iter(p.stdout.readline, b''):
            if line != "":
                logging.info('>>> {}'.format(line.rstrip()))

        gstreamer = stream_setup_gstreamer(stream_source,
                                           ip,
                                           listen_port,
                                           "")

        gst_stream_images(gstreamer, "/tmp/browser-screenshots/")
        gstreamer.stdin.close()
        gstreamer.wait()
    else:
        logging.error("Missing streaming source configuration. Exiting.")
        sys.exit(1)

    # Start webserver
    app.run(host=listen_address)
