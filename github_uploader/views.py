"""
Settings used:

settings.GITHUB_CLIENT_ID:
settings.GITHUB_CLIENT_SECRET:
    Get these from your GitHub Application page. Keep them secret.

settings.GITHUB_UPLOADER_REPOS:
    Dict of reponame:repoconf:
    reponame: most often the GitHub name of the repo.
    
    repoconf is dict of key:value
    full_name: url components "owner/reponame", like "neicnordic/neicweb". Required.
    description: Short human understandable description of the repo. Default is ''.
    hidden: Do not advertize on first page. Default is False.  
    scope: github scope necessary to access this repo, default is 
        settings.GITHUB_UPLOADER_SCOPE.
    branch: branch to upload to, default is 'master'.
    path: path to dir to upload to, default is settings.GITHUB_UPLOADER_PATH.
    media_root: path to local copy of upload dir, for checking for collisions.
        Default is os.path.join(settings.MEDIA_ROOT, reponame, path). Explicitly
        setting this empty or None disables collision check.
    media_url: url to dir where uploads will eventually end up, for showing results.
        Default is os.path.join(settings.MEDIA_URL, reponame, path).
    static_url: url to dir where to find the staticfiles for the github_uploader app 
        for this repo. Default is settings.STATIC_URL.
    miniature_size: (X, Y) max size of miniatures in pixels. 0 means 
       proportionally scale to fit other dimension. (0, 0) is illegal. Default
       is (200, 0).

settings.GITHUB_UPLOADER_SCOPE:
    Default github scope necessary to access repos. Default is 'public_repos'.  

settings.GITHUB_UPLOADER_PATH
    In-repo path to upload to. Default is 'media'. 

"""

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

from github import MINIATURE_SIZE, REPOS, create_file, successful_revocation

def top(request):
    full_repoconf = tuple(it for it in sorted(REPOS.items()) if not it[1]['hidden'])
    return render(request, 'github_uploader/top.html', dict(repos=full_repoconf, STATIC_URL=settings.STATIC_URL))

### Login / logout ###

def make_random_state():
    r = SystemRandom()
    chars = string.printable.strip()
    return ''.join(r.choice(chars) for _ in range(20))

def login_redirect(request, reponame):
    repoconf = REPOS[reponame]
    old_access_token = request.session.pop('github_access_token', None)
    if old_access_token:
        request.session.pop('github_uploader_scope', None)
        request.session.pop('github_uploader_reponame', None)
        if not successful_revocation(old_access_token):
            msg = mark_safe(
                'Could not automatically revoke the old authorizations before requesting new ones. Please ' 
                '<a href="https://github.com/settings/applications">' +
                'review your application authorizations on GitHub</a> ' + 
                'and manually click Revoke for any authorizations you no longer need or do not recognize.')
            messages.warning(request, msg)
        auth.logout(request)
    state = make_random_state()
    request.session['github_uploader_oauth_state'] = state
    request.session['github_uploader_reponame'] = reponame
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
        return redirect(upload, request.session.pop('github_uploader_reponame'))
    messages.error(request, 'Login failed.')
    return redirect(top)

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
            width, height = self.min
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

def get_templates(reponame, template_name):
    return [
        'github_uploader/%s/%s' % (reponame, template_name), 
        'github_uploader/' + template_name]

def get_tree_url(repoconf):
    return "https://github.com/%(full_name)s/tree/%(branch)s/%(path)s" % repoconf

def get_tree_link(repoconf):
    return '<a href="%s">GitHub tree</a>' % get_tree_url(repoconf)

def upload_file(request, context, access_token, reponame, filename, content, errmsg_label):
    repoconf = REPOS[reponame]
    templates = get_templates(reponame, 'upload.html')
    response = create_file(
        access_token, content, repoconf['full_name'], 
        repoconf['branch'], repoconf['path'], filename)
    if response.status_code == 404: 
        # GitHub says "not found" on perms error.
        msg = (errmsg_label +
            ' upload failed, possibly due to insufficient permissions. ' +
            'Please check %s, and retry after reviewing your authorizations.')
        messages.error(request, mark_safe(msg % get_tree_link(repoconf)))
        return login_redirect(request, reponame)
    if response.status_code != 201: # CREATED
        messages.error(request, mark_safe(errmsg_label + ' upload failed. Please check %s.' % get_tree_link(repoconf)))
        return render(request, templates, context)
    messages.success(request, errmsg_label + ' %s successfully uploaded.' % filename)
    return None # on success

def upload(request, reponame):
    """Media upload view; form handling logic for media uploads."""
    if not reponame in REPOS:
        raise Http404
    repoconf = REPOS[reponame]
    current_scope = request.session.get('github_uploader_scope', None)
    current_reponame = request.session.get('github_uploader_reponame', None)
    if not (request.user.is_authenticated() and 
            current_scope == repoconf['scope'] and
            current_reponame == reponame):
        return login_redirect(request, reponame)

    context = dict(reponame=reponame, repo=repoconf)
    templates = get_templates(reponame, 'upload.html')
    
    if repoconf['media_root']:
        existing = os.listdir(repoconf['media_root'])
        context.update(existing_json=json.dumps(existing))
        
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
            request, context, access_token, reponame, form.cleaned_data['filename_miniature'], 
            form.cleaned_data['miniature'], 'Miniature file')
        if bailout_response is not None:
            return bailout_response
        
    bailout_response = upload_file(
        request, context, access_token, reponame, form.cleaned_data['filename'], 
        form.cleaned_data['file'], 'Miniature file')
    if bailout_response is not None:
        return bailout_response
    
    return redirect(reverse(show, args=(reponame,)) + '?' + urlencode(success_redirect_get_params))

def show(request, reponame):
    if not reponame in settings.GITHUB_UPLOADER_REPOS:
        raise Http404
    repoconf = REPOS[reponame]
    current_scope = request.session.get('github_uploader_scope', None)
    current_reponame = request.session.get('github_uploader_reponame', None)
    if not (request.user.is_authenticated() and 
            current_scope == repoconf['scope'] and
            current_reponame == reponame):
        return login_redirect(request, reponame)
    
    templates = get_templates(reponame, 'show.html')

    context = dict(
        file=request.GET.get('file', None),
        mini=request.GET.get('mini', None),
        github_tree_url=get_tree_url(repoconf),
        github_tree_link=get_tree_link(repoconf),
        MEDIA_URL=repoconf['media_url'],
        STATIC_URL=repoconf['static_url'],
        repo=repoconf,
        reponame=reponame,
        )
    
    return render(request, templates, context)
