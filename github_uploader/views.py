import logging
import os
from random import SystemRandom
import re
import string
from StringIO import StringIO

from django.conf import settings
from django.contrib import auth
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.forms import CharField, FileField, Form, ImageField
from django.shortcuts import Http404, redirect, render
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from PIL import Image
from urllib import urlencode
import json

from github import MINIATURE_SIZE, UPLOADERS, create_file, successful_revocation

logger = logging.getLogger('github_uploader')

def top(request):
    advertized_uploaders = tuple(item for item in sorted(UPLOADERS.items()) if not item[1]['hidden'])
    return render(request, 'github_uploader/top.html', dict(uploaders=advertized_uploaders, STATIC_URL=settings.STATIC_URL))

### Login / logout ###

def make_random_state():
    r = SystemRandom()
    chars = string.printable.strip()
    return ''.join(r.choice(chars) for _ in range(20))

def login_redirect(request, uploadername):
    repoconf = UPLOADERS[uploadername]
    old_access_token = request.session.pop('github_access_token', None)
    if old_access_token:
        request.session.pop('github_uploader_scope', None)
        request.session.pop('github_uploader_uploadername', None)
        if not successful_revocation(old_access_token):
            msg = mark_safe(
                'Could not automatically revoke the old authorizations before requesting new ones. Please ' 
                '<a href="https://github.com/settings/applications">' +
                'review your application authorizations on GitHub</a> ' + 
                'and manually click Revoke for any authorizations you no longer need or do not recognize.')
            messages.warning(request, msg)
            logger.warn("Could not revoke previous access token for user %s on login.", request.user.username)
        auth.logout(request)
    state = make_random_state()
    request.session['github_uploader_oauth_state'] = state
    request.session['github_uploader_uploadername'] = uploadername
    request.session['github_uploader_scope'] = repoconf['scope']
    params = dict(
        client_id=settings.GITHUB_UPLOADER_CLIENT_ID,
        redirect_uri=request.build_absolute_uri(reverse(authorize)),
        scope=repoconf['scope'],
        state=state)
    return redirect('https://github.com/login/oauth/authorize?' + urlencode(params))

def authorize(request):
    user = auth.authenticate(request_with_github_code=request)
    if user:
        auth.login(request, user)
        messages.success(request, 'You are now logged in. Please enjoy responsibly, and log out when you are done.')
        return redirect(upload, request.session['github_uploader_uploadername'])
    messages.error(request, 'Login failed.')
    return redirect(top)

def logout(request):
    if request.method == 'POST':
        revoked = successful_revocation(request.session['github_access_token'])
        if revoked:
            del request.session['github_access_token']
            logger.info("User %s logged out.", request.user.username)
            messages.success(request, 'GitHub authorizations successfully revoked.')
        else:
            msg = mark_safe(
                'Could not revoke GitHub authorizations. Please ' 
                '<a href="https://github.com/settings/applications">'
                'review your application authorizations on GitHub</a> ' 
                'and manually click Revoke for any authorizations you no longer need or do not recognize.')
            messages.error(request, msg)
            logger.warn("Could not revoke access token for user %s on logout.", request.user.username)
        auth.logout(request)
        messages.success(request, 'You are now logged out.')
        return redirect(top)
    return render(request, 'github_uploader/logout.html', dict(STATIC_URL=settings.STATIC_URL))
    
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
    file = FileField()
    filename = FilenameField()
    filename_miniature = FilenameField(required=False)
    
    def __init__(self, *args, **kw):
        existing = kw.pop('existing', [])
        miniature_size = kw.pop('miniature_size', MINIATURE_SIZE)
        super(Form, self).__init__(*args, **kw)
        self.existing = existing or []
        self.miniature_size = miniature_size or MINIATURE_SIZE
        
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
            width, height = self.miniature_size
            if orig_width <= width or orig_height <= height:
                raise ValidationError(_("Image is too small, miniatures should be at least %sx%spx." % self.miniature_size))
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

def get_templates(uploadername, template_name):
    return [
        'github_uploader/%s/%s' % (uploadername, template_name), 
        'github_uploader/' + template_name]

def get_tree_url(repoconf):
    return "https://github.com/%(full_name)s/tree/%(branch)s/%(path)s" % repoconf

def get_tree_link(repoconf):
    return '<a href="%s">GitHub tree</a>' % get_tree_url(repoconf)

