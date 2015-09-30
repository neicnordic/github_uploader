from django.conf import settings
import json
import requests

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
    req = requests.post(url, params=params, headers=headers)
    if req.status_code != 200:
        return None

    try:
        return json.loads(req.text)
    except:
        return None
    
def is_member(access_token, organization):
    url = 'https://api.github.com/user/orgs'
    headers = dict(
        Accept='application/json',
        Authorization='token ' + access_token)
    req = requests.get(url, headers=headers)
    if req.status_code != 200:
        return False

    try:
        return organization in (o['login'] for o in json.loads(req.text))
    except:
        return False


def get_username(access_token):
    url = 'https://api.github.com/user'
    headers = dict(
        Accept='application/json',
        Authorization='token ' + access_token)
    req = requests.get(url, headers=headers)
    if req.status_code != 200:
        return None

    try:
        return json.loads(req.text)['login']
    except:
        return None

def revoke_access_token(token):
    gh_revoke_url = ('https://api.github.com/applications/%s/tokens/%s' % 
        (settings.GITHUB_CLIENT_ID, token))
    gh_auth = (settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET)
    req = requests.delete(gh_revoke_url, auth=gh_auth)
    return req.status_code == 204 # 204 No Content
