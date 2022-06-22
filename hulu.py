import argparse
import base64
import configparser
import http.cookiejar
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import pathvalidate
import requests
import xmltodict
from unidecode import unidecode
import pyhulu
from pywidevine.cdm import deviceconfig
from pywidevine.decrypt.wvdecrypt import WvDecrypt

COOKIES_FILE = 'cookies.txt'

session = requests.Session()
jar = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
jar.load()
session.cookies = jar


def get_episodes(series_id, season_num):
    base_url = f'https://discover.hulu.com/content/v4/hubs/series/{series_id}/season/{season_num}'
    params = {
        'limit': 999,
        'schema': 9,
    }
    resp = session.get(url=base_url, params=params)
    parsed = resp.json()
    logger.debug(json.dumps(parsed, indent=2))

    episodes = []

    for episode in parsed['items']:
        if 'bundle' not in episode:
            logger.error('Unable to get content ID. Possible GeoIP error.')
            sys.exit(1)

        ep_num = int(episode['number'])

        episodes.insert(ep_num - 1, {
            'id': episode['bundle']['eab_id'],
            'title': episode['series_name'],
            'season_num': int(episode['season']),
            'episode_num': ep_num,
            'episode_name': episode['name'],
        })

    return episodes


def get_title(watch_id):
    base_url = 'https://discover.hulu.com/content/v3/entity/deeplink'
    params = {
        'schema': 12,
        'entity_id': watch_id,
        'referral_host': 'www.hulu.com'
    }
    resp = session.get(url=base_url, params=params)
    parsed = resp.json()
    logger.debug(json.dumps(parsed, indent=2))

    if 'bundle' not in parsed['entity']:
        logger.error('Unable to get content ID. Possible GeoIP error.')
        sys.exit(1)

    return {
        'id': parsed['entity']['bundle']['eab_id'],
        'title': parsed['entity']['name'],
        'year': int(parsed['entity']['premiere_date'].split('-')[0]),
    }


def get_pssh(tracks, track_type="video"):
    for track in tracks:
        if track_type in track.get('@mimeType'):
            for t in track.get('ContentProtection', {}):
                if t['@schemeIdUri'].lower() == 'urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed' and t.get('cenc:pssh'):
                    return t['cenc:pssh']


config = configparser.ConfigParser(interpolation=None)
config.sections()
config.read('hulu.cfg')

parser = argparse.ArgumentParser()
parser.add_argument(
    'url',
    help='URL or ID of title to download',
)
parser.add_argument(
    '-s',
    '--season',
    help='season(s) to download (for TV series)',
)
parser.add_argument(
    '-e',
    '--episode',
    help='episode(s) to download (for TV series) [default: all]',
)
parser.add_argument(
    '-q', '--quality',
    type=lambda x: [int(x.rstrip('p')) for x in x.split(',')],
    help='video quality to download',
)
parser.add_argument(
    '-2',
    '--force-2ch',
    action='store_true',
    help='force downloading 2.0 audio instead of 5.1',
)
parser.add_argument(
    '-al',
    '--audio-lang',
    help='audio language to download',
)
parser.add_argument(
    '-sl',
    '--subtitle-lang',
    type=lambda x: x.split(','),
    default='en',
    help='subtitle language(s) to download',
)
parser.add_argument(
    '-o',
    '--output',
    help='override output filename',
)
parser.add_argument(
    '-i',
    '--info',
    action='store_true',
    help='display information and exit',
)
parser.add_argument(
    '--debug',
    action='store_true',
    help='enable debug logging'
)
parser.add_argument(
    '--h264',
    help='Only get H264',
    action='store_true'
)
parser.add_argument(
    '--hdr',
    help='Get HDR/DV manifest',
    action='store_true'
)
parser.add_argument(
    '-l', "--license",
    help='Get keys',
    action='store_true'
)

args = parser.parse_args()

logger = logging.getLogger('hulu')

if args.debug:
    logging.basicConfig(level=logging.DEBUG,
                        format='%(message)s')
else:
    logging.basicConfig(level=logging.INFO,
                        format='%(message)s')

script_path = os.path.dirname(os.path.realpath(__file__))
binaries_dir = os.path.join(script_path, 'binaries')
os.environ['PATH'] = os.pathsep.join((binaries_dir, os.environ['PATH']))

proxy = None
if 'proxy' in config:
    proxy = config['proxy']['url']
    session.proxies = {'http': proxy, 'https': proxy}


def create_client(device, *args, **kwargs):
    (code, key) = config['devices'][device].split(':')
    return pyhulu.HuluClient(code, bytes.fromhex(key), *args, **kwargs)


audio_codecs = [{'type': 'AAC'}]
if not args.force_2ch:
    audio_codecs.append({'type': 'EC3'})