def upload_file(request, context, access_token, uploadername, filename, content, errmsg_label):
    repoconf = UPLOADERS[uploadername]
    templates = get_templates(uploadername, 'upload.html')
    response = create_file(
        access_token, content, repoconf['full_name'], 
        repoconf['branch'], repoconf['path'], filename)
    if response.status_code == 404: 
        # GitHub says "not found" on perms error.
        msg = (errmsg_label +
            ' upload failed, possibly due to insufficient permissions. ' +
            'Please check %s, and retry after reviewing your authorizations.')
        messages.error(request, mark_safe(msg % get_tree_link(repoconf)))
        logger.warn("Upload failed with status code 404 for user %s file %r to repo %s branch %s path %s", request.user.username, filename, repoconf['full_name'], repoconf['branch'], repoconf['path'])
        return login_redirect(request, uploadername)
    if response.status_code != 201: # CREATED
        logger.warn("Upload failed with status code %s for user %s file %r to repo %s branch %s path %s", response.status_code, request.user.username, filename, repoconf['full_name'], repoconf['branch'], repoconf['path'])
        messages.error(request, mark_safe(errmsg_label + ' upload failed. Please check %s.' % get_tree_link(repoconf)))
        return render(request, templates, context)
    logger.info("User %s uploaded file %r to repo %s branch %s path %s", request.user.username, filename, repoconf['full_name'], repoconf['branch'], repoconf['path'])
    messages.success(request, errmsg_label + ' %s successfully uploaded.' % filename)
    return None # on success

def upload(request, uploadername):
    """Media upload view; form handling logic for media uploads."""
    if not uploadername in UPLOADERS:
        raise Http404
    repoconf = UPLOADERS[uploadername]
    current_scope = request.session.get('github_uploader_scope', None)
    current_uploadername = request.session.get('github_uploader_uploadername', None)
    if not (request.user.is_authenticated() and 
            current_scope == repoconf['scope'] and
            current_uploadername == uploadername):
        return login_redirect(request, uploadername)

    templates = get_templates(uploadername, 'upload.html')
    existing = []
    if repoconf['media_root']:
        existing = os.listdir(repoconf['media_root'])

    context = dict(
        uploadername=uploadername,
        repoconf=repoconf,
        existing_json=json.dumps(existing),
        STATIC_URL=repoconf['static_url'],
        )
    
    ok_to_upload = False
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES, existing=existing, miniature_size=repoconf['miniature_size'])
        ok_to_upload = form.is_valid() 
        context['form'] = form

    if not ok_to_upload:
        return render(request, templates, context)
    
    # Ok to upload
    access_token = request.session['github_access_token']
    success_redirect_get_params = dict(file=form.cleaned_data['filename'])

    if form.cleaned_data['filename_miniature']:
        success_redirect_get_params.update(mini=form.cleaned_data['filename_miniature'])
        bailout_response = upload_file(
            request, context, access_token, uploadername, form.cleaned_data['filename_miniature'], 
            form.cleaned_data['miniature'], 'Miniature file')
        if bailout_response is not None:
            return bailout_response
        
    bailout_response = upload_file(
        request, context, access_token, uploadername, form.cleaned_data['filename'], 
        form.cleaned_data['file'], 'File')
    if bailout_response is not None:
        return bailout_response
    
    return redirect(reverse(show, args=(uploadername,)) + '?' + urlencode(success_redirect_get_params))

def show(request, uploadername):
    if not uploadername in UPLOADERS:
        raise Http404
    repoconf = UPLOADERS[uploadername]
    current_scope = request.session.get('github_uploader_scope', None)
    current_uploadername = request.session.get('github_uploader_uploadername', None)
    if not (request.user.is_authenticated() and 
            current_scope == repoconf['scope'] and
            current_uploadername == uploadername):
        return login_redirect(request, uploadername)
    
    templates = get_templates(uploadername, 'show.html')

    context = dict(
        file=request.GET.get('file', None),
        mini=request.GET.get('mini', None),
        github_tree_url=get_tree_url(repoconf),
        github_tree_link=get_tree_link(repoconf),
        MEDIA_URL=repoconf['media_url'],
        STATIC_URL=repoconf['static_url'],
        repoconf=repoconf,
        uploadername=uploadername,
        )
    
    return render(request, templates, context)
