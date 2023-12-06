#!/usr/bin/env python3
"""Radio Blue Queue Manager"""
# pylint: disable=C0116,R0902,R0912,R0914,R0915,R0904,W1203,W0718,W0212

import os
import time
import sys
import json
import logging
import base64
import threading
import subprocess
import traceback
import shutil
import math
import numpy
import requests

from datetime import datetime
from flask import Flask, jsonify

from InquirerPy import inquirer
from InquirerPy.base import Choice

from plexapi.server import PlexServer
from plexapi.playqueue import PlayQueue
from plexapi.myplex import MyPlexAccount

app = Flask(__name__)

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("__main__").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


DEFAULT_STREAMS = [
    'http://192.168.1.120:8000/stream','http://radioblue.net:8000/stream/stream.mp3']
SERVER_URL = "http://127.0.0.1:32400"
SERVER_TOKEN = os.getenv("PLEX_TOKEN", "")
CLIENT_NAME = os.getenv("CLIENT_NAME", "MyPlexamp")
LIBRARY_SECTION = os.getenv("LIBRARY_SECTION", "Music")
TIDBYT_SERVER = "http://192.168.1.120:5123"
CONFIG_FILE = "config.json"
ENABLE_ARTWORK = False
ITEMS_BEFORE_SILENCE = 6
NOW_PLAYING = """
Title: {title}
Artist: {artist_name} 
Album: {album_name} 
ArtworkData: {artwork_data} 
Artwork: {artwork_url}
Time: {length} 
"""