clients = {
    'chrome': create_client('chrome', jar, proxy=proxy, extra_playlist_params={
        'playback': {
            'audio': {
                'codecs': {
                    'values': audio_codecs,
                },
            },
        },
    })}

watch_id = None

UUID_RE = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'

match = re.fullmatch(UUID_RE, args.url)
if match:
    watch_id = match.group(1)
elif re.match(r'https?://(?:www\.)hulu\.com/(?:watch|movie|series)', args.url):
    match = re.search(UUID_RE, args.url)
    if match:
        watch_id = match.group()

if not watch_id:
    logger.error(f'{args.url!r} is not a valid Hulu watch URL or ID.')
    sys.exit(1)

if '/series/' in args.url and not args.season:
    logger.error('For series, please use the --season argument.')
    sys.exit(1)

titles = []
if args.season:
    if '-' in args.season:
        (start, end) = args.season.split('-')
        start = int(start)
        end = int(end)

        seasons = range(start, end + 1)
    elif ',' in args.season:
        seasons = [int(x) for x in args.season.split(',')]
    else:
        seasons = [int(args.season)]

    for s in seasons:
        eps = get_episodes(watch_id, s)

        if not eps:
            logger.error('No episodes found. Possible GeoIP error.')
            sys.exit(1)

        if args.episode:
            if '-' in args.episode:
                (start, end) = args.episode.split('-')
                start = int(start)
                end = int(end or len(eps))

                titles.extend(x for x in eps if start <= x['episode_num'] <= end)
            elif ',' in args.episode:
                selected_eps = [int(x) for x in args.episode.split(',')]

                titles.extend(x for x in eps if x['episode_num'] in selected_eps)
            else:
                try:
                    titles.append(next(x for x in eps if x['episode_num'] == int(args.episode)))
                except StopIteration:
                    logger.error('Requested episode not found')
                    sys.exit(1)

            if not titles:
                logger.error('No matching episodes found')
                sys.exit(1)
        else:
            titles.extend(eps)
else:
    titles.append(get_title(watch_id))

temp_folder = config['paths']['temp_folder']
output_folder = config['paths']['output_folder']
os.makedirs(temp_folder, exist_ok=True)
os.makedirs(output_folder, exist_ok=True)

