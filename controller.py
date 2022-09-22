#!/usr/bin/env python3

import configargparse
from flask import Flask
import logging
import os
from pathlib import Path
import socket
import stat
import subprocess
from subprocess import Popen
import signal
import sys
import time
from zeroconf import IPVersion, ServiceInfo, Zeroconf

app = Flask(__name__)
dependencies = []
stream_sources = ["static-images", "v4l2", "vnc-browser"]


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


def which(cmd):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(cmd)
    if fpath:
        if is_exe(cmd):
            return cmd
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, cmd)
            if is_exe(exe_file):
                return exe_file

    return None


class Zeroconf_service:

    def __init__(self,
                 name_prefix,
                 service_type,
                 hostname,
                 listen_address,
                 listen_port,
                 properties):

        ip_version = IPVersion.V6Only
        self.service_type = service_type
        self.service_name = name_prefix + "-" + \
            hostname + "." + \
            self.service_type

        # The zeroconf service data to publish on the network
        self.zc_service = ServiceInfo(
            self.service_type,
            self.service_name,
            addresses=[socket.inet_pton(socket.AF_INET,
                                        listen_address)],
            port=int(listen_port),
            properties=properties,
            server=hostname + ".local.",
        )

        self.zc = Zeroconf(ip_version=ip_version)

    def zc_register_service(self):
        self.zc.register_service(self.zc_service)

        return True

    def zc_unregister_service(self):
        self.zc.unregister_service(self.zc_service)
        zc.close()

        return True


def probe_liveness():
    return "OK"


def list_processes():
    ps = subprocess.Popen(['ps', 'aux'],
                          stdout=subprocess.PIPE,
                          encoding="utf8").communicate()[0]
    return ps


def net_local_iface_address(probe_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((probe_ip, 80))

    return s.getsockname()[0]


def stream_setup_gstreamer(stream_source, source_device, ip, port):
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
            ], stdin=subprocess.PIPE)

    elif stream_source == "v4l2":
        gstreamer = subprocess.Popen([
            'gst-launch-1.0', '-v', '-e',
            'v4l2src', 'device=' + source_device,
            '!', 'tcpserversink', 'host=' + ip + '', 'port=' + str(port) + ''
            ], stdin=subprocess.PIPE)

    return gstreamer


def gst_stream_v4l2src(gstreamer):
    return True


def gst_stream_images(gstreamer, img_path, debug=False):
    t0 = int(round(time.time() * 1000))
    n = -1

    while True:
        filename = img_path + '/image_' + str(0).zfill(4) + '.png'
        t1 = int(round(time.time() * 1000))

        if debug:
            logging.debug(filename + ": " + str(t1 - t0) + " ms")

        t0 = t1

        f = Path(filename)

        if not f.is_file():
            logging.info("Startup: No file yet to stream")
            logging.info("Startup: Waiting..")
            time.sleep(3)
        else:
            if -1 == n:
                logging.info("Found first file, starting stream")
                n = 0
            with open(filename, 'rb') as f:
                content = f.read()
                gstreamer.stdin.write(content)
                time.sleep(0.1)

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
    logging.info("Creating v4l2 stream with device: " + device)
    p = subprocess.Popen([
                'wf-recorder',
                '--muxer=v4l2',
                '--file=/dev/video0',
                ],
                stdin=subprocess.PIPE,
                start_new_session=True,
                close_fds=False,
                encoding='utf8')

    # Handle wf-recorder prompt for overwriting the file
    p.stdin.write('Y\n')
    p.stdin.flush()

    return True


