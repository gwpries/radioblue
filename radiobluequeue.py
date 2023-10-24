#!/usr/bin/env python3
"""Radio Blue Queue Manager"""

import os
import time
import sys
import json
import logging
import requests
import base64
import threading
import subprocess
import signal

from flask import Flask, jsonify
app = Flask(__name__)

from InquirerPy import inquirer
from InquirerPy.base import Choice

from plexapi.server import PlexServer
from plexapi.playqueue import PlayQueue
from plexapi.playlist import Playlist
from plexapi.myplex import MyPlexAccount
from plexapi.audio import Audio
import plexapi.exceptions

LOG = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG)
logging.getLogger("__main__").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


SERVER_URL = 'http://127.0.0.1:32400'
SERVER_TOKEN = os.getenv('PLEX_TOKEN', '')
CLIENT_NAME = os.getenv('CLIENT_NAME', 'MyPlexamp')
LIBRARY_SECTION = os.getenv('LIBRARY_SECTION', 'Music')
PIXLET_PATH = '/usr/local/bin/pixlet'
CONFIG_FILE = 'config.json'
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

    def setup(self):
        self.options = self.get_all_options()
        self.playlists = self.load_playlists()
        self.play_queue = self.init_play_queue()
        self.client = self.get_client()

    def load_playlists(self):
        """Load all playlists"""
        output = {}
        output['on-air'] = self.server.playlist(self.options.get('on_air_playlist'))
        return output

    def init_play_queue(self):
        music_section = self.server.library.section("Music")
        items = []
        if self.options.get('silence_track'):
            for track in music_section.searchTracks(guid=self.options.get('silence_track')):
                items.append(track)
        return PlayQueue.create(self.server, items)

    def play(self):
        self.client.playMedia(self.play_queue)

    def get_all_options(self):
        """Fetch all options via inquirer or cfg"""
        prev_options = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as config_fh:
                prev_options = json.loads(config_fh.read())
            confirm = inquirer.confirm(
                message="Use previous config?",
                default=True).execute()
            if confirm:
                self.options = prev_options
                self.test_server_connection()
                playlist_options = self.get_playlist_options(prev_options)
                self.options.update(playlist_options)
                return prev_options

        options = self.get_connection_options(prev_options)
        self.options = options
        self.test_server_connection()
        playlist_options = self.get_playlist_options(prev_options)
        options.update(playlist_options)
        client_options = self.get_client_options(prev_options)
        options.update(client_options)

        with open(CONFIG_FILE, 'w', encoding='utf-8') as config_fh:
            options_cp = options.copy()
            if options_cp.get('password'):
                del options_cp['password']
            LOG.debug(options_cp)
            config_fh.write(json.dumps(options_cp))
            LOG.info(f"Write config file: {CONFIG_FILE}")
        return options

    def server_connection(self):
        """Connect to a server"""
        server = None
        if self.options.get('server_url'):
            server = PlexServer(
                self.options.get('server_url'),
                self.options.get('server_token'))
        elif self.options.get('username'):
            if not self.options.get('password'):
                self.options['password'] = inquirer.secret(
                    message=f"Plex.tv Password",
                ).execute()
            LOG.info(f"Logging into My Plex as {self.options['username']}...")
            logging.getLogger("plexapi").setLevel(logging.CRITICAL)
            account = MyPlexAccount(
                self.options['username'],
                self.options['password'])
            server = account.resource(self.options.get('server_name')).connect()
            logging.getLogger("plexapi").setLevel(logging.WARNING)
        return server

    def test_server_connection(self):
        """Test connecting to a server"""
        server = self.server_connection()
        self.server = server
        music = server.library.section("Music")
        LOG.info("Connection to server OK")

    def get_playlist_options(self, old_options):
        """Get options for playlists within a server"""
        options = {}
        on_air_playlist_options = []
        for plist in self.server.playlists():
            title = plist.title
            on_air_playlist_options.append(
                Choice(title))
        options['on_air_playlist'] = inquirer.select(
            message="Select which playlist will broadcast on-air",
            default=old_options.get('on_air_playlist'),
            choices=on_air_playlist_options
        ).execute()

        on_deck_playlist_options = []
        for plist in self.server.playlists():
            title = plist.title
            on_deck_playlist_options.append(
                Choice(title))
        return options

    def get_client_options(self, old_options):
        options = {}
        client_options = []
        for client in self.server.clients():
            title = client.title
            client_options.append(
                Choice(title))
        options['client_name'] = inquirer.select(
            message="Select which Plex client to play media on",
            default=old_options.get('client_name'),
            choices=client_options
        ).execute()
        options['pixlet_path'] = inquirer.text(
            message="If you have a tidbyt, point to pixlet binary",
            default=old_options.get('pixlet_path', PIXLET_PATH)
        ).execute()
        if os.path.exists(options['pixlet_path']):
            options['tidbyt_api_token'] = inquirer.text(
                message="Tidbyt API Token",
                default=old_options.get('tidbyt_api_token', '')
            ).execute()
            options['tidbyt_device_id'] = inquirer.text(
                message="Tidbyt Device ID",
                default=old_options.get('tidbyt_device_id', '')
            ).execute()
        options['silence_track'] = inquirer.text(
            message="Silence track GUID (Optional)",
            default=old_options.get('silence_track', '')
        ).execute()
        return options

    def get_connection_options(self, old_options):
        """Get plex connection options"""
        options = {}

        connection_method_choices = [
            Choice('local_ip', name='Local IP address'),
            Choice('plex_discovery', name='Plex.tv Discovery')
        ]
        options['connection_method'] = inquirer.select(
            message="Choose a method to find your Plex server",
            default=old_options.get('connection_method'),
            choices=connection_method_choices
        ).execute()
        if options['connection_method'] == 'local_ip':
            server_url_default = old_options.get('server_url') or SERVER_URL
            options['server_url'] = inquirer.text(
                message=f"Enter Plex Server URL",
                default=server_url_default
            ).execute()
            options['server_token'] = inquirer.text(
                message=f"Enter Plex Server Token",
                default=old_options.get('server_token', '')
            ).execute()
            options['server_name'] = inquirer.text(
                message=f"Plex Server Name",
                default=old_options.get('server_name', ''),
            ).execute()
        elif options['connection_method'] == 'plex_discovery':
            options['username'] = inquirer.text(
                message=f"Plex.tv E-mail",
                default=old_options.get('username', '')
            ).execute()
            options['password'] = inquirer.secret(
                message=f"Plex.tv Password",
            ).execute()

            LOG.info(f"Logging into My Plex as {options['username']}...")
            account = MyPlexAccount(options['username'], options['password'])
            LOG.info("Discovering available Plex servers (this is slow)...")
            logging.getLogger("plexapi").setLevel(logging.CRITICAL)
            history = account.history()
            logging.getLogger("plexapi").setLevel(logging.WARNING)

            all_servers = []
            server_choices = []
            for item in history:
                server_name = item._server.friendlyName
                if server_name not in all_servers:
                    all_servers.append(server_name)
                    server_choices.append(
                        Choice(server_name))
            options['server_name'] = inquirer.select(
                message=f"Plex Server Name",
                default=old_options.get('server_name'),
                choices=server_choices
            ).execute()

        return options

    def get_client(self):
        """Fetch the plex client"""
        return self.server.client(self.options['client_name'])

    def refresh_play_queue_from_server(self):
        """Pull the PQ from the server"""
        self.play_queue = self.play_queue.get(self.server, self.play_queue.playQueueID)

    def refresh_play_queue(self):
        """Refresh the play queue"""
        self.client.refreshPlayQueue(self.play_queue)

    def sync_playlist(self):
        """Sync the play queue and play list"""
        playlists = self.load_playlists()
        full_queue = self.play_queue.get(self.server, playQueueID=self.play_queue.playQueueID)
        LOG.debug(f"QUEUE POSITION: {full_queue.playQueueSelectedItemID}")
        queue_items = {}
        for fqueue_item in full_queue:
            #LOG.debug(f"{fqueue_item.title} - {fqueue_item.playQueueItemID}")
            if not queue_items.get(fqueue_item.guid):
                queue_items[fqueue_item.guid] = []
            queue_items[fqueue_item.guid].append(fqueue_item.playQueueItemID) 
 
        play_pos = 0
        for song in playlists.get('on-air'):
            play_pos += 1
            if song.guid in queue_items and song.guid != self.options.get('silence_track'):
                #LOG.debug(f"{song.title} has already been played: {song}")
                continue
            if song.guid == self.options.get('silence_track') and \
                    play_pos in self.used_silence_positions:
                #LOG.debug(f'Skipping silence re-add')
                continue

            LOG.debug(f'Adding {song.title} to queue')
            if song.guid == self.options.get('silence_track'):
                #LOG.debug(f"Marking silence position {play_pos} as used")
                self.used_silence_positions.append(play_pos)
                
            self.queued_songs[song.guid] = song
            self.play_queue.addItem(song)
        self.refresh_play_queue()
        full_queue = self.play_queue.get(
            self.server, playQueueID=self.play_queue.playQueueID)
            

    def get_artwork(self, suffix):
        headers = {
            'X-Plex-Token': self.options.get('server_token')
        }
        url = f'{self.options.get("server_url")}{suffix}'
        response = requests.get(url,
            headers=headers)
        response.raise_for_status()
        return base64.b64encode(response.content).decode('utf-8')
        

    def update_now_playing(self):
        """Update the now playing text pointer"""
        for session in self.server.sessions():
            if session.player.title != self.options['client_name']:
                continue
            if self.currently_playing.get('title') == session.title:
                continue
            ms = session.duration
            seconds, ms = divmod(ms, 1000)
            minutes, seconds = divmod(seconds, 60)
            duration = f'{int(minutes):01d}:{int(seconds):02d}'
            artwork_data = ''
            try:
                artwork_data = self.get_artwork(session.art)
            except Exception:
                LOG.error("Failed to fetch artwork")

            LOG.debug(session)
            self.currently_playing = {
                'title': session.title,
            }
            ps_key = session.guid
            self.played_songs[ps_key] = True

            next_track = False
            for item in self.play_queue:
                if item.guid == session.guid:
                    next_track = True
                    continue
                if next_track:
                    self.playing_next = {
                        'title': item.title,
                        'guid': item.guid
                    }
                    break

            now_playing_txt = NOW_PLAYING.format(
                title=session.title,
                artist_name=session.grandparentTitle,
                album_name=session.parentTitle,
                artwork_url=session.art,
                artwork_data=artwork_data,
                length=duration)
            with open('./Now Playing.txt', 'w', encoding='utf-8') as out_fh:
                out_fh.write(now_playing_txt)

    def update_stats(self):
        """Update time remaining"""
        track_title = ''
        if self.currently_playing:
            track_title = self.currently_playing.get('title')

        total_duration = 0
        queue_count = 0 
        silence = ""
        for item in self.play_queue.items:
            if self.currently_playing and self.currently_playing.get('title') == item.title:
                if item.guid == self.options.get('silence_track'):
                    silence = 'now'
                total_duration += item.duration
            if self.played_songs.get(item.guid):
                continue
            if track_title != item.title:
                queue_count += 1 
            if not silence and item.guid == self.options.get('silence_track'):
                silence = "queued"
            total_duration += item.duration
        if self.playing_next and self.playing_next.get('guid') == self.options.get('silence_track'):
            silence = "next"
        td_seconds = int((total_duration / 1000) % 60)
        td_minutes = int((total_duration / (1000 * 60)) % 60)
        td_hours = int((total_duration / (1000 * 60 * 60)) % 60)

        mediatype = None
        for mediatype in self.client.timelines():
            if not mediatype.time:
                continue
            if not mediatype.duration:
                continue
            break
        curtime = mediatype.time
        curdur = mediatype.duration
        if not curtime or not curdur:
            return
        timeleft = curdur - curtime
        if not timeleft:
            return
        if timeleft == 'NaN':
            return
        millis = int(timeleft)
        seconds=(millis/1000)%60
        seconds = int(seconds)
        minutes=(millis/(1000*60))%60
        minutes = int(minutes)
        hours=(millis/(1000*60*60))%24
        curtimemin = int(curtime)/60000
        curdurmin = int(curdur)/60000
        percent = int((curtimemin / curdurmin) * 100)

        total_duration -= curtime
        td_seconds = int((total_duration / 1000) % 60)
        td_minutes = int((total_duration / (1000 * 60)) % 60)
        td_hours = int((total_duration / (1000 * 60 * 60)) % 60)

        if timeleft < 30000:
            track_left_color = "#ff0000"
        elif timeleft < 60000:
            track_left_color = "#ff9500"
        else:
            track_left_color = "#00ff00"

        queue_color = '#0000ff'
        if queue_count < 1:
            queue_color = "#ff0000"
        elif queue_count < 2:
            queue_color = "#ff9500"
        else:
            queue_color = "#00ff00"

        timeleft = {
            'hours': hours,
            'minutes': f'{minutes:02}',
            'seconds': f'{seconds:02}',
            'td_hours': f'{td_hours:02}',
            'td_minutes': f'{td_minutes:02}',
            'td_seconds': f'{td_seconds:02}',
            'queue_count': f'{queue_count:02}',
            'queue_color': queue_color, 
            'track_left_color': track_left_color,
            'track_title': track_title,
            'percent': percent,
            'silence': silence
        }
        with open('./timeleft.json', 'w', encoding='utf-8') as tl_fh:
            tl_fh.write(json.dumps(timeleft))

    def tidbyt(self, starlet_file="onair"):
        """Render and push a tidbyt image"""
        if not self.options.get('tidbyt_device_id'):
            return
        cmd = [PIXLET_PATH, 'render', f'{starlet_file}.star']
        subprocess.run(cmd, check=True)
        os.environ['TIDBYT_API_TOKEN'] = self.options.get('tidbyt_api_token')
        cmd = [
            PIXLET_PATH,
            'push',
            '--installation-id',
            'radioblue',
            self.options.get('tidbyt_device_id'),
            f'{starlet_file}.webp']
        subprocess.run(cmd, check=True)

    def stop_ah(self):
        cmd = [
            'open',
            'stop.ahcommand',
        ]
        subprocess.run(cmd)

    def start_ah(self):
        cmd = [
            'open',
            'start.ahcommand'
        ]
        subprocess.run(cmd)

    def stop(self):
        """Stop client from playing"""
        self.state = "stopping"
        self.client.pause()


