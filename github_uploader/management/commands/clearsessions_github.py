from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from github_uploader.github import successful_revocation, revoke_access_token

class Command(BaseCommand):
    help = (
        "Like the clearsessions command, but also revokes stored github "
        "access tokens for expired sessions."
    )

    def handle(self, **options):
        # Backend check is hard coded, because the "right" way of finding out if 
        # engine.SessionStore.clear_expired() is supported by the current  
        # backend is to call it, and catch exception if it isn't, but I 
        # don't want to call it. I want to do it myself, to be able to do 
        # revoke before delete in a controlled manner.
        if settings.SESSION_ENGINE != 'django.contrib.sessions.backends.db':
            # The clearesessions command prints to stderr and returns None on error.
            self.stderr.write("Session engine '%s' doesn't support clearing "
                              "expired sessions.\n" % settings.SESSION_ENGINE)
            return
        now = timezone.now()
        expired = []
        active_tokens = set([])
        active_userids = set([])
        for session in Session.objects.all():
            decoded = session.get_decoded()
            if session.expire_date < now:
                expired.append(session)
            else:
                token = decoded.get('github_access_token', None)
                if token:
                    active_tokens.add(token)
                    active_userids.add(decoded['_auth_user_id'])
        for session in expired:
            decoded = session.get_decoded()
            token = decoded.get('github_access_token', None)
            userid = decoded['_auth_user_id']
            if not token or token in active_tokens:
                session.delete()
                continue
            # This expired session has a token that is/should be revoked. 
            username = User.objects.filter(pk=userid)[0].username
            try:
                req = revoke_access_token(token)
            except:
                self.stderr.write('Fatal: Cannot connect with GitHub. Aborting.\n')
                return
            if req.status_code == 404:
                # GitHub API responds to basic auth failure with 404, not to disclose 
                # presence of user data.
                # https://developer.github.com/v3/auth/#basic-authentication 
                self.stderr.write('Fatal: GitHub authentication failure. Aborting.\n')
                return
            if req.status_code == 204: # 204 No Content
                session.delete()
                self.stdout.write('Non-active access token revoked for user %s.\n' % username)
                continue
            if session.expire_date + settings.GITHUB_REVOCATION_RETRY_PERIOD < now: 
                session.delete()
                self.stderr.write(
                    'Could not revoke non-active access token for user %s (status: %s). '
                    'Retry period has expired. Expired session deleted.\n' % (username, req.status_code))
                continue
            self.stderr.write(
                'Could not revoke non-active access token for user %s (status: %s). '
                'Keeping expired session for retry later.\n' % (username, req.status_code))
                    
