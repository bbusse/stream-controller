#!/usr/bin/env python3
import requests
import asyncio
import configargparse
from flask import Flask
from hnapi import HnApi
import html
import json
import logging
import os
from pathlib import Path
import psutil
import random
import socket
import stat
import subprocess
from subprocess import Popen
import signal
import sys
import time
import threading
sys.path.append(os.path.abspath("/usr/local/src/python-wayland"))
import draw as view
import wayland.protocol
from wayland.client import MakeDisplay
from wayland.utils import AnonymousFile
from zeroconf import IPVersion, ServiceInfo, Zeroconf

wserver = Flask(__name__)
dependencies = ["xrandr"]
stream_sources = ["static-images", "v4l2", "vnc-browser"]
cmds = {"media_player": "mpv",
        "image_viewer": "imv",
        "clock": "humanbeans_clock"}

@wserver.route("/")
def info():
    return True


# Readiness
@wserver.route('/healthy')
def healthy():
    return "OK"


# Liveness
@wserver.route('/healthz')
def healthz():
    return probe_liveness()


@wserver.route("/display")
def display():
    data = {}
    data['address'] = display.address
    data['res_x'] = display.res_x
    data['res_y'] = display.res_y
    data['uptime'] = System.uptime()
    data['playlist'] = []
    json_data = json.dumps(data)
    return json_data


def probe_liveness():
    return "OK"


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


def download_file(url, path):
    logging.info("Downloading: " + url)
    cmd = ['curl', '-LO', '--create-dirs', '--output-dir', path,  url]

    Popen(cmd,
          env=env,
          start_new_session=True,
          close_fds=True,
          encoding='utf8')

    return True


class System:

    def list_processes(limit=0):
        if limit > 0:
            cmd = ['ps', 'ux', '--ppid', '2', '-p', '2', '--deselect', '|', 'head', '-n', limit]
        else:
            cmd = ['ps', 'ux', '--ppid', '2', '-p', '2', '--deselect']

        # Processes without kernel threads
        ps = subprocess.Popen(cmd,
                              stdout=subprocess.PIPE,
                              encoding="utf8").communicate()[0]
        return ps


    def net_local_iface_address(probe_ip):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((probe_ip, 80))

        return s.getsockname()[0]

    def uptime():
        return time.time() - psutil.boot_time()


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


