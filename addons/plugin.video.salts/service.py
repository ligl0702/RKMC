"""
    SALTS XBMC Addon
    Copyright (C) 2014 tknorris

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import xbmc
import xbmcgui
import xbmcaddon
import time
import kodi
import log_utils
import utils
from salts_lib import salts_utils
from salts_lib import utils2
from salts_lib.utils2 import i18n
from salts_lib.constants import MODES
from salts_lib.constants import TRIG_DB_UPG
from salts_lib.db_utils import DB_Connection
from salts_lib.trakt_api import Trakt_API

COMPONENT = __name__

MAX_ERRORS = 10
log_utils.log('Service: Installed Version: %s' % (kodi.get_version()), log_utils.LOGNOTICE, COMPONENT)
db_connection = DB_Connection()
if kodi.get_setting('use_remote_db') == 'false' or kodi.get_setting('enable_upgrade') == 'true':
    if TRIG_DB_UPG:
        db_version = db_connection.get_db_version()
    else:
        db_version = kodi.get_version()
    db_connection.init_database(db_version)

class Service(xbmc.Player):
    def __init__(self, *args, **kwargs):
        log_utils.log('Service: starting...', log_utils.LOGNOTICE, COMPONENT)
        xbmc.Player.__init__(self, *args, **kwargs)
        self.win = xbmcgui.Window(10000)
        self.reset()

    def reset(self):
        log_utils.log('Service: Resetting...', log_utils.LOGDEBUG, COMPONENT)
        self.win.clearProperty('salts.playing')
        self.win.clearProperty('salts.playing.trakt_id')
        self.win.clearProperty('salts.playing.season')
        self.win.clearProperty('salts.playing.episode')
        self.win.clearProperty('salts.playing.srt')
        self.win.clearProperty('salts.playing.trakt_resume')
        self.win.clearProperty('salts.playing.salts_resume')
        self.win.clearProperty('salts.playing.library')
        self._from_library = False
        self.tracked = False
        self._totalTime = 999999
        self.trakt_id = None
        self.season = None
        self.episode = None
        self._lastPos = 0

    def onPlayBackStarted(self):
        log_utils.log('Service: Playback started', log_utils.LOGNOTICE, COMPONENT)
        playing = self.win.getProperty('salts.playing') == 'True'
        self.trakt_id = self.win.getProperty('salts.playing.trakt_id')
        self.season = self.win.getProperty('salts.playing.season')
        self.episode = self.win.getProperty('salts.playing.episode')
        srt_path = self.win.getProperty('salts.playing.srt')
        trakt_resume = self.win.getProperty('salts.playing.trakt_resume')
        salts_resume = self.win.getProperty('salts.playing.salts_resume')
        self._from_library = self.win.getProperty('salts.playing.library') == 'True'
        if playing:   # Playback is ours
            log_utils.log('Service: tracking progress...', log_utils.LOGNOTICE, COMPONENT)
            self.tracked = True
            if srt_path:
                log_utils.log('Service: Enabling subtitles: %s' % (srt_path), log_utils.LOGDEBUG, COMPONENT)
                self.setSubtitles(srt_path)
            else:
                self.showSubtitles(False)

        self._totalTime = 0
        while self._totalTime == 0:
            try:
                self._totalTime = self.getTotalTime()
            except RuntimeError:
                self._totalTime = 0
                break
            kodi.sleep(1000)

        if salts_resume:
            log_utils.log("Salts Local Resume: Resume Time: %s Total Time: %s" % (salts_resume, self._totalTime), log_utils.LOGDEBUG, COMPONENT)
            self.seekTime(float(salts_resume))
        elif trakt_resume:
            resume_time = float(trakt_resume) * self._totalTime / 100
            log_utils.log("Salts Trakt Resume: Percent: %s, Resume Time: %s Total Time: %s" % (trakt_resume, resume_time, self._totalTime), log_utils.LOGDEBUG, COMPONENT)
            self.seekTime(resume_time)

    def onPlayBackStopped(self):
        log_utils.log('Service: Playback Stopped', log_utils.LOGNOTICE, COMPONENT)
        if self.tracked:
            # clear the playlist if SALTS was playing and only one item in playlist to
            # use playlist to determine playback method in get_sources
            pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            plugin_url = 'plugin://%s/' % (kodi.get_id())
            if pl.size() == 1 and pl[0].getfilename().lower().startswith(plugin_url):
                log_utils.log('Service: Clearing Single Item SALTS Playlist', log_utils.LOGDEBUG, COMPONENT)
                pl.clear()
                
            playedTime = float(self._lastPos)
            try: percent_played = int((playedTime / self._totalTime) * 100)
            except: percent_played = 0  # guard div by zero
            pTime = utils.format_time(playedTime)
            tTime = utils.format_time(self._totalTime)
            log_utils.log('Service: Played %s of %s total = %s%%' % (pTime, tTime, percent_played), log_utils.LOGDEBUG, COMPONENT)
            if playedTime == 0 and self._totalTime == 999999:
                log_utils.log('Kodi silently failed to start playback', log_utils.LOGWARNING, COMPONENT)
            elif playedTime >= 5:
                if percent_played <= 98:
                    log_utils.log('Service: Setting bookmark on |%s|%s|%s| to %s seconds' % (self.trakt_id, self.season, self.episode, playedTime), log_utils.LOGDEBUG, COMPONENT)
                    db_connection.set_bookmark(self.trakt_id, playedTime, self.season, self.episode)
                    
                if percent_played >= 75 and self._from_library:
                    if kodi.has_addon('script.trakt'):
                        run = 'RunScript(script.trakt, action=sync, silent=True)'
                        xbmc.executebuiltin(run)
            self.reset()

    def onPlayBackEnded(self):
        log_utils.log('Service: Playback completed', log_utils.LOGNOTICE, COMPONENT)
        self.onPlayBackStopped()

service = Service()
salts_utils.do_startup_task(MODES.UPDATE_SUBS)
salts_utils.do_startup_task(MODES.PRUNE_CACHE)

was_on = False
def disable_global_cx():
    global was_on
    if kodi.has_addon('plugin.program.super.favourites'):
        active_plugin = xbmc.getInfoLabel('Container.PluginName')
        sf = xbmcaddon.Addon('plugin.program.super.favourites')
        if active_plugin == kodi.get_id():
            if sf.getSetting('CONTEXT') == 'true':
                log_utils.log('Disabling Global CX while SALTS is active', log_utils.LOGDEBUG, COMPONENT)
                was_on = True
                sf.setSetting('CONTEXT', 'false')
        elif was_on:
            log_utils.log('Re-enabling Global CX while SALTS is not active', log_utils.LOGDEBUG, COMPONENT)
            sf.setSetting('CONTEXT', 'true')
            was_on = False
    
cd_begin = 0
def check_cooldown():
    global cd_begin
    black_list = ['plugin.video.metalliq', 'plugin.video.meta']
    active_plugin = xbmc.getInfoLabel('Container.PluginName')
    if active_plugin in black_list:
        cd_begin = time.time()
    
    active = 'false' if (time.time() - cd_begin) > 30 else 'true'
    if kodi.get_setting('cool_down') != active:
        kodi.set_setting('cool_down', active)

last_label = ''
sf_begin = 0
def show_next_up():
    global last_label
    global sf_begin
    token = kodi.get_setting('trakt_oauth_token')
    if token and xbmc.getInfoLabel('Container.PluginName') == kodi.get_id() and xbmc.getInfoLabel('Container.Content') == 'tvshows':
        if xbmc.getInfoLabel('ListItem.label') != last_label:
            sf_begin = time.time()

        last_label = xbmc.getInfoLabel('ListItem.label')
        if sf_begin and (time.time() - sf_begin) >= int(kodi.get_setting('next_up_delay')):
            liz_url = xbmc.getInfoLabel('ListItem.FileNameAndPath')
            queries = kodi.parse_query(liz_url[liz_url.find('?'):])
            if 'trakt_id' in queries:
                try: list_size = int(kodi.get_setting('list_size'))
                except: list_size = 30
                try: trakt_timeout = int(kodi.get_setting('trakt_timeout'))
                except: trakt_timeout = 20
                trakt_api = Trakt_API(token, kodi.get_setting('use_https') == 'true', list_size, trakt_timeout, kodi.get_setting('trakt_offline') == 'true')
                progress = trakt_api.get_show_progress(queries['trakt_id'], full=True)
                if 'next_episode' in progress and progress['next_episode']:
                    if progress['completed'] or kodi.get_setting('next_unwatched') == 'true':
                        next_episode = progress['next_episode']
                        date = utils2.make_day(utils2.make_air_date(next_episode['first_aired']))
                        if kodi.get_setting('next_time') != '0':
                            date_time = '%s@%s' % (date, utils2.make_time(utils.iso_2_utc(next_episode['first_aired']), 'next_time'))
                        else:
                            date_time = date
                        msg = '[[COLOR deeppink]%s[/COLOR]] - %sx%s' % (date_time, next_episode['season'], next_episode['number'])
                        if next_episode['title']: msg += ' - %s' % (next_episode['title'])
                        duration = int(kodi.get_setting('next_up_duration')) * 1000
                        kodi.notify(header=i18n('next_episode'), msg=msg, duration=duration)
            sf_begin = 0
    else:
        last_label = ''

errors = 0
while not xbmc.abortRequested:
    try:
        isPlaying = service.isPlaying()
        salts_utils.do_scheduled_task(MODES.UPDATE_SUBS, isPlaying)
        salts_utils.do_scheduled_task(MODES.PRUNE_CACHE, isPlaying)
        if service.tracked and service.isPlayingVideo():
            service._lastPos = service.getTime()

        disable_global_cx()
        check_cooldown()
        if kodi.get_setting('show_next_up') == 'true':
            show_next_up()
    except Exception as e:
        errors += 1
        if errors >= MAX_ERRORS:
            log_utils.log('Service: Error (%s) received..(%s/%s)...Ending Service...' % (e, errors, MAX_ERRORS), log_utils.LOGERROR, COMPONENT)
            break
        else:
            log_utils.log('Service: Error (%s) received..(%s/%s)...Continuing Service...' % (e, errors, MAX_ERRORS), log_utils.LOGERROR, COMPONENT)
    else:
        errors = 0

    kodi.sleep(500)
    
log_utils.log('Service: shutting down...', log_utils.LOGNOTICE, COMPONENT)
