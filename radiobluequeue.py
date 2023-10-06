#!/usr/bin/env python3
"""Radio Blue Queue Manager"""

import os
import time
import sys
import json
import logging

from InquirerPy import inquirer
from InquirerPy.base import Choice

from plexapi.server import PlexServer
from plexapi.playqueue import PlayQueue
from plexapi.playlist import Playlist
from plexapi.myplex import MyPlexAccount

LOG = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG)
logging.getLogger("__main__").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)


SERVER_URL = 'http://127.0.0.1:32400'
SERVER_TOKEN = os.getenv('PLEX_TOKEN', 'p2QAMVvT3kC2LPcU827e')
CLIENT_NAME = os.getenv('CLIENT_NAME', 'WorkPlexamp')
LIBRARY_SECTION = os.getenv('LIBRARY_SECTION', 'Music')
CONFIG_FILE = 'config.json'

class RadioBlueQueue:
    """Handle queueing for radio broadcast"""
    def __init__(self):
        """init"""
        self.options = {}
        self.play_queue = None
        self.client = None
        self.played_songs = {}

    def setup(self):
        self.options = self.get_all_options()
        self.playlists = self.load_playlists()
        self.play_queue = self.init_play_queue(
            [self.playlists['on-air'][0]])
        self.client = self.get_client()

    def load_playlists(self):
        """Load all playlists"""
        output = {}
        output['on-air'] = self.server.playlist(self.options.get('on_air_playlist'))
        LOG.debug("Playlists loaded")
        LOG.debug(output)
        return output

    def init_play_queue(self, items):
        for item in items:
            self.played_songs[item.title] = item
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

    def refresh_play_queue(self):
        """Refresh the play queue"""
        self.client.refreshPlayQueue(self.play_queue)

    def sync_playlist(self):
        """Sync the play queue and play list"""
        playlists = self.load_playlists()
        for song in playlists.get('on-air'):
            if song.title in self.played_songs:
                LOG.debug(f'{song.title} has already been played')
                continue
            LOG.debug(f'Adding {song.title} to queue')
            self.played_songs[song.title] = song
            self.play_queue.addItem(song)
            self.refresh_play_queue()
            print(song.title)

        # iterate over queue and remove anything not in playlist

        # confirm order?

def main():
    """Main"""
    rbq = RadioBlueQueue()
    rbq.setup()

    for item in rbq.playlists.get('on-air'):
        print(item.title)
    rbq.play()
    while True:
        LOG.debug("Syncing playlist...")
        logging.getLogger("plexapi").setLevel(logging.INFO)
        rbq.sync_playlist()
        time.sleep(1)

if __name__ == '__main__':
    main()
