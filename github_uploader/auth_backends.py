from django.conf import settings
from django.contrib.auth import backends
from django.contrib.auth.models import User
import json

import requests
from github import Github


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
        
        # The user has successfully signed in to github, so exchange the 
        # one-time code for an auth token, and proceed to check org membership.
        params = dict(
            client_id=settings.GITHUB_CLIENT_ID,
            client_secret=settings.GITHUB_CLIENT_SECRET,
            code=code,
            state=saved_state,
            )
        headers = dict(Accept='application/vnd.github.v3+json')
        req = requests.post('https://github.com/login/oauth/access_token', params=params, headers=headers)
        if req.status_code != 200:
            return None
        
        try:
            auth_info = json.loads(req.text)
        except:
            return None
        access_token = auth_info.get('access_token', None)
        token_type = auth_info.get('access_token', None)
        if not access_token:
            return None
        if not token_type:
            return None 
        
        github_client = Github(access_token)
        github_user = github_client.get_user()
        username = github_user.login 
        if not username:
            return None
        
        member_of_org = False
        for org in github_user.get_orgs():
            if org.login == settings.GITHUB_ORGANIZATION:
                member_of_org = True
                break
        if not member_of_org:
            return None
        
        # The user is member of the organization and is thus ok for us to let in.
        # We don't check for is_active(), since account management and auth should
        # be done on github. 
        
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.save()
        request_with_github_code.session['github_access_token'] = access_token
        request_with_github_code.session['github_client'] = github_client

        return user
    
        
