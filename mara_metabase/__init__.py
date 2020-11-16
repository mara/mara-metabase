
def MARA_CONFIG_MODULES():
    from . import config
    return [config]

def MARA_FLASK_BLUEPRINTS():
    from . import views
    return [views.blueprint]

def MARA_CLICK_COMMANDS():
    from . import cli
    return [cli.setup, cli.update_metadata, cli.sync_acl]

def MARA_ACL_RESOURCES():
    from .views import acl_resource
    return {'Metabase': acl_resource}

def MARA_NAVIGATION_ENTRIES():
    from . import views
    return {'Metabase': views.navigation_entry()}

