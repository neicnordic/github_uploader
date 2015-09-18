from django.conf import settings
from django.contrib.auth import backends
from django.contrib.auth.models import User
from django.contrib.messages import error
import json
import requests

from .github import get_access_token, get_username, is_member

class GitHubOrgMemberBackend(backends.ModelBackend):
    """Github OAuth2 login handling, and org membership validation.
    
    Warning: Uses session variables for passing crypto info. 
    
    Do not configure django to store session data client side!
    
    Needs the following django settings:
    * GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET from GitHub application registration.
    * GITHUB_ORGANIZATION: "login name" of github organization to authorize against. 
    
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
        saved_state = request_with_github_code.session.pop('github_oauth_state', None)
        if not saved_state: 
            return None
        if reported_state != saved_state:
            return None

        requested_scope = sorted(settings.GITHUB_SCOPE.split(','))
        granted_scope = sorted(request_with_github_code.session.pop('github_oauth_scopes', '').split(','))
        if granted_scope != requested_scope:
            error('You did not grant all permissions needed by this service.')
            return None
        access_token = get_access_token(code, saved_state)
        if not access_token:
            return None

        # The user successfully signed in to GitHub and granted the necessary permissions.
        # Are they members of the org?

        username = get_username(access_token)
        if not username:
            return None
        if not is_member(access_token, settings.GITHUB_ORGANIZATION):
            msg = ('You are not a member of %s: ask your project leader or area coordinator to invite you.')
            error(msg % settings.GITHUB_ORGANIZATION)
            return None
        
        # The user is member of the organization and is thus ok for us to let in.
        # We don't check for is_active(), since account management and auth should
        # be done on github. 
        
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.save()
        request_with_github_code.session['github_access_token'] = access_token

        return user
    
        
