# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re
import os
import time

from marionette import BrowserMobProxyTestCaseMixin, MarionetteTestCase
from marionette_driver import Wait
from marionette_driver.errors import TimeoutException
from marionette.marionette_test import SkipTest

from firefox_puppeteer.testcases import BaseFirefoxTestCase
from external_media_tests.utils import (timestamp_now, verbose_until)
from external_media_tests.media_utils.video_puppeteer import (playback_done, playback_started,
                                         VideoException, VideoPuppeteer as VP)


class MediaTestCase(BaseFirefoxTestCase, MarionetteTestCase):

    """
    Necessary methods for MSE playback

    :param video_urls: Urls you are going to play as part of the tests.
    """

    def __init__(self, *args, **kwargs):
        self.video_urls = kwargs.pop('video_urls', False)
        super(MediaTestCase, self).__init__(*args, **kwargs)

    def save_screenshot(self):
        """
        Make a screenshot of the window that is currently playing the video
        element.
        """
        screenshot_dir = os.path.join(self.marionette.instance.workspace or '',
                                      'screenshots')
        filename = ''.join([self.id().replace(' ', '-'),
                            '_',
                            str(timestamp_now()),
                            '.png'])
        path = os.path.join(screenshot_dir, filename)
        if not os.path.exists(screenshot_dir):
            os.makedirs(screenshot_dir)
        with self.marionette.using_context('content'):
            img_data = self.marionette.screenshot()
        with open(path, 'wb') as f:
            f.write(img_data.decode('base64'))
        self.marionette.log('Screenshot saved in %s' % os.path.abspath(path))

    def log_video_debug_lines(self):
        """
        Log the debugging information that Firefox provides for video elements.
        """
        with self.marionette.using_context('chrome'):
            debug_lines = self.marionette.execute_script(VP._debug_script)
            if debug_lines:
                self.marionette.log('\n'.join(debug_lines))

    def run_playback(self, video):
        """
        Play the video all of the way through, or for the requested duration,
        whichever comes first. Raises if the video stalls for too long.

        :param video: VideoPuppeteer instance to play.
        """
        with self.marionette.using_context('content'):
            self.logger.info(video.test_url)
            try:
                verbose_until(Wait(video, interval=video.interval,
                                   timeout=video.expected_duration * 1.3 +
                                   video.stall_wait_time),
                              video, playback_done)
            except VideoException as e:
                raise self.failureException(e)

    def check_playback_starts(self, video):
        """
        Check to see if a given video will start. Raises if the video does not
        start.

        :param video: VideoPuppeteer instance to play.
        """
        with self.marionette.using_context('content'):
            self.logger.info(video.test_url)
            try:
                verbose_until(Wait(video, timeout=video.timeout),
                              video, playback_started)
            except TimeoutException as e:
                raise self.failureException(e)

    def skipTest(self, reason):
        """
        Skip this test.

        Skip with marionette.marionette_test import SkipTest so that it
        gets recognized a skip in marionette.marionette_test.CommonTestCase.run
        """
        raise SkipTest(reason)


class NetworkBandwidthTestCase(MediaTestCase):
    """
    Test MSE playback while network bandwidth is limited. Uses browsermobproxy
    (https://bmp.lightbody.net/). Please see
    https://developer.mozilla.org/en-US/docs/Mozilla/QA/external-media-tests
    for more information on setting up browsermob_proxy.
    """

    def __init__(self, *args, **kwargs):
        super(NetworkBandwidthTestCase, self).__init__(*args, **kwargs)
        BrowserMobProxyTestCaseMixin.__init__(self, *args, **kwargs)
        self.proxy = None

    def setUp(self):
        super(NetworkBandwidthTestCase, self).setUp()
        BrowserMobProxyTestCaseMixin.setUp(self)
        self.proxy = self.create_browsermob_proxy()

    def tearDown(self):
        super(NetworkBandwidthTestCase, self).tearDown()
        BrowserMobProxyTestCaseMixin.tearDown(self)
        self.proxy = None

    def run_videos(self, timeout=60):
        """
        Run each of the videos in the video list. Raises if something goes
        wrong in playback.
        """
        with self.marionette.using_context('content'):
            for url in self.video_urls:
                video = VP(self.marionette, url, stall_wait_time=60,
                           set_duration=60, timeout=timeout)
                self.run_playback(video)