def web():
    """Run web server"""
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5050)


def tidbyt(rbq):
    """Refresh the tidbyt"""
    while True:
        try:
            if not rbq.ready:
                rbq.tidbyt('onair')
            elif rbq.state == 'stopping':
                rbq.tidbyt('offair')
            else:
                rbq.tidbyt('nowplaying')
        except subprocess.CalledProcessError:
            pass
        time.sleep(1)


@app.route("/")
def timeleft():
    with open('./timeleft.json', 'r', encoding='utf-8') as tl_fh:
        try:
            data = json.loads(tl_fh.read())
        except json.decoder.JSONDecodeError:
            data = {} 
    return jsonify(data)


def update_status(rbq):
    """Update status"""
    while True:
        if not rbq.ready:
            time.sleep(1)
            continue
        rbq.update_stats()
        time.sleep(0.5)


def main():
    """Main"""
    rbq = RadioBlueQueue()
    rbq.setup()
    rbq.tidbyt('onair')
    rbq.start_ah()
    rbq.play()
    web_thread = threading.Thread(target=web, daemon=True).start()
    tidbyt_thread = threading.Thread(target=tidbyt, args=(rbq,), daemon=True).start()
    update_thread = threading.Thread(target=update_status, args=(rbq,), daemon=True).start()
    try:
        while True:
            logging.getLogger("plexapi").setLevel(logging.INFO)
            rbq.refresh_play_queue_from_server()
            rbq.sync_playlist()
            rbq.update_now_playing()
            rbq.ready = True
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Keyboard interrupt, shutting down")
        rbq.stop_ah()
        rbq.stop()
        time.sleep(1)
        sys.exit()

if __name__ == '__main__':
    main()