class RadioBlueQueue:
    """Handle queueing for radio broadcast"""

    def __init__(self):
        """init"""
        self.options = {}
        self.play_queue = None
        self.client = None
        self.queued_songs = {}
        self.played_songs = {}
        self.currently_playing = {}
        self.playing_next = {}
        self.ready = False
        self.state = "starting"
        self.used_silence_positions = []
        self.server = None
        self.playlists = []
        self.added_items = 0
        self.paused = False
        self.time_since_stream_audio = 0
        self.stream_online = False
        self.server_play_queue = None
        self.track_log = f'./track_log_{time.time()}.txt'

    def setup(self):
        self.options = self.get_all_options()
        self.playlists = self.load_playlists()
        self.play_queue = self.init_play_queue()
        self.client = self.get_client()

    def connect_client(self):
        """Get client"""
        self.client = self.get_client()

    def load_config(self):
        """Load config"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as config_fh:
                self.options = json.loads(config_fh.read())

    def load_playlists(self):
        """Load all playlists"""
        output = {}
        output["on-air"] = self.server.playlist(self.options.get("on_air_playlist"))
        return output

    def init_play_queue(self):
        music_section = self.server.library.section(LIBRARY_SECTION)
        items = []
        if self.options.get("silence_track"):
            for track in music_section.searchTracks(
                guid=self.options.get("silence_track")
            ):
                items.append(track)
        return PlayQueue.create(self.server, items)

    def play(self):
        self.client.playMedia(self.play_queue)

    def get_all_options(self):
        """Fetch all options via inquirer or cfg"""
        prev_options = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as config_fh:
                prev_options = json.loads(config_fh.read())
            confirm = inquirer.confirm(
                message="Use previous config?", default=True
            ).execute()
            if confirm:
                self.options = prev_options
                self.test_server_connection()
                playlist_options = self.get_playlist_options(prev_options)
                self.options.update(playlist_options)
                return prev_options

        options = self.get_connection_options(prev_options)
        self.options = options
        self.test_server_connection()
        client_options = self.get_client_options(prev_options)
        options.update(client_options)
        playlist_options = self.get_playlist_options(prev_options)
        options.update(playlist_options)

        if os.path.exists(CONFIG_FILE):
            shutil.copyfile(CONFIG_FILE, f'{CONFIG_FILE}.{time.time()}')
        with open(CONFIG_FILE, "w", encoding="utf-8") as config_fh:
            options_cp = options.copy()
            if options_cp.get("password"):
                del options_cp["password"]
            LOG.debug(options_cp)
            config_fh.write(json.dumps(options_cp))
            LOG.info(f"Write config file: {CONFIG_FILE}")
        return options

    def server_connection(self):
        """Connect to a server"""
        server = None
        if self.options.get("server_url"):
            server = PlexServer(
                self.options.get("server_url"), self.options.get("server_token")
            )
        elif self.options.get("username"):
            if not self.options.get("password"):
                self.options["password"] = inquirer.secret(
                    message="Plex.tv Password",
                ).execute()
            LOG.info(f"Logging into My Plex as {self.options['username']}...")
            logging.getLogger("plexapi").setLevel(logging.CRITICAL)
            account = MyPlexAccount(self.options["username"], self.options["password"])
            server = account.resource(self.options.get("server_name")).connect()
            logging.getLogger("plexapi").setLevel(logging.WARNING)
        return server

    def test_server_connection(self):
        """Test connecting to a server"""
        server = self.server_connection()
        self.server = server
        server.library.section("Music")
        LOG.info("Connection to server OK")

    def get_playlist_options(self, old_options):
        """Get options for playlists within a server"""
        options = {}
        on_air_playlist_options = []
        playlists = {}

        for plist in self.server.playlists():
            playlists[plist.updatedAt.timestamp()] = plist

        sorted_keys = sorted(playlists)
        sorted_keys.reverse()
            
        for key in sorted_keys:
            plist = playlists.get(key) 
            title = f'{plist.title}'
            on_air_playlist_options.append(Choice(title))

        options["on_air_playlist"] = inquirer.select(
            message="Select which playlist will broadcast on-air",
            choices=on_air_playlist_options,
        ).execute()

        on_deck_playlist_options = []
        for plist in self.server.playlists():
            title = plist.title
            on_deck_playlist_options.append(Choice(title))
        return options

    def get_client_options(self, old_options):
        options = {}
        client_options = []
        for client in self.server.clients():
            title = client.title
            client_options.append(Choice(title))
        options["client_name"] = inquirer.select(
            message="Select which Plex client to play media on",
            default=old_options.get("client_name"),
            choices=client_options,
        ).execute()
        options["silence_track"] = inquirer.text(
            message="Silence track GUID (Optional)",
            default=old_options.get("silence_track", ""),
        ).execute()
        stream_choices = []
        for stream_url in DEFAULT_STREAMS:
            stream_choices.append(Choice(stream_url))
        options["stream_url"] = inquirer.select(
            message="External Stream URL",
            default=old_options.get("stream_url"),
            choices=stream_choices).execute()
        return options

    def get_connection_options(self, old_options):
        """Get plex connection options"""
        options = {}

        connection_method_choices = [
            Choice("local_ip", name="Local IP address")
        ]
        options["connection_method"] = inquirer.select(
            message="Choose a method to find your Plex server",
            default=old_options.get("connection_method"),
            choices=connection_method_choices,
        ).execute()
        if options["connection_method"] == "local_ip":
            server_url_default = old_options.get("server_url") or SERVER_URL
            options["server_url"] = inquirer.text(
                message="Enter Plex Server URL", default=server_url_default
            ).execute()
            options["server_token"] = inquirer.text(
                message="Enter Plex Server Token",
                default=old_options.get("server_token", ""),
            ).execute()
            options["server_name"] = inquirer.text(
                message="Plex Server Name",
                default=old_options.get("server_name", ""),
            ).execute()

        return options

    def get_client(self):
        """Fetch the plex client"""
        self.client = self.server.client(self.options["client_name"])
        return self.client

    def refresh_play_queue_from_server(self):
        """Pull the PQ from the server"""
        self.server_play_queue = self.play_queue.get(
            self.server, self.play_queue.playQueueID)

    def refresh_play_queue(self):
        """Refresh the play queue"""
        self.client.refreshPlayQueue(self.play_queue)

    def sync_playlist(self):
        """Sync the play queue and play list"""
        playlists = self.load_playlists()
        queue_items = {}
        for fqueue_item in self.play_queue.items:
            # LOG.debug(f"{fqueue_item.title} - {fqueue_item.playQueueItemID}")
            if not queue_items.get(fqueue_item.guid):
                queue_items[fqueue_item.guid] = []
            queue_items[fqueue_item.guid].append(fqueue_item.playQueueItemID)

        play_pos = 0
        for song in playlists.get("on-air"):
            play_pos += 1
            if song.guid in queue_items and song.guid != self.options.get(
                "silence_track"
            ):
                # LOG.debug(f"{song.title} has already been played: {song}")
                continue
            if (
                song.guid == self.options.get("silence_track")
                and play_pos in self.used_silence_positions
            ):
                # LOG.debug(f'Skipping silence re-add')
                continue
            if song.guid != self.options.get("silence_track") and self.queued_songs.get(
                song.guid
            ):
                continue

            LOG.debug(f"Adding {song.title} to queue")
            if song.guid == self.options.get("silence_track"):
                # LOG.debug(f"Marking silence position {play_pos} as used")
                self.used_silence_positions.append(play_pos)

            self.queued_songs[song.guid] = song
            try:
                self.play_queue.addItem(song)
            except Exception:
                LOG.error("Failed to add item to play queue")
        self.refresh_play_queue()

    def get_artwork(self, suffix):
        headers = {"X-Plex-Token": self.options.get("server_token")}
        url = f'{self.options.get("server_url")}{suffix}'
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return base64.b64encode(response.content).decode("utf-8")

    def update_now_playing(self):
        """Update the now playing text pointer"""
        for session in self.server.sessions():
            if session.player.title != self.options["client_name"]:
                continue
            if self.currently_playing.get("title") == session.title:
                continue
            ms = session.duration
            seconds, ms = divmod(ms, 1000)
            minutes, seconds = divmod(seconds, 60)
            duration = f"{int(minutes):01d}:{int(seconds):02d}"
            artwork_data = ""
            if ENABLE_ARTWORK:
                try:
                    artwork_data = self.get_artwork(session.art)
                except Exception:
                    LOG.error("Failed to fetch artwork")

            self.currently_playing = {"title": session.title, "guid": session.guid}
            LOG.debug(f"Now playing: {session.title}")

            # auto on-mic
            if session.guid == self.options.get("silence_track"):
                LOG.debug("Enabling mic due to silence track")
                mic_on()
            album = session.album() 
            with open(self.track_log, 'a', encoding='utf-8') as track_log_fh:
                track_string = f'{session.title} by {session.grandparentTitle} ' \
                               f'({album.year})'
                track_log_fh.write(track_string + "\n")
            LOG.debug(f"Adding {track_string} to {self.track_log}")
            
            ps_key = session.guid
            self.played_songs[ps_key] = True

            is_next_track = False
            for item in self.play_queue:
                if item.guid == session.guid:
                    is_next_track = True
                    continue
                if is_next_track:
                    self.playing_next = {"title": item.title, "guid": item.guid}
                    break

            track_title = session.title
            if track_title == "Silence":
                track_title = "On mic"

            now_playing_txt = NOW_PLAYING.format(
                title=track_title,
                artist_name=session.grandparentTitle,
                album_name=session.parentTitle,
                artwork_url=session.art,
                artwork_data=artwork_data,
                length=duration,
            )
            with open("./Now Playing.txt", "w", encoding="utf-8") as out_fh:
                out_fh.write(now_playing_txt)

    def update_stats(self):
        """Update time remaining"""
        track_title = ""
        if self.currently_playing:
            track_title = self.currently_playing.get("title")

        if not self.server_play_queue:
            return

        total_duration = 0
        queue_count = 0
        on_mic = ""
        time_til_silence = 0
        silence_tracker_armed = False
        silence_tracker_has_been_armed = False
        for item in self.server_play_queue.items:
            if item.playQueueItemID <= self.server_play_queue.playQueueSelectedItemID:
                continue
            is_silence_track = False
            if item.guid == self.options.get("silence_track"):
                silence_tracker_armed = False
                is_silence_track = True
                silence_tracker_has_been_armed = True
            this_duration = item.duration
            if is_silence_track:
                this_duration = 0
                if item.guid != self.currently_playing.get('guid'):
                    silence_tracker_armed = True
            if self.currently_playing and \
                    self.currently_playing.get("guid") == item.guid and \
                    is_silence_track:
                on_mic = "now"
            if track_title != item.title and not is_silence_track:
                queue_count += 1
            if silence_tracker_armed:
                on_mic = "queued"
            else:
                if not is_silence_track and not silence_tracker_has_been_armed:
                    time_til_silence += item.duration
                    #LOG.debug(f"Adding {item.duration} for {item.title}")
            # LOG.debug(f"Adding duration {this_duration} for {item.title}")
            total_duration += this_duration
        if self.playing_next and self.playing_next.get("guid") == self.options.get(
            "silence_track"
        ):
            on_mic = "next"

        mediatype = None
        for mediatype in self.client.timelines():
            if not mediatype.time:
                continue
            if not mediatype.duration:
                continue
            break
        if not mediatype.time or not mediatype.duration:
            return
        track_time_left = mediatype.duration - mediatype.time
        if not track_time_left:
            return
        if math.isnan(track_time_left):
            return

        if on_mic:
            time_til_silence += mediatype.duration
            time_til_silence -= mediatype.time

        seconds = int((int(track_time_left) / 1000) % 60)
        minutes = int((int(track_time_left) / (1000 * 60)) % 60)
        hours = (int(track_time_left) / (1000 * 60 * 60)) % 24
        percent = int((mediatype.time / mediatype.duration) * 100)

        total_duration += track_time_left
        td_seconds = int((total_duration / 1000) % 60)
        td_minutes = int((total_duration / (1000 * 60)) % 60)
        td_hours = int((total_duration / (1000 * 60 * 60)) % 60)

        ts_seconds = 0
        ts_minutes = 0
        if time_til_silence:
            ts_seconds = int((time_til_silence / 1000) % 60)
            ts_minutes = int((time_til_silence / (1000 * 60)) % 60)

        if track_time_left < 30000:
            track_left_color = "#ff0000"
        elif track_time_left < 60000:
            track_left_color = "#ff9500"
        else:
            track_left_color = "#00ff00"

        if time_til_silence < 60000:
            mic_color = "#ff0000"
        elif time_til_silence < 120000:
            mic_color = "#ff9500"
        else:
            mic_color = "#ffffff"

        queue_color = "#0000ff"
        if queue_count < 1:
            queue_color = "#ff0000"
        elif queue_count < 2:
            queue_color = "#ff9500"
        else:
            queue_color = "#00ff00"

        mic_live = False
        if os.path.exists("./mic.indicator"):
            mic_color = "#ff0000"
            mic_live = True

        if track_title == 'Silence':
            track_title = 'On mic'

        timeleft_data = {
            "hours": hours,
            "minutes": f"{minutes:02}",
            "seconds": f"{seconds:02}",
            "td_hours": f"{td_hours:02}",
            "td_minutes": f"{td_minutes:02}",
            "td_seconds": f"{td_seconds:02}",
            "ts_minutes": f"{ts_minutes:02}",
            "ts_seconds": f"{ts_seconds:02}",
            "queue_count": f"{queue_count:02}",
            "queue_color": queue_color,
            "track_left_color": track_left_color,
            "track_title": track_title,
            "mic_live": mic_live,
            "percent": percent,
            "on_mic": on_mic,
            "mic_live": mic_live,
            "mic_color": mic_color,
            "stream_online": self.stream_online,
            "time_since_stream_audio": self.time_since_stream_audio,
        }
        with open("./timeleft.json", "w", encoding="utf-8") as tl_fh:
            tl_fh.write(json.dumps(timeleft_data))

    def tidbyt(self, starlet_file="onair"):
        """Render and push a tidbyt image"""
        with open(f"{starlet_file}.star", "rb") as fileh:
            requests.post(f"{TIDBYT_SERVER}/serve", files={"data": fileh}, timeout=15)

    def stop_ah(self):
        cmd = [
            "open",
            "stop.ahcommand",
        ]
        subprocess.run(cmd, check=True)

    def start_ah(self):
        cmd = ["open", "start.ahcommand"]
        subprocess.run(cmd, check=True)

    def stop(self):
        """Stop client from playing"""
        self.state = "stopping"
        #self.client.pause()

    def next_track(self):
        """Skip client to next track"""
        self.client.skipNext()

    def pause(self):
        """Pause"""
        if self.paused:
            self.client.play()
            self.paused = False
        else:
            self.client.pause()
            self.paused = True

    def unpause(self):
        """Play"""
        self.client.play()

    def delete_last(self):
        """Play"""
        last_item = self.play_queue.items[-1]
        self.play_queue.removeItem(last_item)
        self.refresh_play_queue()

    def add_silence(self):
        """Add silence to the queue"""
        music_section = self.server.library.section("Music")
        if self.options.get("silence_track"):
            for track in music_section.searchTracks(
                guid=self.options.get("silence_track")
            ):
                try:
                    self.play_queue.addItem(track)
                except Exception:
                    pass
            self.refresh_play_queue()

    def get_stream(self):
        """Fetch the mp3 stream"""
        stream_url = self.options.get('stream_url', '')
        return requests.get(stream_url, stream=True)


def web(rbq):
    """Run web server"""
    app.config["rbq"] = rbq
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5050)


@app.route("/")
def timeleft():
    with open("./timeleft.json", "r", encoding="utf-8") as tl_fh:
        try:
            data = json.loads(tl_fh.read())
        except json.decoder.JSONDecodeError:
            data = {}
    return jsonify(data)


@app.route("/next")
def next_track():
    """hello"""
    app.config["rbq"].next_track()
    mic_off()
    return "next track"


@app.route("/pause")
def pause():
    """hello"""
    app.config["rbq"].pause()
    return "pause"


@app.route("/unpause")
def unpause():
    """hello"""
    app.config["rbq"].unpause()
    return "unpause"


@app.route("/delete_last")
def delete_last():
    """hello"""
    app.config["rbq"].delete_last()
    return "delete"


@app.route("/mic_off")
def mic_off():
    """hello"""
    diff_time = 0
    if app.config.get("last_mute"):
        diff_time = time.time() - app.config.get("last_mute")
 
    if diff_time and diff_time < 2:
        with open('./debug.txt', 'a') as dw:
            dw.write(f"{time.time()} - debouncing mic off: {diff_time}\n")
        return "ok"

    app.config["last_mute"] = time.time()
    subprocess.run(['./mute.sh'])
    subprocess.run(['./offmic.sh'])
    with open('./debug.txt', 'a') as dw:
        dw.write(f"{time.time()} - mic off\n")
    return "mic off"


@app.route("/mic_on")
def mic_on():
    """hello"""
    diff_time = 0
    if app.config.get("last_unmute"):
        diff_time = time.time() - app.config.get("last_unmute")
 
    if diff_time and diff_time < 2:
        with open('./debug.txt', 'a') as dw:
            dw.write(f"{time.time()} - debouncing mic on: {diff_time}\n")
        return "ok"

    app.config["last_unmute"] = time.time()
 
    subprocess.run(['./unmute.sh'])
    subprocess.run(['./onmic.sh'])
    with open('./debug.txt', 'a') as dw:
        dw.write(f"{time.time()} - mic on\n")
    return "mic on"


@app.route("/mic_toggle")
def mic_toggle():
    """hello"""
    with open('./debug.txt', 'a') as dw:
        dw.write(f"{time.time()} - mic toggle")

    if os.path.exists('./mic.indicator'):
        mic_off() 
    else:
        mic_on()
    return "mic toggle"


@app.route("/silence")
def add_silence():
    """queue up silence"""
    app.config["rbq"].add_silence()
    return "add silence"

@app.route("/track_log")
def track_log():
    track_log = ""
    with open(app.config["rbq"].track_log, 'r', encoding='utf-8') as track_fh:
        track_log = track_fh.read().splitlines()
    track_log.reverse()
    return track_log



def update_status(rbq):
    """Update status"""
    while True:
        if not rbq.ready:
            time.sleep(1)
            continue
        try:
            rbq.update_stats()
        except Exception:
            LOG.info(traceback.format_exc())
        try:
            rbq.update_now_playing()
        except Exception:
            LOG.info(traceback.format_exc())
 
        time.sleep(0.5)


def get_stream(rbq):
    """Fetch the mp3 stream"""
    return requests.get(rbq.get('options').get('stream_url', ''), stream=True)


def dead_air_detector(rbq):
    """Detect dead air"""
    last_audio_time = time.time() 
    while True:
        radiostream = rbq.get_stream() 
        for block in radiostream.iter_content(4096):
            samps = 0
            try:
                samps = numpy.frombuffer(block, dtype = numpy.int16)
            except ValueError:
                rbq.stream_online = False
                time.sleep(1)
                radiostream = rbq.get_stream()
                continue
            rbq.stream_online = True
            try:
                rms = numpy.sqrt(numpy.mean(samps**2))
            except Exception:
                LOG.error(f"sampe debug: {samps}")
                continue
            db = 20*numpy.log10(rms)
            if not math.isnan(db) and db < 30:
                last_audio_time = time.time()
            diff_time = time.time() - last_audio_time
            rbq.time_since_stream_audio = int(diff_time)


def main():
    """Main"""
    rbq = RadioBlueQueue()
    rbq.tidbyt("onair")
    rbq.setup()
    # rbq.start_ah()
    rbq.play()

    threading.Thread(target=web, daemon=True, args=(rbq,)).start()
    threading.Thread(target=update_status, args=(rbq,), daemon=True).start()
    threading.Thread(target=dead_air_detector, args=(rbq,), daemon=True).start()
    try:
        rbq.tidbyt("nowplaying")
        while True:
            logging.getLogger("plexapi").setLevel(logging.INFO)
            try:
                rbq.sync_playlist()
                rbq.refresh_play_queue_from_server() 
                rbq.ready = True
            except Exception:
                LOG.error(traceback.format_exc())
                LOG.error("Exception from plex api, retrying...")
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Keyboard interrupt, shutting down")
        # rbq.stop_ah()
        rbq.stop()
        time.sleep(1)
        rbq.tidbyt("offair")
        sys.exit()


if __name__ == "__main__":
    main()
