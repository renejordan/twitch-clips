"""Read-only Buffer connection check. No publishing, cookies or state changes."""
import json
import os
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = 'https://api.buffer.com'
ORGANIZATION_ID = '6ad16bade773dee7cee97bfc'
CHANNEL_ID = '6ad16c0c778b240e2f21aca5'
MAX_RESPONSE_BYTES = 1024 * 1024
QUERY = '''query TikTok14ConnectionReadOnly {
  channel(input:{id:"6ad16c0c778b240e2f21aca5"}) {
    id name service organizationId externalLink scopes
    isDisconnected isLocked isQueuePaused timezone
  }
  account { organizations { id limits { scheduledPosts } } }
  dailyPostingLimits(input:{channelIds:["6ad16c0c778b240e2f21aca5"]}) {
    channelId isAtLimit limit scheduled sent
  }
}'''


class CheckFailed(Exception):
    """Internal failures carry only fixed, non-sensitive reason codes."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token, even if the service returns a redirect.
        return None


def fetch(key):
    request = Request(ENDPOINT, data=json.dumps({'query': QUERY,
        'operationName': 'TikTok14ConnectionReadOnly'}).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        method='POST')
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CheckFailed('invalid_response')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise CheckFailed('invalid_response') from None


def validate(body):
    try:
        if not isinstance(body, dict) or body.get('errors'):
            raise CheckFailed('api_response_rejected')
        data = body['data']
        channel = data['channel']
        expected = {'id': CHANNEL_ID, 'organizationId': ORGANIZATION_ID,
                    'name': 'ufo3103', 'service': 'tiktok',
                    'externalLink': 'https://tiktok.com/@ufo3103',
                    'timezone': 'Europe/Berlin'}
        if any(channel.get(field) != value for field, value in expected.items()):
            raise CheckFailed('channel_identity_mismatch')
        if any(channel.get(flag) is not False for flag in
               ('isDisconnected', 'isLocked', 'isQueuePaused')):
            raise CheckFailed('channel_not_ready')
        if not isinstance(channel.get('scopes'), list) or 'video.publish' not in channel['scopes']:
            raise CheckFailed('publishing_scope_missing')
        organizations = [org for org in data['account']['organizations']
                         if org['id'] == ORGANIZATION_ID]
        limits = data['dailyPostingLimits']
        if len(organizations) != 1 or len(limits) != 1 or limits[0]['channelId'] != CHANNEL_ID:
            raise CheckFailed('quota_identity_mismatch')
        daily = limits[0]
        if daily.get('isAtLimit') is not False:
            raise CheckFailed('buffer_daily_limit_reached')
        summary = {'queue_capacity': organizations[0]['limits']['scheduledPosts'],
                   'buffer_daily_limit': daily['limit'],
                   'buffer_scheduled': daily['scheduled'], 'buffer_sent': daily['sent']}
        if any(type(value) is not int or value < 0 or value > 1000000
               for value in summary.values()):
            raise CheckFailed('invalid_quota')
        if summary['queue_capacity'] == 0 or summary['buffer_daily_limit'] == 0:
            raise CheckFailed('invalid_quota')
        if summary['buffer_scheduled'] + summary['buffer_sent'] >= summary['buffer_daily_limit']:
            raise CheckFailed('buffer_daily_limit_reached')
        return summary
    except (KeyError, TypeError, AttributeError):
        raise CheckFailed('invalid_response') from None


def main():
    key = os.environ.pop('BUFFER_API_KEY', '').strip()
    if not key:
        print('STOP: BUFFER_API_KEY is missing. No request was sent.')
        return 1
    try:
        summary = validate(fetch(key))
    except HTTPError as error:
        # Never print the exception, headers, response body or traceback.
        print('STOP: Buffer HTTP request failed (status %d).' % error.code)
        return 1
    except CheckFailed:
        print('STOP: Buffer identity, connection, permissions or quotas could not be verified.')
        return 1
    except Exception:
        print('STOP: Buffer connection check failed. No server details were logged.')
        return 1
    print('OK: Buffer workspace My organization; TikTok @ufo3103; connection and video.publish verified.')
    print('Buffer quota snapshot: ' + json.dumps(summary, sort_keys=True))
    print('Read-only check only: no post, draft, schedule or upload was created.')
    print('These Buffer counters do not verify account-wide TikTok limits or successful publication.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
