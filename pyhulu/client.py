"""
Client module

Main module for Hulu API requests
"""

import base64
import binascii
import hashlib
import json
import logging
import random
import requests

from Cryptodome.Cipher import AES
from Cryptodome.Util import Padding

from pyhulu.device import Device


class HuluClient(object):
    """
    HuluClient class

    Main class for Hulu API requests

    __init__:

    @param device_code: Three-digit string or integer (doesn't matter)
                        denoting the device you will make requests as

    @param device_key: 16-byte AES key that corresponds to the device
                       code you're using. This is used to decrypt the
                       device config response.

    @param cookies: Either a cookie jar object or a dict of cookie
                    key / value pairs. This is passed to the requests library,
                    so whatever it takes will work. Examples here:
                    http://docs.python-requests.org/en/master/user/quickstart/#cookies

    @param proxy: Proxy URL to use for requests to the Hulu API (optional)

    @param extra_playlist_params: A dict of extra playlist parameters (optional)

    @return: HuluClient object
    """

    def __init__(self, device_code, device_key, cookies, proxy=None, extra_playlist_params={}):
        self.logger = logging.getLogger(__name__)
        self.device = Device(device_code, device_key)
        self.extra_playlist_params = extra_playlist_params

        self.session = requests.Session()
        self.session.cookies = cookies
        self.session.proxies = {'http': proxy, 'https': proxy}

        self.session_key, self.server_key = self.get_session_key()

    def load_playlist(self, video_id):
        """
        load_playlist()

        Method to get a playlist containing the MPD
        and license URL for the provided video ID and return it

        @param video_id: String of the video ID to get a playlist for

        @return: Dict of decrypted playlist response
        """

        base_url = 'https://play.hulu.com/v4/playlist'
        params = {
            'device_identifier': hashlib.md5().hexdigest().upper(),
            'deejay_device_id': int(self.device.device_code),
            'version': 1,
            'content_eab_id': video_id,
            'rv': random.randrange(1E5, 1E6),
            'kv': self.server_key,
        }
        params.update(self.extra_playlist_params)

        resp = self.session.post(url=base_url, json=params)
        ciphertext = self.__get_ciphertext(resp.text, params)

        return self.decrypt_response(self.session_key, ciphertext)

    def load_playlist_six(self, video_id, device_id, hdr, hevc=True):
        base_url = 'https://play.hulu.com/v6/playlist'

        # video_id = "EAB::2695972c-f19a-4044-b7d5-c9af55b478e4::61531101::93091445"
        hevc_params = {
            "device_identifier": hashlib.md5().hexdigest().upper(),
            "deejay_device_id": device_id,
            "version": 1,
            "all_cdn": True,
            "content_eab_id": video_id,
            "region": "US",
            "xlink_support": False,
            "device_ad_id": "5DFEB7AD-3651-8C6A-8302-56EC694FD9E8",
            "limit_ad_tracking": False,
            "ignore_kids_block": False,
            "guid": "0BFDBD0D05D1DF844899A7D608B95BBE",
            'rv': random.randrange(1E5, 1E6),
            'kv': self.server_key,
            "cp_session_id": "4408CF3E-D697-B2EA-A70A-4769B8D072F1",
            "unencrypted": True,
            "network_mode": "wifi",
            "interface_version": "1.3.0-alpha.1",
            "play_intent": "resume",
            "playback": {
                "version": 2,
                "video": {
                    "codecs": {
                        "selection_mode": "ALL",
                        "values": [{
                            'type': 'H265',
                            'profile': 'MAIN_10',
                            'width': 3840,
                            'height': 2160,
                            'framerate': 60,
                            'level': '5.1',
                            'tier': 'MAIN'
                        }]
                    }
                },
                "audio": {
                    "codecs": {
                        "values": [
                            {"type": "EC3"},
                            {"type": "AAC"}
                        ],
                        "selection_mode": "ALL"
                    }
                },
                "drm": {
                    "values": [{
                        "type": "WIDEVINE",
                        "version": "MODULAR",
                        "security_level": "L3"
                    }, {
                        "type": "PLAYREADY",
                        "version": "V2",
                        "security_level": "SL2000"
                    }],
                    "selection_mode": "ALL"
                },
                "manifest": {
                    "type": "DASH",
                    "https": True,
                    "multiple_cdns": True,
                    "patch_updates": True,
                    "hulu_types": True,
                    "live_dai": True,
                    "secondary_audio": True,
                    "live_fragment_delay": 3
                },
                "trusted_execution_environment": True,
                "segments": {
                    "values": [{
                        "type": "FMP4",
                        "encryption": {
                            "mode": "CENC",
                            "type": "CENC"
                        },
                        "https": True
                    }],
                    "selection_mode": "ONE"
                }
            }
        }
        avc_params = {
            "device_identifier": hashlib.md5().hexdigest().upper(),
            "deejay_device_id": device_id,
            "version": 1,
            "all_cdn": True,
            "content_eab_id": video_id,
            "region": "US",
            "xlink_support": False,
            "device_ad_id": "5DFEB7AD-3651-8C6A-8302-56EC694FD9E8",
            "limit_ad_tracking": False,
            "ignore_kids_block": False,
            "guid": "0BFDBD0D05D1DF844899A7D608B95BBE",
            'rv': random.randrange(1E5, 1E6),
            'kv': self.server_key,
            "cp_session_id": "4408CF3E-D697-B2EA-A70A-4769B8D072F1",
            "unencrypted": True,
            "network_mode": "wifi",
            "interface_version": "1.3.0-alpha.1",
            "play_intent": "resume",
            "playback": {
                "version": 2,
                "video": {
                    "codecs": {
                        "selection_mode": "ALL",
                        "values": [{
                            "width": 1920,
                            "level": "4.1",
                            "height": 1080,
                            "profile": "HIGH",
                            "type": "H264"
                        }]
                    }
                },
                "audio": {
                    "codecs": {
                        "values": [
                            {"type": "EC3"},
                            {"type": "AAC"}
                        ],
                        "selection_mode": "ALL"
                    }
                },
                "drm": {
                    "values": [{
                        "type": "WIDEVINE",
                        "version": "MODULAR",
                        "security_level": "L3"
                    }, {
                        "type": "PLAYREADY",
                        "version": "V2",
                        "security_level": "SL2000"
                    }],
                    "selection_mode": "ALL"
                },
                "manifest": {
                    "type": "DASH",
                    "https": True,
                    "multiple_cdns": True,
                    "patch_updates": True,
                    "hulu_types": True,
                    "live_dai": True,
                    "secondary_audio": True,
                    "live_fragment_delay": 3
                },
                "trusted_execution_environment": True,
                "segments": {
                    "values": [{
                        "type": "FMP4",
                        "encryption": {
                            "mode": "CENC",
                            "type": "CENC"
                        },
                        "https": True
                    }],
                    "selection_mode": "ONE"
                }
            }
        }
        if hevc:
            params = hevc_params
        else:
            params = avc_params
        if hdr:
            params["playback"]["video"]["dynamic_range"] = "DOLBY_VISION"
            params["playback"]["drm"]["multi_key"] = True
        resp = self.session.post(url=base_url, json=params)
        resp.raise_for_status()
        return json.loads(resp.text)

    def decrypt_response(self, key, ciphertext):
        """
        decrypt_response()

        Method to decrypt an encrypted response with provided key

        @param key: Key in bytes
        @param ciphertext: Ciphertext to decrypt in bytes

        @return: Decrypted response as a dict
        """

        aes_cbc_ctx = AES.new(key, AES.MODE_CBC, iv=b'\0' * 16)

        try:
            plaintext = Padding.unpad(aes_cbc_ctx.decrypt(ciphertext), 16)
        except ValueError:
            self.logger.error('Error decrypting response')
            self.logger.error('Ciphertext:')
            self.logger.error(base64.b64encode(ciphertext).decode('utf8'))
            self.logger.error(
                'Tried decrypting with key %s',
                base64.b64encode(key).decode('utf8')
            )

            raise ValueError('Error decrypting response')

        return json.loads(plaintext.decode('utf8'))

    def get_session_key(self):
        """
        get_session_key()

        Method to do a Hulu config request and calculate
        the session key against device key and current server key

        @return: Session key in bytes
        """

        version = '1'
        random_value = random.randrange(1E5, 1E6)

        base = '{device_key},{device},{version},{random_value}'.format(
            device_key=binascii.hexlify(self.device.device_key).decode('utf8'),
            device=self.device.device_code,
            version=version,
            random_value=random_value
        ).encode('utf8')

        nonce = hashlib.md5(base).hexdigest()

        url = 'https://play.hulu.com/config'
        payload = {
            'rv': random_value,
            'mozart_version': '1',
            'region': 'US',
            'version': version,
            'device': self.device.device_code,
            'encrypted_nonce': nonce
        }

        resp = self.session.post(url=url, data=payload)
        ciphertext = self.__get_ciphertext(resp.text, payload)

        config_dict = self.decrypt_response(
            self.device.device_key,
            ciphertext
        )

        derived_key_array = bytearray()
        for device_byte, server_byte in zip(self.device.device_key,
                                            bytes.fromhex(config_dict['key'])):
            derived_key_array.append(device_byte ^ server_byte)

        return bytes(derived_key_array), config_dict['key_id']

    def __get_ciphertext(self, text, request):
        try:
            ciphertext = bytes.fromhex(text)
        except ValueError:
            self.logger.error('Error decoding response hex')
            self.logger.error('Request:')
            for line in json.dumps(request, indent=4).splitlines():
                self.logger.error(line)

            self.logger.error('Response:')
            for line in text.splitlines():
                self.logger.error(line)

            raise ValueError('Error decoding response hex')

        return ciphertext

    def __repr__(self):
        return '<HuluClient session_key=%s>' % base64.b64encode(
            self.session_key
        ).decode('utf8')