class Playlist:

    def __init__(self, uris, default_play_time_s, location=None):
        self.download_path = "/tmp/"
        self.location = location
        self.default_play_time_s = default_play_time_s
        self.news = None

        self.playlist = list()
        self.playlist = self.create(uris)

    def create(self, uris):
        n = 0
        playlist = list()

        for uri in uris:
            item = {}
            n += 1
            if uri.endswith(".m3u8"):
                item["num"] = n
                item["uri"] = uri
                item["player"] = "mediaplayer"
                item["play_time_s"] = self.default_play_time_s
            elif uri.endswith(".svg"):
                download_file(uri.strip(), download_path)
                file = uri.split("/")
                item["num"] = n
                item["uri"] = "file:///" + download_path + file[-1]
                item["player"] = "imageviewer"
                item["play_time_s"] = self.default_play_time_s
            elif uri.startswith("https://"):
                item["num"] = n
                item["uri"] = uri
                item["player"] = "browser"
                item["play_time_s"] = self.default_play_time_s
            elif uri.startswith("iss-clock://"):
                item["num"] = n
                item["uri"] = uri
                item["player"] = "clock"
                item["play_time_s"] = self.default_play_time_s
            elif uri.startswith("iss-news://"):
                self.news = News()
                item["num"] = n
                item["uri"] = uri
                item["player"] = "news"
                item["play_time_s"] = self.default_play_time_s
            elif uri.startswith("iss-system://"):
                item["num"] = n
                item["uri"] = uri
                item["player"] = "system"
                item["play_time_s"] = self.default_play_time_s
            elif uri.startswith("iss-weather://"):
                weather = Weather(self.location)
                item["num"] = n
                item["uri"] = uri
                item["player"] = "weather"
                item["play_time_s"] = self.default_play_time_s

            # Append if we found a valid playlist item
            if "num" in item:
                playlist.append(item)

        return playlist

    def start_player(self):
        threads = list()
        for item in self.playlist:
            if item["player"] == "browser":
                # start_browser() wants a list
                # but we want to start an instance for each URL
                urls = list()
                urls.append(item["uri"])
                x = threading.Thread(target=self.start_browser, args=(urls,))
            elif item["player"] == "clock":
                x = threading.Thread(target=self.start_clock, args=())
            elif item["player"] == "imageviewer":
                x = threading.Thread(target=self.start_image_view, args=())
            elif item["player"] == "news":
                x = threading.Thread(target=self.start_news_view, args=(self.news,))
            elif item["system"] == "system":
                x = threading.Thread(target=self.start_system_view, args=())
            elif item["player"] == "weather":
                x = threading.Thread(target=self.start_weather_view, args=())

            x.start()
            if not x.is_alive():
                logging.error("Failed to start {}".format(item["player"]))
            else:
                threads.append(x)

        return threads

    def start_browser(self, urls):
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

    def start_clock(self):
        logging.info("Starting clock")
        cmd = [cmds["clock"]]

        p = Popen(cmd,
                  env=env,
                  start_new_session=True,
                  close_fds=True)

        if p.communicate()[0] != 0:
            return False

        return True

    def start_image_viewer(self, file):
        logging.info("Starting image viewer with file: " + file)
        cmd = [cmds["image_viewer"],  file]

        Popen(cmd,
              env=env,
              start_new_session=True,
              close_fds=True,
              encoding='utf8')

        return True

    def start_mediaplayer(self, url):
        logging.info("Starting media player with stream: " + url)
        cmd = [cmds["media_player"],  url]

        Popen(cmd,
              env=env,
              start_new_session=True,
              close_fds=True,
              encoding='utf8')

        return True

    def start_sys_view(self):
        texts = list()
        texts.append(System.list_processes(23))
        view = Wayland_view(display.res_x, display.res_y, len(texts))
        view.s_objects[0]["font_size"] = 14
        view.s_objects[0]["alignment"] = "left"
        self.render_text_view(view, texts)

    def start_weather_view(self, weather):
        texts = list()
        data = weather.current_weather()
        texts.append(data["current_condition"][0]["temp_C"] + "°C")
        texts.append(data["current_condition"][0]["weatherDesc"][0]["value"] + " " +  \
                     data["current_condition"][0]["windspeedKmph"] + " km/h")
        texts.append(data["nearest_area"][0]["areaName"][0]["value"])
        view = Wayland_view(display.res_x, display.res_y, len(texts))
        view.s_objects[0]["font_size"] = 80
        view.s_objects[0]["alignment"] = "left"
        view.s_objects[1]["font_size"] = 40
        view.s_objects[1]["alignment"] = "left"
        view.s_objects[2]["font_size"] = 20
        view.s_objects[2]["alignment"] = "left"
        self.render_text_view(view, texts)

    def start_news_view(self, news):
        texts = list()
        item = news.news_item()
        texts.append("[HN]")
        texts.append(item["title"])
        texts.append(item["url"])
        logging.info("News: " + item["url"])
        view = Wayland_view(display.res_x, display.res_y, len(texts))
        view.s_objects[0]["font_size"] = 30
        view.s_objects[1]["font_size"] = 60
        view.s_objects[2]["font_size"] = 30
        self.render_text_view(view, texts)

    def render_text_view(self, view, texts):
        view.show_text(texts)

    def start_image_view(self, view, files):
        view = Wayland_view(display.res_x, display.res_y)
        view.show_image(file)


