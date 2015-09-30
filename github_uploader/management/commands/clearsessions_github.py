from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from github_uploader.github import revoke_access_token 

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
        expired = []
        active_tokens = set([])
        active_users = set([])
        for session in Session.objects.all():
            decoded = session.get_decoded()
            if session.expire_date < timezone.now():
                expired.append(session)
            else:
                active_tokens.add(decoded['github_access_token'])
                active_users.add(decoded['_auth_user_id'])
        for session in expired:
            decoded = session.get_decoded()
            username = User.objects.filter(pk=decoded['_auth_user_id'])[0].username
            token = decoded['github_access_token']
            if token not in active_tokens:
                revoked = revoke_access_token(token)
                if revoked:
                    self.stdout.write('Non-active access token revoked for user %s.\n' % username)
                    session.delete()
                    continue
                self.stderr.write('Could not revoke non-active access token for user %s. Did they revoke it themselves?\n' % username)
                    