for t in titles:
    data = {}
    tracks = {}

    for device in ('video', 'chrome'):
        try:
            if device == 'video':
                # Hard code device id to 210 and. use v6 playlist
                if args.h264:
                    hevc = False
                else:
                    hevc = True
                data[device] = clients['chrome'].load_playlist_six(t['id'], 210, hdr=args.hdr, hevc=hevc)
            else:
                data[device] = clients[device].load_playlist(t['id'])
            logger.debug(f'{device.title()} manifest:')
            logger.debug(json.dumps(data[device], indent=2))
        except ValueError:
            sys.exit(1)

        if 'block' in data[device]:
            logger.error(f'Error in {device.title()} manifest: {data[device]["block"]}')
            sys.exit(1)

        r = session.get(data[device]['stream_url'])
        r.raise_for_status()
        xml = xmltodict.parse(r.text, force_list={
            'Period', 'AdaptationSet', 'ContentProtection', 'Representation', 'S',
        })
        period = next(x for x in xml['MPD']['Period'] if not x['@id'].startswith('ad-'))
        tracks[device] = period['AdaptationSet']


    def get_bitrate(rep):
        return int(rep.get('hulu:ProfileBandwidth') or rep.get('@bandwidth'))


    video_tracks = next(x for x in tracks['video'] if x['@mimeType'] == 'video/mp4')
    video_tracks = sorted(video_tracks['Representation'], key=get_bitrate, reverse=True)

    audio_tracks = next(x for x in tracks['chrome'] if x['@mimeType'] == 'audio/mp4'
                        and ('Role' not in x or x['Role']['@value'] == 'main')
                        and ((not args.audio_lang) or x['@lang'] == args.audio_lang))

    if not audio_tracks:
        logger.error(f'Audio language {args.audio_lang!r} not available')
        sys.exit(1)

    audio_lang = audio_tracks['@lang']
    audio_tracks = sorted(audio_tracks['Representation'], key=get_bitrate, reverse=True)

    video_dl = []
    audio_track = audio_tracks[0]

    if args.quality:
        for q in args.quality:
            video_dl.append(next(x for x in video_tracks if int(x['@height']) == q))
    else:
        video_dl = [video_tracks[0]]

    for video_track in video_dl:

        if audio_track['@codecs'] == 'ec-3':
            audio = 'DDP5.1'
        else:
            audio = 'AAC2.0'

        if 'dvhe' in video_track['@codecs']:
            video = 'DV.H.265'
        elif 'hev' in video_track['@codecs']:
            video = 'H.265'
        else:
            video = 'H.264'

        if 'season_num' in t:
            base_filename = config['output_template']['series'].format(**{
                'title': pathvalidate.sanitize_filename(t['title']),
                'season_num': f'{t["season_num"]:02}',
                'episode_num': f'{t["episode_num"]:02}',
                'episode_name': pathvalidate.sanitize_filename(t['episode_name']),
                'quality': video_track['@height'],
                'audio': audio,
                'video': video,
            })
        else:
            base_filename = config['output_template']['movie'].format(**{
                'title': pathvalidate.sanitize_filename(t['title']),
                'year': t['year'],
                'quality': video_track['@height'],
                'audio': audio,
                'video': video,
            })

        if config['output_template']['no_space']:
            base_filename = base_filename.replace('&', '.and.')
            base_filename = re.sub(r'[]!"#$%\'()*+,:;<=>?@\\^_`{|}~[]', '', base_filename)
            base_filename = base_filename.replace(' ', '.')
            base_filename = re.sub(r'\.{2,}', '.', base_filename)
            base_filename = unidecode(base_filename)

        base_filename = pathvalidate.sanitize_filepath(base_filename)

        VIDEO_FILENAME_ENCRYPTED = f'{base_filename}_video_enc.mp4'
        VIDEO_FILENAME_DECRYPTED = f'{base_filename}_video_dec.mp4'
        VIDEO_FILENAME_FIXED = f'{base_filename}_video_fixed.mp4'
        AUDIO_FILENAME_ENCRYPTED = f'{base_filename}_audio_enc.mp4'
        AUDIO_FILENAME_DECRYPTED = f'{base_filename}_audio_dec.mp4'
        AUDIO_FILENAME_FIXED = f'{base_filename}_audio_fixed.mp4'
        SUBTITLE_FILENAME_VTT = f'{base_filename}_subtitles_{{lang}}.vtt'
        SUBTITLE_FILENAME_SRT = f'{base_filename}_subtitles_{{lang}}.srt'
        MUXED_FILENAME = args.output or f'{base_filename}.mkv'
        if not MUXED_FILENAME.endswith('.mkv'):
            MUXED_FILENAME += '.mkv'

        print()
        logger.info(f'Ripping: {base_filename}')

        video_url = video_track['BaseURL']
        audio_url = audio_track['BaseURL']
        subtitle_urls = []
        for sl in args.subtitle_lang:
            try:
                subtitle_urls.append((sl, data['video']['transcripts_urls']['webvtt'][sl]))
            except KeyError:
                logger.warning(f'No {sl!r} subtitle found')

        license_url = data['video']['wv_server']
        pssh = get_pssh(tracks['video'])

        if args.info:
            logger.info('Video: %s', dict(video_track))
            logger.info('Audio: %s', dict(audio_track))
            logger.info('Filename    : %s', base_filename)
            logger.info('Video URL   : %s', video_url)
            logger.info('Audio URL   : %s', audio_url)
            for (lang, url) in subtitle_urls:
                logger.info('Subtitle URL (%s): %s', lang, url)
            logger.info('License URL : %s', license_url)
            logger.info('PSSH        : %s', pssh)
            break

        license_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0',
        }

        logger.info('Requesting license')
        KEYS = []
        wvdecrypt = WvDecrypt(pssh, None, deviceconfig.device_galaxy_note_2)
        challenge = wvdecrypt.get_challenge()
        r = requests.post(license_url, data=challenge)
        r.raise_for_status()
        license_b64 = base64.b64encode(r.content)
        wvdecrypt.update_license(license_b64)
        wvdecrypt.start_process()
        (correct, keys) = wvdecrypt.start_process()
        KEYS += keys
        if not correct:
            logger.error('Unable to get keys')
            sys.exit(1)

        audio_pssh = get_pssh(tracks["video"], "audio")
        if audio_pssh:
            wvdecrypt = WvDecrypt(audio_pssh, None, deviceconfig.device_galaxy_note_2)
            challenge = wvdecrypt.get_challenge()
            r = requests.post(license_url, data=challenge)
            r.raise_for_status()
            license_b64 = base64.b64encode(r.content)
            wvdecrypt.update_license(license_b64)
            wvdecrypt.start_process()
            (correct, keys) = wvdecrypt.start_process()
            KEYS += keys
            if not correct:
                logger.error('Unable to get keys')
                sys.exit(1)
        keys_arg = [['--key', k] for k in KEYS]
        keys_arg = list(itertools.chain(*keys_arg))

        if args.license:
            os.makedirs("KEYS", exist_ok=True)
            with open(os.path.join("KEYS", os.path.basename(MUXED_FILENAME.replace(".mkv", ".txt"))), "w") as keyfile:
                for k in keys:
                    logger.info(f'Key: {k}')
                keyfile.writelines(keys)
                logger.info(f"Wrote keys to {MUXED_FILENAME.replace('.mkv', '.txt')}")

            continue

        logger.info('Downloading video')
        cmdline = [
            'aria2c', '--allow-overwrite=true', '--summary-interval=0', "--disable-ipv6", '--console-log-level=warn', video_url,
            '-d', temp_folder, '-o', VIDEO_FILENAME_ENCRYPTED,
        ]
        logger.debug(cmdline)
        subprocess.run(cmdline, check=True)

        logger.info('Downloading audio')
        cmdline = [
            'aria2c', '--allow-overwrite=true', '--summary-interval=0', "--disable-ipv6", '--console-log-level=warn', audio_url,
            '-d', temp_folder, '-o', AUDIO_FILENAME_ENCRYPTED,
        ]
        subprocess.run(cmdline, check=True)

        for (lang, url) in subtitle_urls:
            logger.info('Downloading %r subtitles', lang)
            cmdline = [
                'aria2c', '--allow-overwrite=true', '--summary-interval=0', "--disable-ipv6", '--console-log-level=warn', url,
                '-d', temp_folder, '-o', SUBTITLE_FILENAME_VTT.format(lang=lang),
            ]
            logger.debug(cmdline)
            subprocess.run(cmdline, check=True)

        logger.info('Decrypting video')
        cmdline = ['mp4decrypt', '--show-progress']
        cmdline += keys_arg
        cmdline += [
            os.path.join(temp_folder, VIDEO_FILENAME_ENCRYPTED),
            os.path.join(temp_folder, VIDEO_FILENAME_DECRYPTED),
        ]
        logger.debug(cmdline)
        subprocess.run(cmdline, check=True)

        logger.info('Decrypting audio')
        cmdline = ['mp4decrypt', '--show-progress']
        cmdline += keys_arg
        cmdline += [
            os.path.join(temp_folder, AUDIO_FILENAME_ENCRYPTED),
            os.path.join(temp_folder, AUDIO_FILENAME_DECRYPTED),
        ]
        logger.debug(cmdline)
        subprocess.run(cmdline, check=True)

        if "HDR" not in video_url:
            logger.info('Remuxing video')
            cmdline = [
                'ffmpeg', "-hide_banner", '-loglevel', 'panic', '-i',
                os.path.join(temp_folder, VIDEO_FILENAME_DECRYPTED),
                '-c', 'copy',
                os.path.join(temp_folder, VIDEO_FILENAME_FIXED)
            ]
            logger.debug(cmdline)
            subprocess.run(cmdline, check=True)
        else:
            os.rename(os.path.join(temp_folder, VIDEO_FILENAME_DECRYPTED), os.path.join(temp_folder, VIDEO_FILENAME_FIXED))

        logger.info('Remuxing audio')
        cmdline = [
            'ffmpeg', '-loglevel', 'panic', '-hide_banner', '-i',
            os.path.join(temp_folder, AUDIO_FILENAME_DECRYPTED),
            '-c', 'copy',
            os.path.join(temp_folder, AUDIO_FILENAME_FIXED)
        ]
        logger.debug(cmdline)
        subprocess.run(cmdline, check=True)

        for (lang, _) in subtitle_urls:
            logger.info(f'Converting {lang!r} subtitles')
            cmdline = [
                'ffmpeg', '-loglevel', 'panic', '-i',
                os.path.join(temp_folder, SUBTITLE_FILENAME_VTT.format(lang=lang)),
                os.path.join(temp_folder, SUBTITLE_FILENAME_SRT.format(lang=lang)),
            ]
            logger.debug(cmdline)
            subprocess.run(cmdline, check=True)

        logger.info('Muxing')
        cmdline = [
            'mkvmerge', '-q', '--no-global-tags', '-o',
            os.path.join(output_folder, MUXED_FILENAME),
            os.path.join(temp_folder, VIDEO_FILENAME_FIXED),
            '--language', f'0:{audio_lang}',
            os.path.join(temp_folder, AUDIO_FILENAME_FIXED),
        ]
        for (lang, _) in subtitle_urls:
            cmdline.extend([
                '--language', f'0:{lang}',
                '--default-track', '0:no',
                os.path.join(temp_folder, SUBTITLE_FILENAME_SRT.format(lang=lang)),
            ])
        logger.debug(cmdline)
        subprocess.run(cmdline, check=True)

logger.info('Deleting temporary files')
for (dirpath, dirnames, filenames) in os.walk(temp_folder):
    for f in filenames:
        os.remove(os.path.join(dirpath, f))

    if dirpath != temp_folder:
        os.rmdir(dirpath)
