import base64
import os

from django.conf import settings
import json
import requests

GITHUB_TIMEOUT = getattr(settings, 'GITHUB_TIMEOUT', 10)

MINIATURE_SIZE = getattr(settings, 'MINIATURE_SIZE', (200, 0))
if MINIATURE_SIZE[0] == MINIATURE_SIZE[1] == 0:
    raise ValueError('django.conf.settings.MINIATURE_SIZE cannot be (0, 0).')

def get_repoconf(reponame):
    # Raises Exceptions if app is misconfigured, which is desirable. We don't 
    # want to serve requests while being misconfigured.
    conf = settings.GITHUB_UPLOADER_REPOS[reponame]
    conf[reponame] # This is to trigger exception if misconfigured
    conf.setdefault('description', '')
    conf.setdefault('hidden', False)
    conf.setdefault('scope', getattr(settings, 'GITHUB_UPLOADER_PATH', 'public_repo'))
    conf.setdefault('branch', 'master')
    path = conf.setdefault('path', getattr(settings, 'GITHUB_UPLOADER_PATH', 'media'))
    conf.setdefault('media_root', os.path.join(settings.MEDIA_ROOT, reponame, path))
    conf.setdefault('media_url', os.path.join(settings.MEDIA_URL, reponame, path))
    conf.setdefault('static_url', os.path.join(settings.STATIC_URL, reponame))
    conf.setdefault('miniature_size', MINIATURE_SIZE)
    return conf 

REPOS = dict((n, get_repoconf(n)) for n in settings.GITHUB_UPLOADER_REPOS)

def get_auth_info(code, state):
    """Exchange a GitHub one-time auth code for an access token."""
    url = 'https://github.com/login/oauth/access_token'
    params = dict(
        client_id=settings.GITHUB_CLIENT_ID,
        client_secret=settings.GITHUB_CLIENT_SECRET,
        code=code,
        state=state,
        )
    headers = dict(Accept='application/json')
    req = requests.post(url, params=params, headers=headers, timeout=GITHUB_TIMEOUT)
    if req.status_code != 200:
        return None
    try:
        return json.loads(req.text)
    except:
        return None
    
def is_member(access_token, organization):
    """Not used. We now only care acout repo push permission."""
    url = 'https://api.github.com/user/orgs'
    headers = dict(
        Accept='application/json',
        Authorization='token ' + access_token)
    req = requests.get(url, headers=headers, timeout=GITHUB_TIMEOUT)
    if req.status_code != 200:
        return False
    try:
        return organization in (o['login'] for o in json.loads(req.text))
    except:
        return False

def has_push_permission(access_token, repo_full_name):
    url = 'https://api.github.com/user/repos'
    headers = dict(
        Accept='application/json',
        Authorization='token ' + access_token)
    req = requests.get(url, headers=headers, timeout=GITHUB_TIMEOUT)
    if req.status_code != 200:
        return False
    try:
        for r in json.loads(req.text):
            if r['full_name'] == repo_full_name:
                return r['permissions']['push']
    finally:
        return False

def get_username(access_token):
    url = 'https://api.github.com/user'
    headers = dict(
        Accept='application/json',
        Authorization='token ' + access_token)
    req = requests.get(url, headers=headers, timeout=GITHUB_TIMEOUT)
    if req.status_code != 200:
        return None

    try:
        return json.loads(req.text)['login']
    except:
        return None

def create_file(access_token, file, full_name, branch, path, filename):
    """PyGitHub does not yet support the create/update file API."""
    
    "PUT /repos/:owner/:repo/contents/:path"
    url = 'https://api.github.com/repos/%s/contents/%s/%s'
    url %= (full_name, path, filename)
    
    headers = dict(
        Accept='application/json', 
        Authorization='token ' + access_token,
        )
    data = dict(
        content=base64.b64encode(file.read()),
        message='Upload %s\n\nUploaded through media uploader service.' % filename,
        branch=branch,
        )
    return requests.put(url, json.dumps(data), headers=headers)

def revoke_access_token(token):
    gh_revoke_url = ('https://api.github.com/applications/%s/tokens/%s' % 
        (settings.GITHUB_CLIENT_ID, token))
    gh_auth = (settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET)
    return requests.delete(gh_revoke_url, auth=gh_auth, timeout=GITHUB_TIMEOUT)

def successful_revocation(token):
    req = revoke_access_token(token)
    return req.status_code == 204 # 204 No Content
