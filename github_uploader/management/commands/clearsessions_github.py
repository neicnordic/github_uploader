from importlib import import_module

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
        engine = import_module()
        # Hard coded, because the "right" way of finding out if 
        # engine.SessionStore.clear_expired() is supported by the current  
        # backend is to call it, and catch exception if it isn't, but I 
        # don't want to call it. I want to do it myself, to be able to do 
        # revoke before delete in a controlled manner.
        if settings.SESSION_ENGINE != 'django.contrib.sessions.backends.db':
            # The clearesessions command prints to stderr and returns None on error.
            self.stderr.write("Session engine '%s' doesn't support clearing "
                              "expired sessions.\n" % settings.SESSION_ENGINE)
            return
        expired = Session.objects.filter(expire_date__lt=timezone.now())
        for session in expired:
            revoked = revoke_access_token(session['github_access_token'])
            if revoked:
                session.delete()
                continue
            decoded = session.get_decoded()
            username = None
            try:
                username = User.objects.filter(pk=decoded['_auth_user_id'])[0]
            except:
                pass
            msg = "Could not revoke access token for session " + session.session_key
            if username:
                msg += " for user " + username
            self.stderr.write(msg + ".\n")