class Stream():

    def __init__(self, stream_source):
        if stream_source == "v4l2":
            # Start streaming
            logging.info("Setting up source")
            stream_create_v4l2_src(stream_source_device)
            logging.info("Setting up stream")
            time.sleep(3)
            stream_v4l2_ffmpeg()
            #gst = stream_setup_gstreamer(stream_source,
            #                             stream_source_device,
            #                             local_ip,
            #                             listen_port)
            #gst.stdin.close()
            #gst.wait()

        elif stream_source == "static-images":
            gst = stream_setup_gstreamer(stream_source,
                                         stream_source_device,
                                         local_ip,
                                         listen_port)

            gst_stream_images(gst, img_path)
            gst.stdin.close()
            gst.wait()

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
                '!', 'videorate',
                '!', 'video/x-raw,framerate=25/2',
                '!', 'queue',
                '!', 'tcpserversink', 'host=' + ip + '', 'port=' + str(port) + ''
                ], stdin=subprocess.PIPE)

        return gstreamer

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
                    '--file=' + device,
                    ],
                    stdin=subprocess.PIPE,
                    start_new_session=True,
                    close_fds=False,
                    encoding='utf8')

        # Handle wf-recorder prompt for overwriting the file
        p.stdin.write('Y\n')
        p.stdin.flush()

        return True


    def stream_v4l2_ffmpeg():
        ffmpeg = subprocess.Popen([
            'ffmpeg', '-f', 'v4l2', '-i', '/dev/video0',
            '-codec', 'copy',
            '-f', 'mpegts', 'udp:localhost:6000'
            ],
            stdin=subprocess.PIPE,
            start_new_session=True,
            close_fds=False)


class News:

    def __init__(self):
        self.news = []
        self.fetch_top_news(10)

    def fetch_top_news(self, nitems):
        n = 0

        logging.info("Fetching News")
        con = HnApi()
        top = con.get_top()

        for tnews in top:
            if n == nitems:
                break

            self.news.append(con.get_item(tnews))
            n += 1

    # news_item returns a single news text
    # from the previously fetched ones
    def news_item(self):
        n = {"title": "",
             "url": ""}

        n["title"] = self.news.pop(0).get('title')
        n["url"] = self.news.pop(0).get('url')

        return n


class Weather:

    def __init__(self, location):
        self.location = location
        self.weather = self.fetch_weather()

    def fetch_weather(self):
        url = "https://wttr.in/{}?format=j1".format(self.location)
        logging.info("Fetching weather for {} at {}"\
                     .format(self.location, url))

        cmd = ['curl ' + url]
        p = subprocess.Popen(cmd,
                             shell=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             encoding="utf8")

        #data = p.communicate()[0]
        data = requests.get(url, timeout=10)
        data = data.content

        if not data:
            logging.error("Failed to fetch weather data")

        try:
            data = json.loads(data)
        except ValueError as e:
            logging.error("weather: Failed to decode data")
            logging.error(e)
            data = {}
            sys.exit(1)

        return data

    def current_weather(self):
        return self.weather