class VideoPlaybackTestsMixin(object):

    """
    Test MSE playback in HTML5 video element.

    These tests should pass on any site where a single video element plays
    upon loading and is uninterrupted (by ads, for example).

    This tests both starting videos and performing partial playback at one
    minute each, and is the test that should be run frequently in automation.
    """

    def test_playback_starts(self):
        """
        Test to make sure that playback of the video element starts for each
        video.
        """
        with self.marionette.using_context('content'):
            for url in self.video_urls:
                try:
                    video = VP(self.marionette, url, timeout=60)
                    # Second playback_started check in case video._start_time
                    # is not 0
                    self.check_playback_starts(video)
                    video.pause()
                    src = video.video_src
                    if not src.startswith('mediasource'):
                        self.marionette.log('video is not '
                                            'mediasource: %s' % src,
                                            level='WARNING')
                except TimeoutException as e:
                    raise self.failureException(e)

    def test_video_playback_partial(self):
        """
        Test to make sure that playback of 60 seconds works for each video.
        """
        with self.marionette.using_context('content'):
            for url in self.video_urls:
                video = VP(self.marionette, url,
                           stall_wait_time=10,
                           set_duration=60)
                self.run_playback(video)


class NetworkBandwidthTestsMixin(object):

    """
        Test video urls with various bandwidth settings.
    """

    def test_playback_limiting_bandwidth_250(self):
        self.proxy.limits({'downstream_kbps': 250})
        self.run_videos(timeout=120)

    def test_playback_limiting_bandwidth_500(self):
        self.proxy.limits({'downstream_kbps': 500})
        self.run_videos(timeout=120)

    def test_playback_limiting_bandwidth_1000(self):
        self.proxy.limits({'downstream_kbps': 1000})
        self.run_videos(timeout=120)


reset_adobe_gmp_script = """
navigator.requestMediaKeySystemAccess('com.adobe.primetime',
[{initDataTypes: ['cenc']}]).then(
    function(access) {
        marionetteScriptFinished('success');
    },
    function(ex) {
        marionetteScriptFinished(ex);
    }
);
"""


class EMESetupMixin(object):

    """
    An object that needs to use the Adobe GMP system must inherit from this
    class, and then call check_eme_system() to insure that everything is
    setup correctly.
    """

    version_needs_reset = True

    def check_eme_system(self):
        """
        Download the most current version of the Adobe GMP Plugin. Verify
        that all MSE and EME prefs are set correctly. Raises if things
        are not OK.
        """
        self.set_eme_prefs()
        self.reset_GMP_version()
        assert(self.check_eme_prefs())

    def set_eme_prefs(self):
        with self.marionette.using_context('chrome'):
            # https://bugzilla.mozilla.org/show_bug.cgi?id=1187471#c28
            # 2015-09-28 cpearce says this is no longer necessary, but in case
            # we are working with older firefoxes...
            self.prefs.set_pref('media.gmp.trial-create.enabled', False)

    def reset_GMP_version(self):
        if EMESetupMixin.version_needs_reset:
            with self.marionette.using_context('chrome'):
                if self.prefs.get_pref('media.gmp-eme-adobe.version'):
                    self.prefs.reset_pref('media.gmp-eme-adobe.version')
            with self.marionette.using_context('content'):
                result = self.marionette.execute_async_script(
                    reset_adobe_gmp_script,
                    script_timeout=60000)
                if not result == 'success':
                    raise VideoException(
                        'ERROR: Resetting Adobe GMP failed % s' % result)

            EMESetupMixin.version_needs_reset = False

    def check_and_log_boolean_pref(self, pref_name, expected_value):
        with self.marionette.using_context('chrome'):
            pref_value = self.prefs.get_pref(pref_name)

            if pref_value is None:
                self.logger.info('Pref %s has no value.' % pref_name)
                return False
            else:
                self.logger.info('Pref %s = %s' % (pref_name, pref_value))
                if pref_value != expected_value:
                    self.logger.info('Pref %s has unexpected value.'
                                     % pref_name)
                    return False

        return True

    def check_and_log_integer_pref(self, pref_name, minimum_value=0):
        with self.marionette.using_context('chrome'):
            pref_value = self.prefs.get_pref(pref_name)

            if pref_value is None:
                self.logger.info('Pref %s has no value.' % pref_name)
                return False
            else:
                self.logger.info('Pref %s = %s' % (pref_name, pref_value))

                match = re.search('^\d+$', pref_value)
                if not match:
                    self.logger.info('Pref %s is not an integer' % pref_name)
                    return False

            return pref_value >= minimum_value

    def check_eme_prefs(self):
        with self.marionette.using_context('chrome'):
            prefs_ok = self.check_and_log_boolean_pref(
                'media.mediasource.enabled', True)
            prefs_ok = self.check_and_log_boolean_pref(
                'media.eme.enabled', True) and prefs_ok
            prefs_ok = self.check_and_log_boolean_pref(
                'media.mediasource.mp4.enabled', True) and prefs_ok
            prefs_ok = self.check_and_log_boolean_pref(
                'media.gmp-eme-adobe.enabled', True) and prefs_ok
            prefs_ok = self.check_and_log_integer_pref(
                'media.gmp-eme-adobe.version', 1) and prefs_ok

        return prefs_ok



