import base64
from random import SystemRandom
import os
import re
import requests
import string
from StringIO import StringIO

from django.conf import settings
from django.contrib import auth
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.forms import CharField, FileField, Form, ImageField
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from PIL import Image
from urllib import urlencode
import json

from decorators import require_nothing, require_login
from github import successful_revocation

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
            scope=settings.GITHUB_SCOPE,
            state=state)
        return redirect('https://github.com/login/oauth/authorize?' + urlencode(params))
    return render(request, 'github_uploader/login.html')

@require_nothing
def authorize(request):
    user = auth.authenticate(request_with_github_code=request)
    if user and user.is_active:
        auth.login(request, user)
        messages.success(request, 'You are now logged in. Please enjoy responsibly, and log out when you are done.')
        return redirect(upload)
    messages.error(request, 'Login failed.')
    return redirect(login)

@require_nothing
def logout(request):
    if request.method == 'POST':
        revoked = successful_revocation(request.session['github_access_token'])
        if revoked:
            del request.session['github_access_token']
            messages.success(request, 'GitHub authorizations successfully revoked.')
        else:
            msg = mark_safe(
                'Could not revoke GitHub authorizations. Please ' 
                '<a href="https://github.com/settings/applications">'
                'review your application authorizations on GitHub</a> ' 
                'and manually click Revoke for any authorizations you no longer need or do not recognize.')
            messages.error(request, msg)
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

MINIATURE_SIZE = getattr(settings, 'MINIATURE_SIZE', (200, 0))
if MINIATURE_SIZE[0] == MINIATURE_SIZE[1] == 0:
    raise ValueError('django.conf.settings.MINIATURE_SIZE cannot be (0, 0).')

class UploadForm(Form):
    file = FileField()
    filename = FilenameField()
    filename_miniature = FilenameField(required=False)
    
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

    def clean_filename_miniature(self):
        self._assert_nonexisting(self.cleaned_data['filename_miniature'])
        return self.cleaned_data['filename_miniature']

    def clean(self):
        filename_miniature = self.cleaned_data.get('filename_miniature', None)
        if filename_miniature:
            filename = self.cleaned_data['filename']
            if filename == filename_miniature:
                raise ValidationError(_("The filenames must be different."))
            if os.path.splitext(filename)[1] != os.path.splitext(filename_miniature)[1]:
                raise ValidationError(_("The filenames must have the same extensions."))
            try:
                ImageField().clean(self.cleaned_data['file'])
            except ValidationError, e:
                raise ValidationError(_("Cannot make miniatures from non-image files. The file you uploaded was either not an image or a corrupted image."))

            image = Image.open(self.cleaned_data['file'])
            orig_width, orig_height = image.size
            width, height = MINIATURE_SIZE
            if orig_width <= width or orig_height <= height:
                raise ValidationError(_("Image is too small, miniatures should be at least %sx%spx." % MINIATURE_SIZE))
            if width == 0:
                width = int(float(orig_width) / orig_height * height)
            if height == 0:
                height = int(float(orig_height) / orig_width * width)
            size = (width, height)
            mini = image.resize(size, Image.ANTIALIAS)
            miniature = StringIO() 
            mini.save(miniature, image.format)
            miniature.seek(0)
            self.cleaned_data['miniature'] = miniature

            self.cleaned_data['miniature'].seek(0)
            self.cleaned_data['file'].seek(0)
            
        return self.cleaned_data

def do_upload(access_token, file, filename):
    """PyGitHub does not yet support the create/update file API."""
    
    "PUT /repos/:owner/:repo/contents/:path"
    url = 'https://api.github.com/repos/%s/%s/contents/%s/%s'
    url %= (
        settings.GITHUB_ORGANIZATION, 
        settings.GITHUB_REPO, 
        settings.GITHUB_PATH, 
        filename)
    
    headers = dict(
        Accept='application/json', 
        Authorization='token ' + access_token,
        )
    data = dict(
        content=base64.b64encode(file.read()),
        message='Upload %s\n\nUploaded through media uploader service.' % filename,
        )
    r = requests.put(url, json.dumps(data), headers=headers)
    return r.status_code == 201 # CREATED

tree_url = "https://github.com/%s/%s/tree/master/%s" % ( 
    settings.GITHUB_ORGANIZATION,
    settings.GITHUB_REPO,
    settings.GITHUB_PATH
    )

tree_link = '<a href="%s">GitHub tree</a>' % tree_url

@require_login
def upload(request):
    """Media upload view; form handling logic for media uploads."""
    existing = os.listdir(settings.MEDIA_ROOT)
    context = dict(existing_json=json.dumps(existing))
    ok_to_upload = False
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        ok_to_upload = form.is_valid() 
        context['form'] = form

    if not ok_to_upload:
        return render(request, 'github_uploader/upload.html', context)
    
    # Ok to upload
    access_token = request.session['github_access_token']
    f = form.cleaned_data['file']
    filename = form.cleaned_data['filename']
    filename_miniature = form.cleaned_data['filename_miniature']
    
    params = dict(file=filename)
    success = do_upload(access_token, f, filename)
    if not success:
        messages.error(request, mark_safe('File upload failed. Please check %s.' % tree_link))
        return render(request, 'github_uploader/upload.html', context)

    messages.success(request, 'File %s successfully uploaded.' % filename)

    if filename_miniature:
        params.update(mini=filename_miniature)
        miniature = form.cleaned_data['miniature']
        success = do_upload(access_token, miniature, filename_miniature)
        if not success:
            messages.error(request, mark_safe('Miniature file upload failed. Please check %s.' % tree_link))
            return render(request, 'github_uploader/upload.html', context)

        messages.success(request, 'Miniature file %s successfully uploaded.' % filename_miniature)
    
    return redirect(reverse(show) + '?' + urlencode(params))


@require_login
def show(request):
    context = dict(
        file=request.GET.get('file', None),
        mini=request.GET.get('mini', None),
        github_tree_url=tree_url,
        github_tree_link=tree_link,
        MEDIA_URL=settings.MEDIA_URL,
        )
    
    return render(request, 'github_uploader/show.html', context)