class Wayland_view:

    def __init__(self, res_x, res_y, num_objects):
        # Load the main Wayland protocol.
        wp_base = wayland.protocol.Protocol("/usr/share/wayland/wayland.xml")
        wp_xdg_shell = wayland.protocol.Protocol("/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml")

        try:
            self.conn = view.WaylandConnection(wp_base, wp_xdg_shell)
        except FileNotFoundError as e:
            if e.errno == 2:
                print("Unable to connect to the compositor - "
                      "is one running?")
                sys.exit(1)
            raise

        self.window = {}
        self.window["res_x"] = res_x
        self.window["res_y"] = res_y
        self.window["title"] = "News"

        s_object = {"alignment": "center",
                    "offset_x": 10,
                    "offset_y": 10,
                    "bg_colour_r": 7,
                    "bg_colour_g": 59,
                    "bg_colour_b": 76,
                    "font_face": "monospace",
                    "font_size": 60,
                    "font_colour_r": 0,
                    "font_colour_g": 0,
                    "font_colour_b": 0,
                    "file": "",
                    "text": list()}

        self.s_objects = list()
        for n in range(0, num_objects):
            logging.info("view: Appending drawing object")
            self.s_objects.append(s_object.copy())

    def create_window(self, w):
        view.eventloop()

        w.close()
        self.conn.display.roundtrip()
        self.conn.disconnect()
        logging.info("Exiting wayland view: {}".format(view.shutdowncode))

    def show_text(self, texts, fullscreen=False):
        logging.info("view: Have {} text blocks".format(len(texts)))
        n = 0
        for text in texts:
            logging.info(text)
            self.s_objects[n]["text"] = html.escape(text)
            n += 1

        w = view.Window(self.conn,
                        self.window,
                        self.s_objects,
                        redraw=view.draw_text_in_window,
                        fullscreen=fullscreen,
                        class_="iss-view")

        self.create_window(w)

    def show_image(self, file, fullscreen=False):
        self.s_object["file"] = file
        w = view.Window(self.conn,
                        self.window,
                        self.s_object,
                        redraw=iew.draw_img_in_window,
                        fullscreen=fullscreen,
                        class_="iss-view")

        self.create_window(w)


class Display:

    def __init__(self, address):
        self.address = address
        res = self.get_resolution().split("x")
        self.res_x = int(res[0])
        self.res_y = int(res[1])
        self.start_time = time.time()
        self.switching_windows = list()
        self.window_blacklist = list()

        logging.info("Resolution: {} x {}"
                     .format(self.res_x, self.res_y))

        # We do not want to handle existing windows,
        # so we put their IDs on a blacklist
        existing_windows = self.get_windows()
        for win in existing_windows:
            self.window_blacklist.append(win["id"])

        logging.info("Blacklisted {} windows".format(len(self.window_blacklist)))

    def get_resolution(self):
        cmd = "xrandr -q | awk '/\*/ {print $1}' \
               | awk 'BEGIN{FS=\"x\";} NR==1 || \
               $1>max {line=$0; max=$1}; END {print line}'"

        p = subprocess.Popen(cmd,
                             shell=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             encoding="utf8")

        res = p.communicate()[0]

        return res

    def get_windows_whitelist(self):
        windows = self.get_windows(self.window_blacklist)
        logging.info("display: {} windows in whitelist".format(len(windows)))

        return windows

    def get_windows(self, blacklist=None):
        cmd="swaymsg -t get_tree"
        windows = []

        p = subprocess.Popen(cmd,
                             shell=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)

        data = json.loads(p.communicate()[0])

        for output in data['nodes']:
            if output.get('type') == 'output':
                workspaces = output.get('nodes')
                for ws in workspaces:
                    if ws.get('type') == 'workspace':
                        windows += self.workspace_nodes(ws)

        if blacklist:
            windows_whitelist = windows.copy()
            for win in windows:
                if win["id"] in blacklist:
                    windows_whitelist.pop()

            return windows_whitelist

        return windows


    # Extracts all windows from sway workspace json
    def workspace_nodes(self, workspace):
        windows = []

        floating_nodes = workspace.get('floating_nodes')

        for floating_node in floating_nodes:
            windows.append(floating_node)

        nodes = workspace.get('nodes')

        for node in nodes:
            # Leaf node
            if len(node.get('nodes')) == 0:
                windows.append(node)
            # Nested node
            else:
                for inner_node in node.get('nodes'):
                    nodes.append(inner_node)

        return windows

    def active_window():
        cmd = 'swaymsg -t get_tree) | jq ".. | select(.type?) | select(.focused==true).id"'

    async def focus_next_window(self):
        await asyncio.sleep(random.random() * 3)
        t = round(time.time() - self.start_time, 1)
        logging.info("Finished task: {}".format(t))

        if len(self.switching_windows) == 0:
            self.switching_windows = self.get_windows_whitelist()
            if len(self.switching_windows) == 0:
                logging.warning("display: Expected windows to display but there is none")

                return

        next_window = self.switching_windows.pop()
        logging.info("display: Switching focus to: ".format(next_window["id"]))
        cmd = "swaymsg [con_id={}] focus".format(next_window["id"])

        p = subprocess.Popen(cmd,
                             shell=True)

        p.communicate()[0]

    async def fullscreen_next_window(self):
        await asyncio.sleep(random.random() * 3)
        t = round(time.time() - self.start_time, 1)
        logging.info("Finished task: {}".format(t))

        if len(self.switching_windows) == 0:
            self.switching_windows = self.get_windows_whitelist()
            if len(self.switching_windows) == 0:
                logging.warning("display: Expected windows to display but there is none")

                return

        next_window = self.switching_windows.pop()
        logging.info("display: Switching focus to: ".format(next_window["id"]))

        cmd = "swaymsg [con_id={}] fullscreen".format(next_window["id"])

        p = subprocess.Popen(cmd,
                             shell=True)

        p.communicate()[0]

    async def task_scheduler(self, interval_s, interval_function):
        while True:
            logging.info("Starting periodic function: {}"\
                         .format(round(time.time() - self.start_time, 1)))
            await asyncio.gather(
                asyncio.sleep(interval_s),
                interval_function(),
            )

    def switch_workspace(self):
        cmd = "swaymsg workspace {}".format(next_ws)

        p = subprocess.Popen(cmd,
                             shell=True,
                             encoding="utf8")

        res = p.communicate()[0]



