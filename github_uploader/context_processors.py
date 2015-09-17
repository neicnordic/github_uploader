from django.conf import settings

def site_settings(request):
    return dict(PRODUCTION=settings.PRODUCTION)
