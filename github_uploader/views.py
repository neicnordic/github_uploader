import base64
from random import SystemRandom
import os
import re
import requests
import string

from django.conf import settings
from django.contrib import auth
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.forms import CharField, FileField, Form, ImageField
from django.shortcuts import redirect, render
from django.utils.translation import ugettext_lazy as _
from urllib import urlencode
import json

from decorators import require_nothing, require_login

@require_nothing
def top(request):
    return render(request, 'github_uploader/top.html')

### Login / logout ###

def make_random_state():
    r = SystemRandom()
    chars = string.printable.strip()
    return ''.join(r.choice(chars) for _ in range(20))

@require_nothing
def login(request):
    if request.method == 'POST':
        state = make_random_state()
        request.session['github_oauth_state'] = state
        params = dict(
            client_id=settings.GITHUB_CLIENT_ID,
            redirect_uri=request.build_absolute_uri(reverse(authorize)),
            scope="repo,read:org",
            state=state)
        return redirect('https://github.com/login/oauth/authorize?' + urlencode(params))
    return render(request, 'github_uploader/login.html')

@require_nothing
def authorize(request):
    user = auth.authenticate(request_with_github_code=request)
    if user and user.is_active:
        auth.login(request, user)
        messages.success(request, 'You are now logged in. Please enjoy responsibly.')
        return redirect(top)
    messages.error(request, 'Login failed.')
    return redirect(login)

@require_nothing
def logout(request):
    if request.method == 'POST':
        auth.logout(request)
        messages.success(request, 'You are now logged out.')
        return redirect(top)
    return render(request, 'github_uploader/logout.html')
    
### Uploads ###

class FilenameField(CharField):
    """A draconian filename field."""
    default_error_messages = {
        'invalid_filename': _("Contains illegal characters %s."),
        'dotfile': _("Must not start with a . character."),
        }
        
    def validate(self, data):
        super(CharField, self).validate(data)
        illegal = re.findall(r'[^A-Za-z0-9-_.]', data)
        if illegal:
            raise ValidationError(self.error_messages['invalid_filename'] % ''.join(illegal))
        if data.startswith('.'):
            raise ValidationError(self.error_messages['dotfile'])
            
class UploadForm(Form):
    image = FileField(required=True)
    filename = FilenameField(required=True)
    filename_mini = FilenameField()

    def __init__(self, *args, **kw):
        existing = kw.pop('existing', [])
        super(Form, self).__init__(*args, **kw)
        self.existing = existing or []
        
    def _assert_nonexisting(self, name):
        if name in self.existing:
            raise ValidationError(_("The filename %s already exists.") % name)
            
    def clean_filename(self):
        self._assert_nonexisting(self.cleaned_data['filename'])
        return self.cleaned_data['filename']

    def clean_filename_mini(self):
        self._assert_nonexisting(self.cleaned_data['filename_mini'])
        return self.cleaned_data['filename_mini']

    def clean(self):
        filename_mini = self.cleaned_data['filename_mini']
        if filename_mini:
            filename = self.cleaned_data['filename']
            if os.path.splitext(filename)[1] != os.path.splitext(filename_mini)[1]:
                raise ValidationError(_("The filenames must have the same extensions."))
            try:
                ImageField().clean(self.cleaned_data['image'])
            except ValidationError, e:
                raise ValidationError(_("Cannot make miniatures from non-image files. %s") % e.messages)
        return self.cleaned_data

def do_upload(access_token, content, filename):
    """PyGitHub does not yet support the create/update file API."""
    
    "PUT /repos/:owner/:repo/contents/:path"
    url = 'https://api.github.com/repos/%s/%s/contents/media/%s'
    url %= (settings.GITHUB_ORGANIZATION, settings.GITHUB_REPO, filename)
    
    headers = dict(Accept='application/vnd.github.v3+json')
    params = dict(
        access_token=access_token,
        content=base64.b64encode(content),
        message='Upload %s\n\nUploaded through media uploader service.' % filename,
        )
    r = requests.put(url, params=params, headers=headers)
    

@require_login
def upload(request):
    """Media upload view; form handling logic for media uploads."""
    existing = os.listdir(settings.MEDIA_ROOT)
    context = dict(success=False, existing_json=json.dumps(existing))
    ok_to_upload = False
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        ok_to_upload = form.is_valid() 
        context['errors'] = form._errors

    if not ok_to_upload:
        return render(request, 'github_uploader/upload.html', context)
    
    # Ok to upload
    
    context['filename'] = form.cleaned_data['filename']
    context['filename_mini'] = form.cleaned_data['filename_mini']
    
    
    render(request, 'github_uploader/upload-success.html', context)
                    