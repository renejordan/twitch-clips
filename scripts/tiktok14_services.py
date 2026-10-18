"""Small service boundaries for the cloud worker. No browser cookies or retries."""
import base64
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BUFFER_URL = 'https://api.buffer.com'
GITHUB_URL = 'https://api.github.com/repos/renejordan/twitch-clips'
CHANNEL_ID = '6ad16c0c778b240e2f21aca5'
ORGANIZATION_ID = '6ad16bade773dee7cee97bfc'
STATE_BRANCH = 'tiktok14-state'
MAX_BYTES = 2 * 1024 * 1024


class ServiceError(Exception):
    """Only fixed internal reason codes belong in this exception, never bodies."""


class QualityRejected(ServiceError):
    """Real content evidence failed; exclude this candidate, not the service."""


class ProductionInterrupted(BaseException):
    """Stop the legacy per-candidate loop on a production service failure."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, token=None, method='GET', payload=None):
    parsed = urlsplit(url)
    github = url.startswith(GITHUB_URL + '/')
    buffer = url == BUFFER_URL
    public_tiktok = (parsed.scheme == 'https' and parsed.netloc == 'www.tiktok.com'
                     and parsed.path == '/oembed')
    if not (github or buffer or public_tiktok) or (token and public_tiktok):
        raise ServiceError('unapproved_endpoint')
    headers = {'User-Agent':'TikTok14/1.0', 'Accept':'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if github:
        headers['X-GitHub-Api-Version'] = '2026-03-10'
    raw = None
    if payload is not None:
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=raw, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            if getattr(response,'status',200)==204:
                return {}
            body = response.read(MAX_BYTES+1)
    except HTTPError as error:
        service = 'github' if github else 'buffer' if buffer else 'tiktok'
        raise ServiceError(service + '_http_' + str(error.code)) from None
    except Exception:
        raise ServiceError('transport_error') from None
    if len(body) > MAX_BYTES:
        raise ServiceError('response_too_large')
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise ServiceError('invalid_json') from None
    if not isinstance(data, dict):
        raise ServiceError('invalid_response_shape')
    return data


def canonical_video(url):
    if not isinstance(url, str) or not re.fullmatch(
            r'https://(?:www\.)?tiktok\.com/@ufo3103/video/[0-9]{10,30}', url):
        raise ServiceError('unexpected_tiktok_url')
    return 'https://www.tiktok.com/@ufo3103/video/' + url.rsplit('/', 1)[1]


def verify_public(url):
    canonical = canonical_video(url)
    video_id = canonical.rsplit('/', 1)[1]
    body = request_json('https://www.tiktok.com/oembed?' + urlencode({'url':canonical}))
    return (body.get('provider_name') == 'TikTok' and body.get('type') == 'video'
            and body.get('author_url') == 'https://www.tiktok.com/@ufo3103'
            and bool(re.search(r'data-video-id=[\"\x27]' + video_id + r'[\"\x27]',
                               str(body.get('html', '')))))


POST_FIELDS = '''id status text channelId sentAt dueAt createdAt externalLink
  assets { source ... on VideoAsset { video { title } } }'''
OVERVIEW = '''query TikTok14WorkerOverview($since:DateTime!, $until:DateTime!) {
  channel(input:{id:"6ad16c0c778b240e2f21aca5"}) {
    id name service organizationId externalLink scopes
    isDisconnected isLocked isQueuePaused timezone
  }
  account { organizations { id limits { scheduledPosts } } }
  dailyPostingLimits(input:{channelIds:["6ad16c0c778b240e2f21aca5"]}) {
    channelId isAtLimit limit scheduled sent
  }
  recent:posts(first:100,input:{organizationId:"6ad16bade773dee7cee97bfc",
    filter:{channelIds:["6ad16c0c778b240e2f21aca5"],createdAt:{start:$since},
            status:[sent,scheduled,sending,error]}}) {
    edges { node { FIELDS } } pageInfo { hasNextPage }
  }
  due:posts(first:100,input:{organizationId:"6ad16bade773dee7cee97bfc",
    filter:{channelIds:["6ad16c0c778b240e2f21aca5"],dueAt:{start:$since,end:$until},
            status:[sent,scheduled,sending,error]}}) {
    edges { node { FIELDS } } pageInfo { hasNextPage }
  }
  pending:posts(first:100,input:{organizationId:"6ad16bade773dee7cee97bfc",
    filter:{channelIds:["6ad16c0c778b240e2f21aca5"],status:[scheduled,sending]}}) {
    edges { node { FIELDS } } pageInfo { hasNextPage }
  }
}'''.replace('FIELDS', POST_FIELDS)


class BufferGateway:
    def __init__(self, key):
        if not key:
            raise ServiceError('buffer_credential_missing')
        self._key = key

    def graphql(self, query, variables=None):
        body = request_json(BUFFER_URL, self._key, 'POST',
                            {'query':query,'variables':variables or {}})
        if body.get('errors') or not isinstance(body.get('data'), dict):
            raise ServiceError('buffer_graphql_error')
        return body['data']

    def overview(self, since, until):
        return self.graphql(OVERVIEW, {'since':since,'until':until})

    def post(self, post_id):
        if not re.fullmatch('[a-f0-9]{24}', post_id):
            raise ServiceError('invalid_post_id')
        data = self.graphql('query Read($id:PostId!){post(input:{id:$id}){'
                            + POST_FIELDS + '}}', {'id':post_id})
        if not isinstance(data.get('post'), dict):
            raise ServiceError('buffer_post_missing')
        return data['post']

    def create_post(self, video_url, caption, asset_title):
        data = self.graphql('''mutation Send($input:CreatePostInput!) {
          createPost(input:$input) { __typename ... on PostActionSuccess {
            post { id status externalLink sentAt }
          } }
        }''', {'input':{'channelId':CHANNEL_ID,'text':caption,
            'mode':'shareNow','schedulingType':'automatic','saveToDraft':False,
            'metadata':{'tiktok':{'isAiGenerated':False}},
            'assets':[{'video':{'url':video_url,'metadata':{
                'title':asset_title,'thumbnailOffset':0}}}]}})
        result = data.get('createPost')
        if not isinstance(result, dict) or result.get('__typename') != 'PostActionSuccess':
            raise ServiceError('buffer_create_rejected')
        post = result.get('post')
        if not isinstance(post, dict) or not re.fullmatch('[a-f0-9]{24}', str(post.get('id',''))):
            raise ServiceError('buffer_create_unresolved')
        return post


class GitHubAPI:
    def __init__(self, token):
        if not token:
            raise ServiceError('github_credential_missing')
        self._token = token

    def call(self, method, path, body=None):
        if not path.startswith('/') or path.startswith('//') or '..' in path or '\\' in path:
            raise ServiceError('invalid_github_path')
        return request_json(GITHUB_URL+path, self._token, method, body)


class GitHubState:
    def __init__(self, github):
        self.github = github

    @staticmethod
    def validate(data):
        if (not isinstance(data, dict) or type(data.get('version')) is not int
                or data['version'] != 1 or not isinstance(data.get('attempts'),list)
                or not isinstance(data.get('queue'),list)):
            raise ServiceError('invalid_state')
        return data

    def initialize(self, data):
        self.validate(data)
        # No base_tree and no parents: this branch contains only state.json.
        # Copying main would include tiktok.yml and trigger its push production.
        tree = self.github.call('POST','/git/trees',{'tree':[{
            'path':'state.json','mode':'100644','type':'blob',
            'content':json.dumps(data, ensure_ascii=False, indent=2)}]})
        commit = self.github.call('POST','/git/commits',{
            'message':'TikTok14: initialize isolated state', 'tree':tree['sha'],'parents':[]})
        self.github.call('POST','/git/refs',{
            'ref':'refs/heads/'+STATE_BRANCH,'sha':commit['sha']})

    def load(self):
        body = self.github.call('GET','/contents/state.json?ref='+STATE_BRANCH)
        try:
            if body['encoding'] != 'base64' or not isinstance(body['sha'],str):
                raise ServiceError('invalid_state_encoding')
            data = json.loads(base64.b64decode(body['content']))
            return self.validate(data), body['sha']
        except (KeyError, ValueError, TypeError):
            raise ServiceError('invalid_state_response') from None

    def save(self, data, previous_sha):
        self.validate(data)
        if not previous_sha:
            raise ServiceError('missing_state_version')
        encoded = base64.b64encode(json.dumps(data,ensure_ascii=False,indent=2).encode()).decode()
        if len(encoded) > 900000:
            raise ServiceError('state_compaction_required')
        response = self.github.call('PUT','/contents/state.json',{
            'branch':STATE_BRANCH,'message':'TikTok14: persist worker state',
            'sha':previous_sha,'content':encoded})
        try:
            return response['content']['sha']
        except (KeyError, TypeError):
            raise ServiceError('unconfirmed_state_write') from None