if __name__ == "__main__":

    parser = configargparse.ArgParser(description="")
    parser.add_argument('--debug',
                        dest='debug',
                        env_var='DEBUG',
                        help="Show debug output",
                        type=bool,
                        default=False)
    parser.add_argument('--uri',
                        dest='uris',
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
    parser.add_argument('--location',
                        dest='location',
                        env_var='LOCATION',
                        help="The location to gather data like weather for",
                        type=str,
                        default="Berlin")
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
    # workaround: Make url a new list if first element contains a '|'
    # since we can specify --uri multiple times but not URI as
    # an env var. We use pipe: | as seperator since it is not allowed in URIs
    if args.uris[0].find("|") != -1:
        args.uris = args.uris[0].split("|")

    debug = args.debug
    uris = args.uris
    stream_source = args.stream_source
    stream_source_device = args.stream_source_device
    img_path = args.img_path
    listen_address = args.listen_address
    listen_port = args.listen_port
    probe_ip = args.probe_ip
    location = args.location
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
            logging.debug(System.list_processes())

    if listen_port < 1025 or listen_port > 65535:
        logging.error("Invalid port, aborting..")
        sys.exit(1)

    if stream_source not in stream_sources:
        sources_str = " ".join(str(x) for x in stream_sources)
        logging.error("Invalid source, aborting..")
        logging.info("Possible choices are: " + sources_str)
        sys.exit(1)

    hostname = socket.gethostname()
    local_ip = System.net_local_iface_address(probe_ip)

    display = Display(local_ip)
    nwins = len(display.get_windows())
    if nwins > 0:
        logging.warning("Expected no windows but found {}"
                        .format(nwins))

    playlist = Playlist(uris, 5, location)
    threads = playlist.start_player()
    logging.info("Started {} sources".format(len(threads)))

    stream = Stream(stream_source)

    # Publish service on the network via mDNS
    if zeroconf_publish_service:
        zc_listen_address = listen_address

        if "0.0.0.0" == zc_listen_address:
            zc_listen_address = System.net_local_iface_address(probe_ip)

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
            zc.zc_unregister_service()

        logging.shutdown()

        sys.exit(0)

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)

    # Change view regularly
    display.start_time = time.time()
    #asyncio.run(display.task_scheduler(5, display.fullscreen_next_window))

    # Start webserver
    wserver.run(host=listen_address)
