from django.conf import settings
from django.contrib.auth import backends
from django.contrib.auth.models import User
from django.contrib.messages import error
import json
import requests

from .github import REPOS, get_auth_info, get_username, has_push_permission

class GitHubOrgMemberBackend(backends.ModelBackend):
    """Github OAuth2 login handling, and org membership validation.
    
    Warning: Uses session variables for passing crypto info. 
    
    Do not configure django to store session data client side!
    
    Needs the following django settings:
    * GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET from GitHub application registration.
    
    Needs the following session variables:
    * github_oauth_state: random unique string sent to github on initial auth redirect.
    
    Sets the following session variables on successful authorization:
    * github_access_token: can be used to act on behalf of the user in the github api.
    
    Creates users as necessary.
    """
    def authenticate(self, request_with_github_code):
        code = request_with_github_code.GET.get("code", None)
        reported_state = request_with_github_code.GET.get("state", None)
        if not code: 
            return None
        if not reported_state: 
            return None
        saved_state = request_with_github_code.session.pop('github_uploader_oauth_state', None)
        if not saved_state: 
            return None
        if reported_state != saved_state:
            return None
        reponame = request_with_github_code.session.get('github_uploader_reponame', None)
        if not reponame:
            return None
        if not reponame in REPOS: 
            return None
        repoconf = REPOS[reponame]

        auth_info = get_auth_info(code, saved_state)
        if not auth_info:
            return None

        access_token = auth_info.get('access_token', None)
        if not access_token:
            return None

        granted_scope = sorted(auth_info.get('scope', '').split(','))        
        requested_scope = sorted(repoconf['scope'].split(','))
        if granted_scope != requested_scope:
            error(request_with_github_code, 'You did not grant all permissions needed by this service.')
            return None

        # The user successfully signed in to GitHub and granted the requested scopes.

        if not has_push_permission(access_token, repoconf['full_name']):
            msg = 'You do not have push permission for repo %r: ask the repo owner to invite you.'
            error(request_with_github_code, msg % repoconf['full_name'])
            return None

        username = get_username(access_token)
        if not username:
            return None
        
        # The user has push permissions and is thus ok for us to let in.
        # We don't check for is_active(), since account management and auth should
        # be done on github. 
        
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.save()
        request_with_github_code.session['github_access_token'] = access_token

        return user