def start_browser(urls):
    cmd = ['webdriver_util.py']
    for url in urls:
        cmd.append("--url")
        cmd.append(url)

    Popen(cmd,
          env=env,
          start_new_session=True,
          close_fds=True,
          encoding='utf8')

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
                        dest='urls',
                        env_var='URL',
                        help="The URL to open in a browser, can be supplied multiple times",
                        type=str,
                        action='append',
                        required=True)
    parser.add_argument('--stream_source',
                        dest='stream_source',
                        env_var='STREAM_SOURCE',
                        help="The source of the stream",
                        type=str,
                        default="")
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
    parser.add_argument('--img-path',
                        dest='img_path',
                        env_var='IMAGES_PATH',
                        help="Path to image files",
                        type=str,
                        default="/tmp/screenshots/")
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
    parser.add_argument('--zeroconf-publish-service',
                        dest='zeroconf_publish_service',
                        env_var='ZEROCONF_PUBLISH',
                        help="Publish service via mDNS",
                        type=bool,
                        default=False)
    parser.add_argument('--zeroconf-service-name-prefix',
                        dest='zeroconf_service_name_prefix',
                        env_var='ZEROCONF_PREFIX',
                        help="The name prefix of the service",
                        type=str,
                        default="controller")
    parser.add_argument('--zeroconf-service-type',
                        dest='zeroconf_service_type',
                        env_var='ZEROCONF_TYPE',
                        help="The type of service",
                        type=str,
                        default="_http._tcp.local.")

    args = parser.parse_args()
    debug = args.debug
    urls = args.urls
    stream_source = args.stream_source
    stream_source_device = args.stream_source_device
    img_path = args.img_path
    listen_address = args.listen_address
    listen_port = args.listen_port
    probe_ip = args.probe_ip
    zeroconf_publish_service = args.zeroconf_publish_service
    zc_service_name_prefix = args.zeroconf_service_name_prefix
    zc_service_type = args.zeroconf_service_type
    logfile = args.logfile
    loglevel = args.loglevel
    log_format = '[%(asctime)s] \
    {%(filename)s:%(lineno)d} %(levelname)s - %(message)s'
    del locals()['args']

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

    for dep in dependencies:
        if which(dep) is None:
            logging.error("Could not find dependency: " + dep + ", aborting..")

        sys.exit(1)

    env = os.environ.copy()

    if debug:
        for k, v in env.items():
            logging.debug(k + '=' + v)

    try:
        logging.info(app)

    except Exception as e:
        logging.error(e)
        sys.exit(1)

    if debug:
        logging.debug(list_processes())

    if listen_port < 1025 or listen_port > 65535:
        logging.error("Invalid port, aborting..")
        sys.exit(1)

    if stream_source not in stream_sources:
        sources_str = " ".join(str(x) for x in stream_sources)
        logging.error("Invalid source, aborting..")
        logging.info("Possible choices are: " + sources_str)
        sys.exit(1)

    hostname = socket.gethostname()
    local_ip = net_local_iface_address(probe_ip)

    if stream_source == "v4l2":
        # Start streaming
        logging.info("Setting up source")
        stream_create_v4l2_src(stream_source_device)
        logging.info("Setting up stream")
        gst = stream_setup_gstreamer(stream_source,
                                     stream_source_device,
                                     local_ip,
                                     listen_port)
        gst_stream_v4l2src(gst)
        gst.stdin.close()
        gst.wait()

    elif stream_source == "static-images":
        logging.info("Starting browser with " + str(len(urls)) + "URLs")
        start_browser(urls)

        gst = stream_setup_gstreamer(stream_source,
                                     stream_source_device,
                                     local_ip,
                                     listen_port)

        gst_stream_images(gst, img_path)
        gst.stdin.close()
        gst.wait()

    elif stream_source == "vnc-browser":
        logging.info("Starting browser")
        start_browser(urls)

    else:
        logging.error("Missing streaming source configuration. Exiting.")
        sys.exit(1)

    # Publish service on the network via mDNS
    if zeroconf_publish_service:
        zc_listen_address = listen_address

        if "0.0.0.0" == zc_listen_address:
            zc_listen_address = net_local_iface_address(probe_ip)

        zc_listen_port = listen_port

        logging.info("zeroconf: Publishing service of type " \
            + zc_service_type + " with name prefix " \
            + zc_service_name_prefix + " on " \
            + zc_listen_address + ":" + str(zc_listen_port))

        zc_service_properties = {"stream_source": stream_source}

        zc = Zeroconf_service(zc_service_name_prefix,
                              zc_service_type,
                              hostname,
                              zc_listen_address,
                              zc_listen_port,
                              zc_service_properties)

        r = zc.zc_register_service()

        if not r:
            logging.error("zeroconf: Failed to publish service")

    # Set up signal handler
    def signal_handler(number, *args):
        logging.info('Signal received:', number)

        # Unpublish service
        if zeroconf_publish_service and zc:
            zc.unregister_service()

        sys.exit(0)

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)

    # Start webserver for health endpoints
    app.run(host=listen_address)
