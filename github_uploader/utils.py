
### GENERAL PURPOSE ###

def getattrs(obj, attr_names=[], alias={}):
    """Get attribute values as a dict.
    
    obj can be any object. 
    attr_names should be attribute names. 
    alias is an attr_name:alias dict of attributes that should be renamed.
    
    Good for pulling of initial form data out of models objects.
    """
    return dict((alias.get(attr, attr), getattr(obj, attr)) for attr in attr_names)

def setattrs(obj, update, names=None, alias={}):
    """Set attributes from a dict.
    
    obj can be any object.
    update should be a dict with new values.
    names should be attribute names to set/update. None means all.
    alias should be a name:attrname dict. Useful if names are mismatched.  
    """
    if names is None:
        names = update
    for name in names:
        setattr(obj, alias.get(name, name), update[name])

### FORMS ###
        
def get_initial(obj, form):
    """Get a dict of potential initial data for form using obj attrs with same names."""
    return getattrs(obj, form.fields)

def get_form(form_class, request, **extra):
    """Instantiate a form and check if it is filled-out and valid.
    
    Returns (bool, form) where the former is True only if the form is 
    filled-out and .is_valid().
    
    This is a simple helper for untangling the often prosaic but convoluted 
    code paths of standard Django form handling boilerplate code.
    """
    if request.method == 'POST':
        form = form_class(request.POST, request.FILES, **extra) # Return filled-in form
        return form.is_valid(), form
    return False, form_class(**extra) # Present empty form
