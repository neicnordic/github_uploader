from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required 

def require_nothing(view):
    """Wrap the view function to require nothing."""
    @wraps(view)
    def wrapped_view(request, *args, **kw):
        request.authorization_checked = True
        return view(request, *args, **kw)
    return wrapped_view
    
def require_login(view, *args, **kw):
    """Django's login_required, made neicweb middleware compliant."""
    @wraps(view)
    def wrapped_view(request, *w_args, **w_kw):
        request.authorization_checked = True
        return login_required(view, *args, **kw)(request, *w_args, **w_kw)
    return wrapped_view
