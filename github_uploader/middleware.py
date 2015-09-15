from django.http import HttpResponseBadRequest

class CheckAuthorization(object):
    def process_response(self, request, response):
        # Pass everything but normal pages through
        if response.status_code != 200:
            return response
        
        # Assume this is a normal response page, and check if it has been checked by a decorator like
        # @require_staff or @require_login. For views that really does not require
        # an authenticated user (such as the login page), use @require_nothing.

        if getattr(request, "authorization_checked", False):
            return response

        # Complain
        return HttpResponseBadRequest("Authorization check lacking in %s" %
                                      request.path)
        
    
