import logging

from django.contrib.auth import backends
from django.contrib.auth.models import User
from django.contrib.messages import error

from .github import UPLOADERS, get_auth_info, get_username, has_push_permission

logger = logging.getLogger('github_uploader')

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
            # This authenticator is one of potentially many different backends, we should expect duds. 
            logger.debug('Attempt to authenticate github user failed. Request contains no code in GET variables.')
            return None
        if not reported_state: 
            logger.warn('Cannot authenticate github user. Request has code but no state GET variable.')
            return None
        saved_state = request_with_github_code.session.pop('github_uploader_oauth_state', None)
        if not saved_state: 
            logger.critical('Cannot authenticate github user. Session has no saved state to compare with.')
            return None
        if reported_state != saved_state:
            logger.error('Cannot authenticate github user. Reported state %r does not match saved state %r: This is authentication attempt did not originate from this server and user.', reported_state, saved_state)
            return None
        uploadername = request_with_github_code.session.get('github_uploader_uploadername', None)
        if not uploadername:
            logger.critical('Cannot authorize github user. Session does not contain information on which uploader to authorize.')
            return None
        if not uploadername in UPLOADERS: 
            logger.critical('Cannot authorize github user. Authorization attempt against nonexisting uploader %r.', uploadername)
            return None
        repoconf = UPLOADERS[uploadername]

        auth_info = get_auth_info(code, saved_state)
        if not auth_info:
            logger.critical('Cannot authorize github user for uploader %s. Could not exchange github one-time code for access token.', uploadername)
            return None

        access_token = auth_info.get('access_token', None)
        if not access_token:
            logger.critical('Cannot authorize github user for uploader %s. Access token message from github was not in the expected format.', uploadername)
            return None

        username = get_username(access_token)
        if not username:
            logger.critical('Cannot authorize github user for uploader %s. Username message from github was not in the expected format.', uploadername)
            return None
        
        granted_scope = ','.join(sorted(auth_info.get('scope', '').split(',')))
        requested_scope = ','.join(sorted(repoconf['scope'].split(',')))
        if granted_scope != requested_scope:
            logger.info('Cannot authorize github user %s for uploader %s. User granted scope %r does not match requested scope %r.', username, uploadername, granted_scope, requested_scope)
            error(request_with_github_code, 'You did not grant all permissions needed by this service.')
            return None

        # The user successfully signed in to GitHub and granted the requested scopes.

        if not has_push_permission(access_token, repoconf['full_name']):
            logger.info('Cannot authorize github user %r for uploader %s. User does not have push privileges to the %s repository.', username, uploadername, repoconf['full_name'])
            msg = 'You do not have push permission for repo %r: ask the repo owner to invite you.'
            error(request_with_github_code, msg % repoconf['full_name'])
            return None

        # The user has push permissions and is thus ok for us to let in.
        # We don't check for is_active(), since account management and auth should
        # be done on github. 
        
        user, created = User.objects.get_or_create(username=username)
        if created:
            logger.info('Created new github user %s.', username)
            user.save()

        logger.info('Github user %s authenticated and authorized to use uploader %s.', username, uploadername)
        request_with_github_code.session['github_access_token'] = access_token

        return user
